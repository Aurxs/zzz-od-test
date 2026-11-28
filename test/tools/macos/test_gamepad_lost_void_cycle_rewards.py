"""回放真实手柄奖励格，确认周期目标只在胜利和完整数据后更新。"""

import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import (
    LostVoidRunLevel,
)
from zzz_od.operation.gamepad import lost_void
from zzz_od.operation.gamepad.lost_void_result import (
    GamepadLostVoidBattleResult,
    LostVoidCycleProgress,
)


@pytest.fixture(scope='module')
def reward_reader() -> Iterator[GamepadLostVoidBattleResult]:
    """通过生产 OCR、区域和模板回放，不读取账号。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    assert ocr.init_model()
    screen_loader = ProfileScreenContext()
    screen_loader.reload()
    op = GamepadLostVoidBattleResult(SimpleNamespace(
        ocr=ocr, screen_loader=screen_loader, tm=TemplateMatcher(TemplateLoader()),
    ), read_cycle_rewards=True)
    try:
        yield op
    finally:
        ocr.cleanup()


@pytest.mark.parametrize(('name', 'expected'), (
    ('ios_final_s.webp', LostVoidCycleProgress(False, False)),
    ('ios_coreml_activity7_result.webp', LostVoidCycleProgress(True, False)),
    ('ios_mid_small_prompt.webp', None),
))
def test_replay_real_cycle_reward_grid(
    reward_reader: GamepadLostVoidBattleResult, name: str, expected: LostVoidCycleProgress | None,
) -> None:
    folder = Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-挑战结果'
    reward_reader.last_screenshot = cv2_utils.read_image(str(folder / name))
    assert reward_reader.last_screenshot is not None
    observation = reward_reader._read_cycle_rewards()
    assert (observation[1] if observation is not None else None) == expected


def test_complete_grid_without_weekly_icons_and_incomplete_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """两项都未掉落时才结束周期奖励目标，缺一格保持未知。"""
    op = GamepadLostVoidBattleResult(SimpleNamespace())
    image = np.zeros((348, 522, 3), dtype=np.uint8)
    words: dict[str, MatchResultList] = {}
    for index in range(8):
        matches = words.setdefault('20' if index < 3 else 'EMPTY', MatchResultList(only_best=False))
        matches.append(MatchResult(1, 60 + (index % 4) * 125, 147 + (index // 4) * 158, 24, 20))
    monkeypatch.setattr(op.navigation, '_read_area', lambda *_: (image, words))
    monkeypatch.setattr(op, '_cycle_reward_present', lambda *_: False)
    assert op._read_cycle_rewards()[1] == LostVoidCycleProgress(True, True)
    words['EMPTY'].arr.pop()
    assert op._read_cycle_rewards() is None


@pytest.mark.parametrize('known', [True, False])
def test_final_win_confirms_once_after_bounded_reward_reads(monkeypatch: pytest.MonkeyPatch, known: bool) -> None:
    """证据稳定才传周进度，未知也可关闭实际胜利结算回入口。"""
    op = GamepadLostVoidBattleResult(SimpleNamespace(controller=Mock()), read_cycle_rewards=True)
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.last_screenshot = image
    title = Mock(return_value=SimpleNamespace(is_success=True))
    monkeypatch.setattr(op, 'round_by_find_area', title)
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, '_has_result_action', lambda _, icon, _label: icon == 'B')
    numbers = MatchResultList()
    numbers.append(MatchResult(1, 0, 0, 30, 15))
    monkeypatch.setattr(op.navigation, '_read_area', lambda _, area: (
        image, {'+8000': numbers} if area == '手柄-最终结晶' else {},
    ))
    progress = LostVoidCycleProgress(True, False) if known else None
    sample = (('20', 'EMPTY'), progress) if known else None
    monkeypatch.setattr(op, '_read_cycle_rewards', lambda: sample)
    for _ in range(1 if known else 4):
        assert not op.confirm().is_success
        op.ctx.controller.btn_tap.assert_not_called()
    assert not op.confirm().is_success
    assert not op.confirm().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('east')
    title.return_value = SimpleNamespace(is_success=False)
    result = op.confirm()
    assert result.status == LostVoidRunLevel.STATUS_COMPLETE
    assert result.data == progress


@pytest.mark.parametrize('progress', [LostVoidCycleProgress(True, False), None])
def test_app_counts_after_entry_and_never_writes_unknown_flags(
    monkeypatch: pytest.MonkeyPatch, progress: LostVoidCycleProgress | None,
) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    app = object.__new__(LostVoidApp)
    app.ctx = SimpleNamespace()
    app.config = SimpleNamespace(extra_task='刷满业绩点', is_cycle_reward_mode=True)
    app.run_record = SimpleNamespace(
        add_complete_times=Mock(), eval_point_complete=False, period_reward_complete=True,
        is_finished_by_week=progress is not None,
    )
    app.use_priority_agent = False
    app._macos_cycle_progress = progress
    app._macos_cycle_unconfirmed = False
    app._macos_claim_error = None
    entry = Mock(return_value=SimpleNamespace(is_success=False))
    monkeypatch.setattr(app, '_wait_for_lost_void_entry', entry)
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    assert not app.after_complete().is_success
    app.run_record.add_complete_times.assert_not_called()
    entry.return_value = SimpleNamespace(is_success=True)
    result = app.after_complete()
    app.run_record.add_complete_times.assert_called_once()
    assert app.run_record.eval_point_complete is (progress is not None)
    assert app.run_record.period_reward_complete is (progress is None)
    assert result.status == (app.STATUS_MACOS_CYCLE_RETURN if progress is None else None)
    monkeypatch.setattr(lost_void, 'GamepadLostVoidBackToWorld', lambda _: SimpleNamespace(
        execute=lambda: OperationResult(True, '已返回游戏主界面'),
    ))
    final = app.back_at_last()
    assert final.is_success is (progress is not None)
    assert final.status == ('已刷满业绩点' if progress is not None else '实际通关已记录，周奖励进度未确认')
