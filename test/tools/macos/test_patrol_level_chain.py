"""原体力计划及单场节点链的无设备回放。"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
)
from zzz_od.operation.gamepad import area_patrol, charge_plan
from zzz_od.operation.gamepad.area_patrol import GamepadAreaPatrol
from zzz_od.operation.gamepad.charge_plan import (
    GamepadChargePlan,
    validate_macos_charge_plan,
)
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation


class Replay:
    """输入仅改变内存页面；截图时间模拟采集而非调用自动刷新缓存。"""
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.stage = 'detail'
        self.starts = 0
        self.level_reads = 0
        self.cached = time.time()
        self.transition_seen = 0
        self.settlement_confirmed = False
        self.events: list[str] = []

    def screenshot(self) -> tuple[float, np.ndarray]:
        if self.stage == 'transition':
            self.transition_seen += 1
            image = np.full((2, 2, 3), 2, dtype=np.uint8)
            self.stage = 'deployment'
            return time.time(), image
        code = {'detail': 1, 'deployment': 3, 'battle': 4, 'result': 5, 'return': 6}[self.stage]
        stamp = time.time()
        if self.mode == 'cache' and self.stage == 'detail':
            stamp = self.cached
        if self.mode == 'old_deployment' and self.stage == 'deployment':
            stamp = self.cached
        return stamp, np.full((2, 2, 3), code, dtype=np.uint8)

    def tap(self, key: str) -> None:
        self.events.append(f'{self.stage}:{key}')
        if key == 'start':
            self.starts += 1
            if self.stage == 'detail':
                self.stage = 'transition'
            elif self.stage == 'deployment':
                self.stage = 'battle'
            else:
                raise AssertionError('unexpected start')
        elif key == 'east' and self.stage == 'result':
            self.stage = 'return'


def make_chain(monkeypatch: pytest.MonkeyPatch, mode: str) -> tuple[GamepadChargePlan, Replay, ChargePlanItem, Mock]:
    replay = Replay(mode)
    controller = Mock()
    controller.screenshot.side_effect = replay.screenshot
    controller.btn_tap.side_effect = replay.tap
    controller.battle_input_blocked = False
    battle = Mock()
    battle.normal_attack_template_variants = ()
    battle.is_normal_attack_btn_available.return_value = True
    battle.last_check_end_result = '普通战斗-完成'
    battle.check_battle_state.side_effect = lambda *_a, **_kw: setattr(replay, 'stage', 'result')
    ctx = SimpleNamespace(controller=controller, auto_battle_context=battle, run_context=Mock(),
                          current_instance_idx=2, is_game_window_ready=True, unlisten_all_event=Mock(),
                          notify_config=SimpleNamespace(enable_notify=False),
                          battle_assistant_config=SimpleNamespace(screenshot_interval=0))
    ctx.run_context.is_context_stop = False
    ctx.run_context.is_context_pause = False
    plan = ChargePlanItem(category_name='区域巡防', mission_type_name='游侠与守卫',
                          level='等级Lv.60', predefined_team_idx=-1, plan_times=1)
    config = ChargePlanConfig.__new__(ChargePlanConfig)
    YamlOperator.__init__(config)
    config.data.update(loop=False, restore_charge='不使用', double_reward=False)
    config.plan_list = [plan]
    config.save = Mock()
    record = Mock()
    monkeypatch.setattr(GamepadChargePlan, '_after_round_wait', Mock())
    monkeypatch.setattr(GamepadAreaPatrol, '_after_round_wait', Mock())
    monkeypatch.setattr(GamepadChargePlan, '_found', lambda _self, _name: True)
    monkeypatch.setattr(GamepadAreaPatrol, '_found',
                        lambda self, _name: self.last_screenshot is not None and int(self.last_screenshot[0, 0, 0]) in (1, 6))
    monkeypatch.setattr(GamepadAreaPatrol, '_deployment_visible',
                        lambda self: self.last_screenshot is not None and int(self.last_screenshot[0, 0, 0]) == 3)
    monkeypatch.setattr(GamepadAreaPatrol, '_result_visible',
                        lambda self: mode != 'no_settlement' and replay.stage == 'result')
    def outer_charge(_self: GamepadAreaPatrol) -> tuple[int, int]:
        if mode == 'shortage':
            config.data['restore_charge'] = '使用储蓄电量'  # 模拟预检后配置发生变化
            return (30, 60)
        return (180, 60)
    monkeypatch.setattr(GamepadAreaPatrol, 'read_charge', outer_charge)
    monkeypatch.setattr(area_patrol, 'read_focused_choice', lambda *_a, **_kw: ('游侠与守卫', {'游侠与守卫'}))
    def ocr(_ctx: object, image: np.ndarray, area: str, *_args: object) -> tuple[object, dict]:
        if area == '手柄-副本标题':
            return object(), {'游侠与守卫': [object()]}
        if area == '手柄-挑战等级数值':
            replay.level_reads += 1
            if mode == 'no_level':
                return object(), {}
            value = 'Lv.50' if mode == 'changed_level' and replay.level_reads > 1 else 'Lv.60'
            return object(), {value: [object()]}
        if area == '手柄-电量':
            return object(), {'180/60': [object()]}
        raise AssertionError(area)
    monkeypatch.setattr(area_patrol, 'read_preset_area', ocr)
    transport = Mock()
    transport.return_value.execute.return_value = OperationResult(True)
    monkeypatch.setattr(charge_plan, 'GamepadChargeTransport', transport)
    back = Mock()
    back.return_value.execute.return_value = OperationResult(True, '已返回大世界')
    monkeypatch.setattr(area_patrol, 'GamepadChargeBackToWorld', back)
    original_add = config.add_plan_run_times
    def count_after_settlement(item: ChargePlanItem) -> None:
        assert replay.stage == 'result' and mode != 'no_settlement'
        replay.settlement_confirmed = True
        original_add(item)
    config.add_plan_run_times = count_after_settlement
    runner = GamepadChargePlan(ctx, config, record)
    if mode == 'shortage':
        config.data['skip_plan'] = True
        config.plan_list.append(ChargePlanItem(card_num='1'))
        monkeypatch.setattr(runner, 'round_by_find_area', lambda *_a, **_kw: runner.round_success())
    return runner, replay, plan, controller


def test_real_chain_same_pixels_transition_and_settlement(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, replay, plan, controller = make_chain(monkeypatch, 'ok')
    result = runner.execute()
    assert result.success and result.data['completed_battles'] == 1
    assert replay.transition_seen == 1 and replay.starts == 2  # Next 一次、出战一次
    assert replay.events.count('detail:start') == 1 and replay.events.count('deployment:start') == 1
    assert replay.settlement_confirmed and plan.run_times == 1
    assert controller.btn_tap.call_count == 3  # 另一次仅为结算返回


@pytest.mark.parametrize('mode', ['cache', 'no_level', 'changed_level', 'old_deployment', 'no_settlement'])
def test_real_chain_stops_without_unconfirmed_count(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    runner, replay, plan, _controller = make_chain(monkeypatch, mode)
    result = runner.execute()
    assert not result.success
    assert plan.run_times == 0 and runner.completed_battles == 0 and not replay.settlement_confirmed
    assert replay.starts == (2 if mode == 'no_settlement' else 1 if mode == 'old_deployment' else 0)


def test_explicit_level_forbids_backup_preflight_and_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, replay, plan, controller = make_chain(monkeypatch, 'ok')
    runner.config.data['restore_charge'] = '使用储蓄电量'
    assert '不允许自动恢复' in validate_macos_charge_plan(runner.config)
    runner.current_plan = plan
    runner._create_simulation(plan)
    runner._simulation.read_charge = Mock(return_value=(30, 60))
    runner.last_screenshot = np.zeros((2, 2, 3), dtype=np.uint8)
    assert runner.check_charge().status == runner.STATUS_CHARGE_NOT_ENOUGH
    assert runner.restore_minimum_reserve().is_fail
    assert plan.run_times == 0 and runner.completed_battles == 0 and replay.starts == 0
    controller.btn_tap.assert_not_called()
    plan.level = '默认等级'
    monkeypatch.setattr('zzz_od.operation.gamepad.restore_reserve_charge.reserve_budget', lambda _cfg: None)
    assert validate_macos_charge_plan(runner.config) is None
    assert runner.check_charge().status == '执行最小储蓄补电'



def test_shortage_from_caller_stops_without_reserve_or_next_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import restore_reserve_charge
    runner, replay, plan, controller = make_chain(monkeypatch, 'shortage')
    reserve = Mock()
    monkeypatch.setattr(restore_reserve_charge, 'GamepadRestoreReserveCharge', reserve)
    result = runner.execute()
    assert result.success and '电量不足' in result.status
    assert result.data['completed_battles'] == 0 and not result.data['plans_finished']
    assert plan.run_times == 0 and replay.starts == 0
    assert not runner.config.plan_list[0].skipped
    reserve.assert_not_called()
    controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('level', ['默认等级', '等级Lv.60'])
def test_actual_parent_resumes_battle_after_pause_without_start(
    monkeypatch: pytest.MonkeyPatch, level: str,
) -> None:
    runner, _replay, plan, controller = make_chain(monkeypatch, 'ok')
    plan.level = level
    op = GamepadAreaPatrol(runner.ctx, plan, config=runner.config)
    op._battle_active = True
    op._current_node = SimpleNamespace(cn='自动战斗')
    op._level_confirmed = True
    op.handle_pause()
    op.handle_resume()
    runner.ctx.auto_battle_context.stop_auto_battle.assert_called_once_with()
    runner.ctx.auto_battle_context.resume_auto_battle.assert_called_once_with()
    assert not op._level_confirmed
    controller.btn_tap.assert_not_called()

def test_resume_calls_parent_without_reissuing_start(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _replay, plan, controller = make_chain(monkeypatch, 'ok')
    op = GamepadAreaPatrol(runner.ctx, plan, config=runner.config)
    parent = Mock()
    monkeypatch.setattr(GamepadCombatSimulation, 'handle_resume', parent)
    op._level_confirmed = True
    op.handle_resume()
    parent.assert_called_once_with()
    assert not op._level_confirmed
    controller.btn_tap.assert_not_called()
