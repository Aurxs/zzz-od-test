"""深度追猎真实模式页面和体力计数检查，不连接游戏。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad import deep_hunt
from zzz_od.operation.gamepad.deep_hunt import GamepadDeepHunt, GamepadEnableDeepHunt, deep_target_selected

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '恶名狩猎'


@pytest.fixture(scope='module')
def ctx() -> SimpleNamespace:
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少OCR模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    return SimpleNamespace(ocr=ocr, screen_loader=loader, controller=Mock(spec=['btn_tap']), run_context=Mock())


def test_mode_switch_confirm_and_actual_on(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """OFF只切一次，专用确认弹窗才按A，ON与目标同时匹配。"""
    op = GamepadEnableDeepHunt(ctx, '库萨里库')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    ctx.controller.reset_mock()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_deep_off.webp'))
    assert not deep_target_selected(ctx, op.last_screenshot, '库萨里库')
    op.enable()
    op.enable()
    ctx.controller.btn_tap.assert_called_once_with('right_stick_click')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_deep_dialog.webp'))
    op.enable()
    assert ctx.controller.btn_tap.call_args.args == ('south',)
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_deep_on.webp'))
    assert op.enable().is_success
    assert deep_target_selected(ctx, op.last_screenshot, '库萨里库')
    assert not deep_target_selected(ctx, op.last_screenshot, '基塔布鲁')
    assert ctx.controller.btn_tap.call_count == 2


@pytest.mark.parametrize(('won', 'remaining', 'counted'), [(True, 140, True), (False, 140, False), (True, 200, False)])
def test_count_only_victory_with_charge_change(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, won: bool, remaining: int, counted: bool) -> None:
    """免费次数不参与体力计数，失败或未扣电结果不能计为完成。"""
    config = Mock()
    op = GamepadDeepHunt(ctx, ChargePlanItem(category_name='恶名狩猎', mission_type_name='库萨里库'), config=config)
    op._won = won
    op._charge_before = 200
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    result = Mock()
    result.return_value.execute.return_value = OperationResult(True, data={'won': won, 'charge': remaining})
    monkeypatch.setattr(deep_hunt, 'GamepadDeepHuntResultExit', result)
    back = Mock()
    back.return_value.execute.return_value = OperationResult(True)
    monkeypatch.setattr(deep_hunt, 'GamepadHuntBackToWorld', back)
    assert op.finish().is_success == counted
    assert config.add_plan_run_times.call_count == int(counted)


def test_free_opportunities_prevent_charge_mode(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """免费次数未用完时不切模式，不将周常挑战计入体力计划。"""
    op = GamepadEnableDeepHunt(ctx, '库萨里库')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(deep_hunt, 'read_preset_area', Mock(return_value=(None, {'库萨里库': [], '挑战等级': [], '剩余奖励次数2/3': []})))
    ctx.controller.reset_mock()
    result = op.enable()
    assert result.is_fail and result.status == '周期挑战有剩余次数，本次跳过深度追猎'
    ctx.controller.btn_tap.assert_not_called()


def test_story_alias_and_ocr_keep_same_target(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """原数据两个名字均保留，剧情隐藏名及一字OCR误差不阻断跨页。"""
    from zzz_od.operation.gamepad.charge_transport import GamepadChargeTransport, charge_mission_aliases, match_charge_mission

    names = charge_mission_aliases('恶名狩猎')['魇缚者·叶释渊']
    assert names == ('魇缚者·叶释渊', '魇缚者·???')
    for name in (*names, '魔缚者・???'):
        assert match_charge_mission(name, '恶名狩猎') == '魇缚者·叶释渊'
    assert match_charge_mission('未知Boss·???', '恶名狩猎') is None
    op = GamepadChargeTransport(ctx, '恶名狩猎', '初生死路屠夫')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op.navigation, '_teleport_dialog', Mock(return_value=False))
    op.check_target()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_hidden_boss_alias.webp'))
    ctx.controller.reset_mock()
    op.choose_target()
    ctx.controller.btn_tap.assert_called_once_with('dpad_down')
