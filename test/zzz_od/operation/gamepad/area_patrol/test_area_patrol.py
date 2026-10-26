"""真实区域巡防截图验证目标和倒序手册导航，不连接设备。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.area_patrol import GamepadAreaPatrol
from zzz_od.operation.gamepad.charge_transport import GamepadChargeTransport

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '区域巡防'


@pytest.fixture(scope='module')
def ctx() -> SimpleNamespace:
    """使用实际平台区域和 OCR，输入严格替换。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少 OCR 模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    return SimpleNamespace(ocr=ocr, screen_loader=loader, controller=Mock(spec=['btn_tap']), run_context=Mock())


@pytest.mark.parametrize('filename', ['ios_patrol_detail.webp', 'ios_patrol_arrow.webp'])
def test_patrol_target_and_actual_cost(ctx: SimpleNamespace, filename: str) -> None:
    """翻页箭头覆盖边框时仍核对标题和唯一焦点，错目标不能放行。"""
    plan = ChargePlanItem(category_name='区域巡防', mission_type_name='怪兽二重奏')
    op = GamepadAreaPatrol(ctx, plan, config=Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / filename))
    assert op._preset_selected()
    assert op.read_charge()[1] == op.expected_charge == 60
    plan.mission_type_name = '游侠与守卫'
    assert not op._preset_selected()


def test_handbook_uses_visible_order(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """实际列表与原数据相反，未显示目标应向上查找而非来回振荡。"""
    op = GamepadChargeTransport(ctx, '区域巡防', '怪兽二重奏')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    op.check_target()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_handbook_descending.webp'))
    monkeypatch.setattr(op.navigation, '_teleport_dialog', Mock(return_value=False))
    ctx.controller.reset_mock()
    assert not op.choose_target().is_success
    ctx.controller.btn_tap.assert_called_once_with('dpad_up')
    assert not op.choose_target().is_success
    ctx.controller.btn_tap.assert_called_once_with('dpad_up')


def test_recommended_entries_scan_with_one_boundary_reverse(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """置顶推荐打乱顺序时向下遍历，边界连续不动仅允许反向一次。"""
    op = GamepadChargeTransport(ctx, '区域巡防', '怪兽二重奏')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    monkeypatch.setattr(op.navigation, '_teleport_dialog', Mock(return_value=False))
    op.check_target()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_handbook_recommended.webp'))
    ctx.controller.reset_mock()
    op.choose_target()
    ctx.controller.btn_tap.assert_called_once_with('dpad_down')
    for _ in range(3):
        op.choose_target()
    assert ctx.controller.btn_tap.call_args.args == ('dpad_up',)
    for _ in range(3):
        result = op.choose_target()
    assert result.is_fail
    assert ctx.controller.btn_tap.call_count == 2


@pytest.mark.parametrize('filename', ['ios_patrol_detail.webp', 'ios_patrol_next_split.webp'])
def test_next_anchor_avoids_button_background(ctx: SimpleNamespace, filename: str) -> None:
    """不同像素密度的按钮背景不能把下一步文字拆成两个识别结果。"""
    from one_dragon.base.matcher.ocr.ocr_service import OcrService
    from one_dragon.base.screen.screen_utils import FindAreaResultEnum, find_area

    ctx.ocr_service = OcrService(ctx.ocr)
    screen = cv2_utils.read_image(str(SCREENS / filename))
    assert find_area(ctx, screen, '区域巡防', '手柄-下一步') == FindAreaResultEnum.TRUE
    assert find_area(ctx, screen, '区域巡防', '手柄-挑战等级') == FindAreaResultEnum.TRUE


def test_training_avatar_can_cover_focus_corner(ctx: SimpleNamespace) -> None:
    """培养头像遮角时仍须四边覆盖、标题及目标同时吻合。"""
    plan = ChargePlanItem(category_name='区域巡防', mission_type_name='机师与叛甲')
    op = GamepadAreaPatrol(ctx, plan, config=Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_patrol_training_avatar.webp'))
    assert op._preset_selected()
    assert op.read_charge()[1] == 60
    plan.mission_type_name = '怪兽与怪客'
    assert not op._preset_selected()
