"""专业挑战室详情和两层返回的真实截图回放。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.area_patrol import GamepadChargeBackToWorld
from zzz_od.operation.gamepad.expert_challenge import GamepadExpertChallenge

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '专业挑战室'


@pytest.fixture(scope='module')
def ctx() -> SimpleNamespace:
    """真实识别和内存控制器。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少OCR模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    return SimpleNamespace(ocr=ocr, screen_loader=loader, controller=Mock(spec=['btn_tap']), run_context=Mock())


def test_expert_exact_target_and_cost(ctx: SimpleNamespace) -> None:
    """单目标详情必须精确匹配，实际27/40不能当成巡防60或可出战。"""
    plan = ChargePlanItem(category_name='专业挑战室', mission_type_name='恶名·杜拉罕')
    op = GamepadExpertChallenge(ctx, plan, config=Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_expert_detail.webp'))
    assert op._preset_selected()
    assert op.read_charge() == (27, 40)
    assert op.expected_charge == 40
    plan.mission_type_name = '恶名·装甲哈提'
    assert not op._preset_selected()


def test_expert_list_return_once(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """识别第二层Boss列表后仅按一次返回，不等待不存在的下一步。"""
    op = GamepadChargeBackToWorld(ctx, '专业挑战室')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'round_by_find_area', Mock(return_value=SimpleNamespace(is_success=False)))
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_expert_list.webp'))
    ctx.controller.reset_mock()
    op.back()
    op.back()
    ctx.controller.btn_tap.assert_called_once_with('east')


@pytest.mark.parametrize(('words', 'status', 'key'), [
    ({'燃竭模式': [], 'OFF': []}, 'success', None),
    ({'燃竭模式': [], 'ON': [], 'RS': []}, 'retry', 'right_stick_click'),
    ({'燃竭模式': [], 'ON': []}, 'fail', None),
    ({'燃竭模式': [], 'ON': [], 'OFF': [], 'RS': []}, 'retry', None),
])
def test_burnout_requires_explicit_state_and_key(monkeypatch: pytest.MonkeyPatch, words: dict, status: str, key: str | None) -> None:
    """未知开关或没有对应RS提示不操作，OFF状态不反向开启。"""
    from zzz_od.operation.gamepad import expert_challenge as module

    ctx = SimpleNamespace(controller=Mock(spec=['btn_tap']), run_context=Mock(), ocr=SimpleNamespace(run_ocr=lambda image: {}))
    op = module.GamepadDisableBurnout(ctx, '恶名·杜拉罕')
    op.last_screenshot = object()
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(module, 'read_preset_area', lambda ctx, screen, area, group: (None, {'恶名·杜拉罕': []} if area == '手柄-副本标题' else words))
    result = op.disable()
    assert result.is_success == (status == 'success')
    assert result.is_fail == (status == 'fail')
    if key is None:
        ctx.controller.btn_tap.assert_not_called()
    else:
        ctx.controller.btn_tap.assert_called_once_with(key)
        words.clear()
        words.update({'燃竭模式': [], 'OFF': []})
        assert op.disable().is_success
        ctx.controller.btn_tap.assert_called_once_with(key)


def test_burnout_confirmation_requires_followup_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """确认关闭弹窗不等于成功，随后必须明确读到OFF。"""
    from zzz_od.operation.gamepad import expert_challenge as module

    words = {'是否退出燃竭模式，恢复电量消耗和奖励产出至正常水平？': [], '确认': [SimpleNamespace(rect=object())]}
    mode = {'燃竭模式': [], 'ON': [], 'RS': []}
    ctx = SimpleNamespace(controller=Mock(spec=['btn_tap']), run_context=Mock(), ocr=SimpleNamespace(run_ocr=lambda image: words))
    op = module.GamepadDisableBurnout(ctx, '恶名·杜拉罕')
    op.last_screenshot = object()
    op._sent = True
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(module, 'has_filled_highlight', lambda *args: True)
    monkeypatch.setattr(module, 'read_preset_area', lambda ctx, screen, area, group: (None, {'恶名·杜拉罕': []} if area == '手柄-副本标题' else mode))
    assert not op.disable().is_success
    ctx.controller.btn_tap.assert_called_once_with('south')
    words.clear()
    assert not op.disable().is_success
    mode.clear()
    mode.update({'燃竭模式': [], 'OFF': []})
    assert op.disable().is_success
    ctx.controller.btn_tap.assert_called_once_with('south')


def test_real_burnout_states_and_recovery(ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """实际ON、退出确认和OFF：恢复确认后必须核对目标与40消耗。"""
    from zzz_od.operation.gamepad.expert_challenge import GamepadDisableBurnout
    from zzz_od.operation.gamepad.simulation_preset import read_preset_charge

    op = GamepadDisableBurnout(ctx, '空域戒戍者')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    ctx.controller.reset_mock()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_expert_burnout_on.webp'))
    assert not op.disable().is_success
    ctx.controller.btn_tap.assert_called_once_with('right_stick_click')
    op.handle_init()
    ctx.controller.reset_mock()
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_expert_burnout_confirm.webp'))
    assert not op.disable().is_success
    ctx.controller.btn_tap.assert_called_once_with('south')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_expert_burnout_off.webp'))
    assert op.disable().is_success
    assert read_preset_charge(ctx, op.last_screenshot)[1] == 40
    ctx.controller.btn_tap.assert_called_once_with('south')
