"""核对固定业绩路线的领取、满额及继续规则。"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.operation.application_run_record import AppRunRecord
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.hollow_eval_speed.hollow_eval_speed_app import (
    HollowEvalSpeedApp,
)
from zzz_od.operation.gamepad import hollow_eval_run
from zzz_od.operation.gamepad.hollow_eval_exit import GamepadHollowEvalFinish
from zzz_od.operation.gamepad.hollow_eval_receipt import (
    GamepadHollowEvalMeritReceipt,
    confirms_weekly_merit_cap,
)


@pytest.mark.parametrize(('texts', 'expected'), [
    (['本周零号业绩获取已达上限'], True),
    (['本周零号业绩 900/900'], True),
    (['本周零号业绩 900/900', '本周零号业绩 600/900'], False),
    (['业绩考察点空', '调查点数900/900', '若本周零号业绩获取已达上限'], False),
])
def test_cap_requires_explicit_receipt(texts: list[str], expected: bool) -> None:
    assert confirms_weekly_merit_cap(texts) is expected


def test_merit_icon_needs_positive_amount_in_the_same_slot() -> None:
    icon = SimpleNamespace(x=30, y=40, w=90, h=90, confidence=0.95)
    op = GamepadHollowEvalFinish(SimpleNamespace(tm=Mock()), {})
    op.ctx.tm.match_template.return_value.max = icon
    matching_line = SimpleNamespace(center=SimpleNamespace(x=61, y=153))
    next_slot = SimpleNamespace(center=SimpleNamespace(x=185, y=152))
    op.navigation._read_area = Mock(return_value=(None, {'50': [matching_line], '1110': [next_slot]}))
    assert op._read_settlement_merit() == (True, 50)
    op.navigation._read_area.return_value = (None, {'1110': [next_slot]})
    assert op._read_settlement_merit() == (False, None)


def test_positive_merit_starts_next_expedition_until_verified_weekly_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    app = object.__new__(HollowEvalSpeedApp)
    app.ctx = SimpleNamespace(run_context=SimpleNamespace(is_context_running=True))
    app._after_round_wait = Mock()
    record = SimpleNamespace(
        run_status_under_now=AppRunRecord.STATUS_WAIT, daily_run_times=0, update_status=Mock(),
        check_and_update_status=Mock(), is_finished_by_day=Mock(return_value=False),
    )
    record.update = Mock(side_effect=lambda name, value, save: setattr(record, name, value))
    app.run_record = record
    receipts = iter((
        {'merit_increase': 50, 'weekly_cap_confirmed': False},
        {'merit_increase': None, 'weekly_cap_confirmed': True, 'weekly_cap_screenshot': '周满回执'},
    ))
    child = Mock(return_value=SimpleNamespace(execute=lambda: OperationResult(
        True, GamepadHollowEvalFinish.STATUS_RETURNED, next(receipts),
    )))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(hollow_eval_run, 'GamepadHollowEvalRun', child)
    assert app.check_first_screen().is_success
    assert child.call_count == 2
    assert record.daily_run_times == 2 and record.no_eval_point


def test_actual_hollow_award_captures_30_and_sends_confirmation_once() -> None:
    path = Path(__file__).resolve().parents[3] / 'screens/零号空洞-事件/手柄-零号业绩获得.webp'
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[376:848, 804:1115] = cv2_utils.read_image(str(path))
    screen_loader = ProfileScreenContext()
    screen_loader.reload()
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False))
    ctx = SimpleNamespace(screen_loader=screen_loader, tm=TemplateMatcher(TemplateLoader()), ocr=ocr, controller=Mock())
    op = GamepadHollowEvalMeritReceipt(ctx)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='当局业绩回执')
    op.last_screenshot = frame
    try:
        for _ in range(2):
            assert not op.try_confirm().is_fail
        assert op.pending == (30, '当局业绩回执')
        op.save_screenshot.assert_called_once_with(prefix='macos_hollow_eval_merit_award')
        ctx.controller.btn_tap.assert_called_once_with('south')
    finally:
        ocr.cleanup()


def test_exit_keeps_distinct_in_run_receipts_when_settlement_has_no_merit() -> None:
    op = GamepadHollowEvalFinish(SimpleNamespace(), {
        'screenshot': '停止点',
        'merit_receipts': [
            {'amount': 30, 'screenshot': '第一处'},
            {'amount': 30, 'screenshot': '第一处'},
            {'amount': 50, 'screenshot': '第二处'},
        ],
    })
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='街区')
    op._settlement = '无业绩的终止结算'
    assert op._returned().data['merit_increase'] == 80
