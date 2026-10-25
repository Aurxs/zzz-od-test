"""仅用内存配置与假操作验证 Mac 原体力计划调度，不连接游戏。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.charge_plan import charge_plan_app
from zzz_od.application.charge_plan.charge_plan_app import ChargePlanApp
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
)
from zzz_od.application.charge_plan.charge_plan_run_record import ChargePlanRunRecord
from zzz_od.application.zzz_application import ZApplication
from zzz_od.operation.gamepad import charge_plan
from zzz_od.operation.gamepad.charge_plan import (
    GamepadChargePlan,
    validate_macos_charge_plan,
)


@pytest.fixture
def config() -> ChargePlanConfig:
    """构造不读写文件的原配置，保留真实计数和循环方法。"""
    result = ChargePlanConfig.__new__(ChargePlanConfig)
    YamlOperator.__init__(result)
    result.data.update(loop=False, restore_charge='不使用', double_reward=False)
    result.plan_list = [ChargePlanItem(auto_battle_config='Mac全配队通用', plan_times=2)]
    return result


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('tab_name', '作战'),
        ('category_name', '专业挑战室'),
        ('mission_type_name', '代理人晋升'),
        ('mission_name', '音擎专项'),
        ('level', '50'),
        ('card_num', '1'),
        ('predefined_team_idx', 0),
    ],
)
def test_preflight_rejects_later_unsupported_plan(
    config: ChargePlanConfig, field: str, value: str | int,
) -> None:
    """即使前面的计划可执行，也先检查后面的任务且不替换用户设置。"""
    later = ChargePlanItem()
    setattr(later, field, value)
    config.plan_list.append(later)
    reason = validate_macos_charge_plan(config)
    assert reason is not None and '第 2 项' in reason and str(value) in reason
    assert getattr(later, field) == value
    assert all(plan.run_times == 0 for plan in config.plan_list)


@pytest.mark.parametrize(
    ('setting', 'value', 'expected'),
    [('restore_charge', '使用储蓄电量', '恢复电量'), ('double_reward', True, '双倍活动')],
)
def test_preflight_rejects_unimplemented_resource_options(
    config: ChargePlanConfig, setting: str, value: str | bool, expected: str,
) -> None:
    """不静默忽略补电和临时计划配置。"""
    config.data[setting] = value
    assert expected in validate_macos_charge_plan(config)


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_application_checks_macos_before_bootstrap_only(
    monkeypatch: pytest.MonkeyPatch, config: ChargePlanConfig, platform: str,
) -> None:
    """Mac 未支持计划不进入公共启动，Windows 仍委托原应用执行。"""
    config.plan_list[0].card_num = '1'
    app = ChargePlanApp.__new__(ChargePlanApp)
    app.config = config
    delegate = Mock(return_value=OperationResult(True, '原应用'))
    monkeypatch.setattr(charge_plan_app, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(ZApplication, 'execute', delegate)
    result = app.execute()
    if platform == 'darwin':
        assert not result.success and '卡片数量' in result.status
        delegate.assert_not_called()
    else:
        assert result.status == '原应用'
        delegate.assert_called_once_with()


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_start_routes_only_macos_to_saved_plan_runner(
    monkeypatch: pytest.MonkeyPatch, config: ChargePlanConfig, platform: str,
) -> None:
    """原开始节点的精确状态边只在 Mac 分流，并传入同一份配置与记录。"""
    app = ChargePlanApp.__new__(ChargePlanApp)
    app.ctx = SimpleNamespace()
    app.config = config
    app.run_record = Mock(spec=ChargePlanRunRecord)
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(charge_plan_app, 'sys', SimpleNamespace(platform=platform))
    result = app.start_charge_plan()
    assert result.status == (ChargePlanApp.STATUS_MACOS_PLAN if platform == 'darwin' else None)
    factory = Mock()
    factory.return_value.execute.return_value = OperationResult(True, '原配置调度完成')
    monkeypatch.setattr(charge_plan, 'GamepadChargePlan', factory)
    if platform == 'darwin':
        assert app.run_macos_plan().status == '原配置调度完成'
        factory.assert_called_once_with(app.ctx, config, app.run_record)
    else:
        factory.assert_not_called()


@pytest.fixture
def operation(
    monkeypatch: pytest.MonkeyPatch, config: ChargePlanConfig,
) -> GamepadChargePlan:
    """业务节点使用严格假控制器，子操作不执行真实输入。"""
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap']),
        run_context=Mock(),
        current_instance_idx=99,
        screen_loader=Mock(),
    )
    result = GamepadChargePlan(ctx, config, Mock(spec=ChargePlanRunRecord))
    monkeypatch.setattr(result, '_after_round_wait', Mock())
    monkeypatch.setattr(result, '_found', Mock(return_value=True))
    result.last_screenshot = object()
    return result


def test_saved_plan_repeats_until_its_original_count(
    monkeypatch: pytest.MonkeyPatch, operation: GamepadChargePlan,
) -> None:
    """原配置累计两场，逐场复核实际一百，不走 PC 导航或另建计划。"""
    simulation = Mock()
    simulation.read_charge.side_effect = [(200, 100), (100, 100)]

    def win() -> OperationResult:
        """模拟既有单次操作已经保存胜利次数。"""
        operation.config.add_plan_run_times(operation.current_plan)
        return OperationResult(True)

    simulation.execute.side_effect = win
    factory = Mock(return_value=simulation)
    monkeypatch.setattr(charge_plan, 'GamepadCombatSimulation', factory)
    transport = Mock()
    transport.return_value.execute.return_value = OperationResult(True)
    monkeypatch.setattr(charge_plan, 'GamepadTransportByCompendium', transport)
    for expected_runs in (1, 2):
        assert operation.select_plan().status is None
        assert operation.transport().is_success
        assert operation.check_charge().status is None
        assert operation.run_battle().is_success
        assert operation.config.plan_list[0].run_times == expected_runs
    assert operation.select_plan().status == operation.STATUS_FINISHED
    result = operation.finish()
    assert result.data == {
        'completed_battles': 2, 'plans_finished': True, 'remaining_charge': None,
    }
    assert factory.call_args.kwargs['config'] is operation.config
    assert transport.call_args_list == [call(operation.ctx, '训练', '实战模拟室', '基础材料')] * 2
    operation.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('skip_plan', [False, True])
def test_shortage_returns_once_per_known_page_and_preserves_progress(
    monkeypatch: pytest.MonkeyPatch, operation: GamepadChargePlan, skip_plan: bool,
) -> None:
    """不足一百时不战斗、不补电，未知页不输入，结束仍保留未完成计划。"""
    operation.config.data['skip_plan'] = skip_plan
    operation.config.plan_list[0].run_times = 1
    simulation = Mock()
    simulation.read_charge.return_value = (99, 100)
    monkeypatch.setattr(charge_plan, 'GamepadCombatSimulation', Mock(return_value=simulation))
    operation.select_plan()
    assert operation.check_charge().status == operation.STATUS_CHARGE_NOT_ENOUGH
    frame = ['preset']
    monkeypatch.setattr(operation, 'round_by_find_area', lambda *args: (
        operation.round_success() if frame[0] == 'world' else operation.round_retry()
    ))
    monkeypatch.setattr(operation, '_found', lambda name: (
        frame[0] == 'preset' and name in ('手柄-挑战等级', '手柄-下一步')
    ) or (
        frame[0] == 'category' and name in ('手柄-基础材料分类', '手柄-代理人晋升分类')
    ))
    for scene in ('preset', 'preset', 'unknown', 'category', 'category'):
        frame[0] = scene
        assert not operation.return_after_shortage().is_success
    frame[0] = 'world'
    result = operation.return_after_shortage()
    assert result.is_success and '未完成计划保留' in result.status
    assert result.data == {
        'completed_battles': 0, 'plans_finished': False, 'remaining_charge': 99,
    }
    assert operation.config.plan_list[0].run_times == 1
    simulation.execute.assert_not_called()
    operation.ctx.controller.btn_tap.assert_has_calls([call('east'), call('east')])
    assert operation.ctx.controller.btn_tap.call_count == 2


def test_loop_uses_original_round_reset(
    operation: GamepadChargePlan, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """循环扣减沿用原配置，不把一次运行的胜利次数改成电量目标。"""
    operation.config.data['loop'] = True
    operation.config.plan_list[0].run_times = 3
    monkeypatch.setattr(charge_plan, 'GamepadCombatSimulation', Mock())
    assert operation.select_plan().status is None
    assert operation.config.plan_list[0].run_times == 1
    assert operation.current_plan is operation.config.plan_list[0]


@pytest.mark.parametrize('succeeded', [False, True])
def test_failed_or_unrecorded_battle_never_increments_count(
    monkeypatch: pytest.MonkeyPatch, operation: GamepadChargePlan, succeeded: bool,
) -> None:
    """失败或缺少胜利记录都停止，不重试战斗或伪造计划进度。"""
    simulation = Mock()
    simulation.execute.return_value = OperationResult(succeeded, '未确认胜利')
    monkeypatch.setattr(charge_plan, 'GamepadCombatSimulation', Mock(return_value=simulation))
    operation.select_plan()
    result = operation.run_battle()
    assert result.is_fail
    assert operation.current_plan.run_times == 0 and operation.completed_battles == 0
    assert operation.current_charge is None
    assert operation.run_record.charge_power_snapshot == [0, -1]
    simulation.execute.assert_called_once()


@pytest.mark.parametrize('charge', [None, (200, 20)])
def test_missing_or_unverified_actual_charge_never_starts_battle(
    monkeypatch: pytest.MonkeyPatch, operation: GamepadChargePlan,
    charge: tuple[int, int] | None,
) -> None:
    """识别缺失或实际消耗不为一百时，不使用计划中的默认二十预估。"""
    simulation = Mock()
    simulation.read_charge.return_value = charge
    monkeypatch.setattr(charge_plan, 'GamepadCombatSimulation', Mock(return_value=simulation))
    operation.select_plan()
    assert not operation.check_charge().is_success
    simulation.execute.assert_not_called()
    operation.ctx.controller.btn_tap.assert_not_called()
