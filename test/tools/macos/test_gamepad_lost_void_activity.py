"""用实拍活性画面回放调整边界，不连接游戏或消耗周常机会。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.lost_void.lost_void_config import LostVoidConfig
from zzz_od.operation.gamepad.lost_void_activity import GamepadLostVoidSetActivity

SCREENS = Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-战线肃清'


class FrameOcr:
    """按实际框回放局部 OCR，图像高亮与模板仍使用真实像素。"""

    def __init__(self, state: str) -> None:
        self.words = json.loads((SCREENS / 'ios_activity_ocr.json').read_text())[state]

    def crop_and_run_ocr(self, image: object, rect: Rect) -> dict[str, MatchResultList]:
        results = {}
        for word in self.words:
            x, y, w, h = (int(word[k]) for k in ('x', 'y', 'width', 'height'))
            if rect.x1 <= x < x + w <= rect.x2 and rect.y1 <= y < y + h <= rect.y2:
                result = MatchResultList()
                result.append(MatchResult(1, x - rect.x1, y - rect.y1, w, h))
                results[word['text']] = result
        return results


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadLostVoidSetActivity:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap']), screen_loader=loader,
        ocr=FrameOcr('ios_activity_4'), tm=TemplateMatcher(TemplateLoader()),
        run_context=Mock(), current_instance_idx=2,
    )
    op = GamepadLostVoidSetActivity(ctx, target=4)
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'round_by_find_area', Mock(return_value=op.round_success()))
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_activity_4.webp'))
    return op


@pytest.mark.parametrize('target', [-1, 4])
def test_keep_default_or_matching_activity_sends_no_input(operation: GamepadLostVoidSetActivity, target: int) -> None:
    """默认保持与已达到目标均须读真实4/12，但不改变勾选。"""
    operation.target = target
    result = operation.set_activity()
    assert result.is_success and result.data == {'activity': 4, 'maximum': 12}
    operation.ctx.controller.btn_tap.assert_not_called()


def test_increase_requires_unchecked_and_observed_count_change(operation: GamepadLostVoidSetActivity) -> None:
    """4→5只操作一次，没读到5/12不能成功或再次切换。"""
    operation.target = 5
    assert not operation.set_activity().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    assert not operation.set_activity().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    for item in operation.ctx.ocr.words:
        if '4/12' in item['text'].replace(' ', ''):
            item['text'] = '5/12'
    assert operation.set_activity().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


def test_decrease_requires_checked_and_observed_count_change(operation: GamepadLostVoidSetActivity) -> None:
    """真实12活性首行已勾选；等待11的证据期间不得连按。"""
    operation.ctx.ocr = FrameOcr('ios_activity_12')
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_activity_12.webp'))
    assert not operation.set_activity().is_success
    assert operation._pending == 11
    assert not operation.set_activity().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


def test_ambiguous_selection_and_invalid_values_send_no_input(operation: GamepadLostVoidSetActivity) -> None:
    """冲突模板或超出当帧上限时停止，不猜测勾选。"""
    operation.target = 13
    assert operation.set_activity().is_fail
    operation.target = 5
    operation.ctx.tm = Mock()
    operation.ctx.tm.match_template.return_value.max = object()
    assert operation.set_activity().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()


def test_activity_config_keeps_legacy_default_and_validates_range() -> None:
    """旧配置默认不改游戏；合法值存原实例配置，非法值不写入。"""
    config = object.__new__(LostVoidConfig)
    config.data = {}
    config.save = Mock()
    assert config.ether_activity == -1
    config.ether_activity = 4
    assert config.ether_activity == 4
    for value in (-2, 13, True, '4'):
        with pytest.raises(ValueError):
            config.ether_activity = value
    assert config.ether_activity == 4


def test_buff_radio_cannot_be_used_as_activity_toggle(operation: GamepadLostVoidSetActivity) -> None:
    """周期增益与活性复用相似圆标；必须先依据面板标题退出增益焦点。"""
    operation.target = 7
    operation.ctx.ocr = FrameOcr('ios_buff_focus')
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_buff_focus.webp'))
    assert not operation.set_activity().is_success
    assert operation._pending is None
    operation.ctx.controller.btn_tap.assert_called_once_with('east')
