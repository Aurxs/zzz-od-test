"""显式巡防等级保护与原调度入口的离线回归，不连接游戏。"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import cv2
import numpy as np
import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
)
from zzz_od.operation.gamepad import area_patrol, charge_plan, simulation_preset
from zzz_od.operation.gamepad.area_patrol import GamepadAreaPatrol
from zzz_od.operation.gamepad.charge_plan import (
    GamepadChargePlan,
    validate_macos_charge_plan,
)


@pytest.fixture
def plan() -> ChargePlanItem:
    return ChargePlanItem(category_name='区域巡防', mission_type_name='游侠与守卫',
                          level='等级Lv.60', predefined_team_idx=-1, plan_times=5)


@pytest.fixture
def op(plan: ChargePlanItem, monkeypatch: pytest.MonkeyPatch) -> GamepadAreaPatrol:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    result = GamepadAreaPatrol(ctx, plan, config=Mock())
    monkeypatch.setattr(result, '_after_round_wait', Mock())
    monkeypatch.setattr(result, '_deployment_visible', Mock(return_value=False))
    monkeypatch.setattr(result, '_found', Mock(return_value=True))
    monkeypatch.setattr(result, '_preset_selected', Mock(return_value=True))
    monkeypatch.setattr(result, '_charge', Mock(return_value=(180, 60)))
    monkeypatch.setattr(result, '_target_state', Mock(return_value='ok'))
    monkeypatch.setattr(result, '_charge_state', Mock(return_value=('ok', (180, 60))))
    monkeypatch.setattr(result, 'save_screenshot', Mock())
    result.last_screenshot = object()
    return result


def frame(op: GamepadAreaPatrol, age: float) -> None:
    number = getattr(op, "_test_frame_number", 0) + 1
    op._test_frame_number = number
    op.last_screenshot = np.full((2, 2, 3), number, dtype=np.uint8)
    op.last_screenshot_time = time.time() - age


def set_ocr(monkeypatch: pytest.MonkeyPatch, texts: list[str] | None) -> None:
    reader = Mock(return_value=None if texts is None else (object(), {t: [object()] for t in texts}))
    monkeypatch.setattr(area_patrol, 'read_preset_area', reader)


def ready(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['等级Lv.60'])
    frame(op, 4)
    assert op.prepare_cards().is_success
    frame(op, 3)
    assert not op.prepare_deployment().is_fail
    op._next_sent_at -= 5  # 模拟 Next 后实际采集的页面
    op._deployment_visible.return_value = True
    frame(op, 2)
    assert op.prepare_deployment().status == op.STATUS_DEPLOYMENT_READY


@pytest.mark.parametrize(('texts', 'expected'), [
    (['等级Lv.60'], True), (['Lv.60'], True), (['等级 Lv.60'], True),
    (None, False), ([], False), (['Lv.50'], False), (['Lv.60', 'Lv.50'], False),
    (['等级'], False), (['60'], False), (['180/60'], False), (['Lv.60?'], False), (['Lv.060'], False),
])
def test_exact_level(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch,
                     texts: list[str] | None, expected: bool) -> None:
    set_ocr(monkeypatch, texts)
    assert op._level_matches() is expected



@pytest.mark.parametrize('titles', [
    {'游侠与守卫': [object()], '其他': [object()]},
    {'游侠与守卫': [object(), object()]},
    {'其他': [object()]},
])
def test_ambiguous_target_rejected(plan: ChargePlanItem, monkeypatch: pytest.MonkeyPatch,
                                   titles: dict[str, list[object]]) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    op = GamepadAreaPatrol(ctx, plan, config=Mock())
    monkeypatch.setattr(area_patrol, 'read_preset_area', lambda *_args: (object(), titles))
    monkeypatch.setattr(area_patrol, 'read_focused_choice', lambda *_args, **_kw: ('游侠与守卫', set()))
    assert not op._preset_selected()
    ctx.controller.btn_tap.assert_not_called()


def test_patrol_split_label_is_reread_only_inside_a_unique_complete_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.zeros((200, 900, 3), dtype=np.uint8)
    cv2.rectangle(image, (12, 2), (392, 196), (255, 240, 0), 4)
    ctx = SimpleNamespace(ocr=Mock())
    ctx.ocr.run_ocr_single_line.return_value = '怪兽二重奏'
    split = {word: SimpleNamespace(max=None) for word in ('怪', '重奏')}
    monkeypatch.setattr(simulation_preset, 'read_preset_area', lambda *_: (image, split))
    assert simulation_preset.read_focused_choice(
        ctx, image, '手柄-副本列表', ('怪兽二重奏', '游侠与守卫'), reread_card_name=True,
    ) == ('怪兽二重奏', {'怪兽二重奏'})
    assert ctx.ocr.run_ocr_single_line.call_args.args[0].shape[0] == 52
    cv2.rectangle(image, (490, 2), (870, 196), (255, 240, 0), 4)
    ctx.ocr.run_ocr_single_line.reset_mock()
    focus, _ = simulation_preset.read_focused_choice(
        ctx, image, '手柄-副本列表', ('怪兽二重奏', '游侠与守卫'), reread_card_name=True,
    )
    assert focus is None
    ctx.ocr.run_ocr_single_line.assert_not_called()


@pytest.mark.parametrize(('texts', 'expected'), [
    ({'180/60': [object()]}, (180, 60)),
    ({'180/60': [object(), object()]}, None),
    ({'180/60': [object()], '180/40': [object()]}, None),
    ({'60': [object()]}, None),
    ({}, None),
])
def test_unambiguous_actual_charge(plan: ChargePlanItem, monkeypatch: pytest.MonkeyPatch,
                                   texts: dict[str, list[object]], expected: tuple[int, int] | None) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    op = GamepadAreaPatrol(ctx, plan, config=Mock())
    monkeypatch.setattr(area_patrol, 'read_preset_area', lambda *_args: (object(), texts))
    assert op._charge() == expected
    ctx.controller.btn_tap.assert_not_called()



@pytest.mark.parametrize(('x', 'expected'), [(118, (180, 60)), (30, None)])
def test_known_button_noise_requires_position(plan: ChargePlanItem, monkeypatch: pytest.MonkeyPatch,
                                              x: int, expected: tuple[int, int] | None) -> None:
    from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    op = GamepadAreaPatrol(ctx, plan, config=Mock())
    icon = MatchResultList(only_best=False)
    icon.append(MatchResult(1, x, 20, 20, 20))
    monkeypatch.setattr(area_patrol, 'read_preset_area',
                        lambda *_args: (object(), {'180/60': [object()], '三': icon}))
    assert op._charge() == expected

def test_sent_flag_cannot_bypass_missing_proof(op: GamepadAreaPatrol) -> None:
    op._deploy_sent = True
    op._deployment_visible.return_value = True
    frame(op, 1)
    assert not op.deploy().is_success
    op.ctx.controller.btn_tap.assert_not_called()

def test_fresh_verified_sequence_and_once(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    ready(op, monkeypatch)
    frame(op, 1)
    assert op.deploy().is_success
    assert op.deploy().is_success
    assert op.ctx.controller.btn_tap.call_args_list == [call('start'), call('start')]


@pytest.mark.parametrize('failure', ['stale', 'same_frame', 'expired', 'resume', 'plan_change', 'reinit', 'cost'])
def test_proof_cannot_be_reused(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch,
                                failure: str) -> None:
    ready(op, monkeypatch)
    if failure == 'stale':
        frame(op, 6)
    elif failure == 'same_frame':
        op.last_screenshot_time = op._ready_frame_time
    else:
        frame(op, 1)
    if failure == 'expired':
        op._proof_started -= 121
    elif failure == 'resume':
        op.handle_resume()
    elif failure == 'plan_change':
        op.plan.run_times += 1
    elif failure == 'reinit':
        op.handle_init()
    elif failure == 'cost':
        op._charge_state.return_value = ('ok', (180, 40))
    assert not op.deploy().is_success
    assert op.ctx.controller.btn_tap.call_args_list == [call('start')]


def test_detail_level_changed_between_nodes_stops(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['Lv.60'])
    frame(op, 3)
    assert op.prepare_cards().is_success
    set_ocr(monkeypatch, ['Lv.50'])
    frame(op, 2)
    assert op.prepare_deployment().is_fail
    op.ctx.controller.btn_tap.assert_not_called()




def test_unsupported_explicit_level_cannot_skip_plan_check(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    op.plan.level = '等级Lv.50'
    op.handle_init()
    set_ocr(monkeypatch, ['Lv.60'])
    frame(op, 1)
    assert op.prepare_cards().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_duplicate_level_boxes_are_ambiguous(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(area_patrol, 'read_preset_area',
                        lambda *_args: (object(), {'Lv.60': [object(), object()]}))
    frame(op, 1)
    assert op.prepare_cards().status_display == '重试'
    assert not op._level_confirmed
    op.ctx.controller.btn_tap.assert_not_called()


def test_frame_expires_during_cost_read(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['Lv.60'])
    frame(op, 3)
    assert op.prepare_cards().is_success
    frame(op, 2)
    def slow_read() -> tuple[int, int]:
        op.last_screenshot_time -= 6
        return (180, 60)
    op._charge_state.side_effect = lambda: ('ok', slow_read())
    assert not op.prepare_deployment().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_same_pixels_with_new_capture_time_are_accepted(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['Lv.60'])
    frame(op, 3)
    assert op.prepare_cards().is_success
    op.last_screenshot_time = time.time() - 1
    assert not op.prepare_deployment().is_fail
    op.ctx.controller.btn_tap.assert_called_once_with('start')


def test_cached_frame_is_waited_without_input(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['Lv.60'])
    frame(op, 3)
    assert op.prepare_cards().is_success
    assert not op.prepare_deployment().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_old_deployment_frame_is_waited(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    ready(op, monkeypatch)
    assert not op.deploy().is_success
    assert op.ctx.controller.btn_tap.call_args_list == [call('start')]


def test_no_direct_deployment_or_old_frame(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    set_ocr(monkeypatch, ['Lv.60'])
    op._deployment_visible.return_value = True
    frame(op, 1)
    assert not op.prepare_deployment().is_success
    assert not op.deploy().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_default_level_keeps_original_behavior(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    op.plan.level = '默认等级'
    op.handle_init()
    set_ocr(monkeypatch, None)
    op.last_screenshot_time = 0
    assert op.prepare_cards().is_success
    assert not op.prepare_deployment().is_fail
    op.ctx.controller.btn_tap.assert_called_once_with('start')


def test_only_patrol_accepts_explicit_level(plan: ChargePlanItem) -> None:
    config = SimpleNamespace(loop=False, double_reward=False, restore_charge='不使用', plan_list=[plan])
    assert validate_macos_charge_plan(config) is None
    plan.level = '等级Lv.50'
    assert validate_macos_charge_plan(config) is not None
    plan.category_name, plan.level = '专业挑战室', '等级Lv.60'
    assert validate_macos_charge_plan(config) is not None



def test_five_saved_runs_stop_at_plan_limit(plan: ChargePlanItem, monkeypatch: pytest.MonkeyPatch) -> None:
    """原计划每场重建操作，仅真实成功后计数，五场后不再创建第六场。"""
    config = ChargePlanConfig.__new__(ChargePlanConfig)
    YamlOperator.__init__(config)
    config.data.update(loop=False, restore_charge='不使用', double_reward=False)
    config.plan_list = [plan]
    config.save = Mock()
    context = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    runner = GamepadChargePlan(context, config, Mock())
    monkeypatch.setattr(runner, '_after_round_wait', Mock())
    instances = []
    def make(_ctx: object, passed_plan: ChargePlanItem, config: object) -> Mock:
        sim = Mock()
        sim.execute.side_effect = lambda: (setattr(passed_plan, 'run_times', passed_plan.run_times + 1)
                                            or OperationResult(True))
        instances.append(sim)
        return sim
    monkeypatch.setattr(charge_plan, 'GamepadAreaPatrol', make)
    for count in range(1, 6):
        assert runner.select_plan().is_success
        assert runner.run_battle().is_success
        assert plan.run_times == count and runner.completed_battles == count
    assert runner.select_plan().status == runner.STATUS_FINISHED
    assert len(instances) == 5
    assert runner.finish().data['completed_battles'] == 5


def test_archived_level_frame_uses_real_ocr(op: GamepadAreaPatrol, monkeypatch: pytest.MonkeyPatch) -> None:
    """只回放测试仓已跟踪的历史图和已安装模型。"""
    from one_dragon.base.matcher.ocr.onnx_ocr_matcher import (
        OnnxOcrMatcher,
        OnnxOcrParam,
    )
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.utils import cv2_utils
    param = OnnxOcrParam(use_gpu=False, det_limit_side_len=1920)
    if not Path(param.det_model_dir).exists() or not Path(param.rec_model_dir).exists():
        pytest.skip('缺少已安装 OCR 模型')
    matcher = OnnxOcrMatcher(param)
    monkeypatch.setattr(matcher, 'download', Mock(return_value=True))
    assert matcher.init_model()
    loader = ProfileScreenContext()
    loader.reload()
    op.ctx.screen_loader, op.ctx.ocr = loader, matcher
    path = Path(__file__).resolve().parents[3] / 'screens/区域巡防/ios_patrol_detail.webp'
    op.last_screenshot = cv2_utils.read_image(str(path))
    try:
        assert op.last_screenshot is not None and op._level_matches()
    finally:
        matcher.cleanup()
