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


def test_empty_charge_preset_keeps_stable_next_label(
    op: GamepadConfigureCards, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """电量耗尽后的完整按钮裁图仍识别下一步，不把预设当未知编辑页。"""
    from one_dragon.utils import str_utils

    op.last_screenshot = cv2_utils.read_image(str(
        SCREENS / 'macos_cards_unknown_editor_1792978621510.webp'
    ))

    def found(name: str) -> bool:
        """用平台区域做真实局部 OCR，隔离框架服务初始化。"""
        area = op.ctx.screen_loader.get_area('实战模拟室', name)
        words = op.ctx.ocr.crop_and_run_ocr(op.last_screenshot, area.rect)
        return any(str_utils.find_by_lcs(area.text, text, area.lcs_percent) for text in words)

    monkeypatch.setattr(op, '_found', found)
    assert op._preset_visible()
    result = op.configure()
    assert result.is_success and result.data['current_charge'] == 0
    assert result.data['required_charge'] == 20
    op.ctx.controller.btn_tap.assert_not_called()


def test_other_material_menu_and_saved_target(op: GamepadConfigureCards) -> None:
    """音擎专项菜单位于不同横向位置，单卡保存仍确认目标和消耗。"""
    from zzz_od.operation.gamepad.simulation_preset import (
        preset_focused,
        read_preset_charge,
    )
    op.mission_name = '音擎专项'
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_engine_menu.webp'))
    assert op._preset_menu() == (True, '开始战斗')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_engine_single.webp'))
    assert preset_focused(op.ctx, op.last_screenshot, '音擎专项')
    assert not preset_focused(op.ctx, op.last_screenshot, '调查专项')
    assert read_preset_charge(op.ctx, op.last_screenshot) == (33, 20)


def test_editor_transition_does_not_mistake_old_preset_for_wrong_material(op: GamepadConfigureCards, monkeypatch: pytest.MonkeyPatch) -> None:
    """确认编辑后的过渡帧只等待，不把未稳定的外层文字当作错误材料。"""
    from zzz_od.operation.gamepad import configure_cards
    op._menu_confirm_sent = True
    monkeypatch.setattr(op, '_editor_charge', lambda: None)
    monkeypatch.setattr(op, '_preset_menu', lambda: (False, None))
    monkeypatch.setattr(op, '_preset_visible', lambda: True)
    monkeypatch.setattr(configure_cards, 'preset_focused', lambda *args: False)
    result = op.configure()
    assert not result.is_fail and '切换动画' in result.status
    op.ctx.controller.btn_tap.assert_not_called()


def test_material_category_focus_uses_complete_card(op: GamepadConfigureCards) -> None:
    """分类页按完整黄框确认基础材料，不把其他卡片的 NEW 当焦点。"""
    from zzz_od.operation.gamepad.simulation_preset import (
        SIMULATION_TYPES,
        read_focused_choice,
    )
    screen = cv2_utils.read_image(str(SCREENS / 'ios_material_category.webp'))
    selected, visible = read_focused_choice(op.ctx, screen, '手柄-材料分类列表', (*SIMULATION_TYPES, '自定义模板'))
    assert selected == '基础材料'
    assert set(SIMULATION_TYPES) <= visible


@pytest.mark.parametrize(('state', 'mission', 'cost'), [('ios_promotion_single', '强攻演练', 20), ('ios_wengine_last_three', '防护音圈试验', 60)])
def test_material_preset_after_category_or_page_change(op: GamepadConfigureCards, state: str, mission: str, cost: int) -> None:
    """不同分类和后页焦点使用原专项名，实读单卡和三卡消耗。"""
    from zzz_od.operation.gamepad.simulation_preset import (
        preset_focused,
        read_preset_charge,
    )
    screen = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    assert preset_focused(op.ctx, screen, mission)
    assert not preset_focused(op.ctx, screen, '调查专项')
    assert read_preset_charge(op.ctx, screen)[1] == cost
