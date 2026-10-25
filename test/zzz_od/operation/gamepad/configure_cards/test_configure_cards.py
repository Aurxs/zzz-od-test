"""回放实际编辑页，验证不误入战斗及数量变化检查。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.configure_cards import GamepadConfigureCards

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '实战模拟室'


@pytest.fixture
def op(monkeypatch: pytest.MonkeyPatch) -> GamepadConfigureCards:
    """真实区域 OCR 与假控制器，不能扣除游戏电量。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少 OCR 模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    ctx = SimpleNamespace(ocr=ocr, screen_loader=loader, controller=Mock(spec=['btn_tap']), run_context=Mock())
    result = GamepadConfigureCards(ctx, 1)
    monkeypatch.setattr(result, '_after_round_wait', Mock())
    monkeypatch.setattr(result, '_save', Mock())
    return result


def test_preset_menu_never_confirms_default_battle(op: GamepadConfigureCards) -> None:
    """默认开始战斗只下移，编辑高亮才 A。"""
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_menu_battle.webp'))
    assert op._preset_menu() == (True, '开始战斗')
    assert not op.configure().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('dpad_down')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_menu_edit.webp'))
    assert op._preset_menu() == (True, '编辑')
    assert not op.configure().is_success
    assert op.ctx.controller.btn_tap.call_args.args == ('south',)


def test_editor_checks_actual_cost_before_next_change(op: GamepadConfigureCards) -> None:
    """五卡 Y 减一；未变化不连发，四卡目标五卡时 A 加一。"""
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_editor_five.webp'))
    assert op._editor_charge()[1] == 100
    assert not op.configure().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('north')
    assert not op.configure().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('north')
    op.num_cards = 5
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_editor_four.webp'))
    assert op._editor_charge()[1] == 80
    assert not op.configure().is_success
    assert op.ctx.controller.btn_tap.call_args.args == ('south',)
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_editor_five.webp'))
    assert not op.configure().is_success
    assert op.ctx.controller.btn_tap.call_args.args == ('west',)
