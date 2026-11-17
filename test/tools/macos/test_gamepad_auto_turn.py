"""普通任务允许默认转向策略，Mac 无镜头参数时仅停用周期转向。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.auto_battle import auto_battle_operator
from zzz_od.auto_battle.auto_battle_operator import AutoBattleOperator
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.notorious_hunt import GamepadHuntBattle, GamepadHuntDeploy


@pytest.mark.parametrize('entry', ['simulation', 'hunt_deploy', 'hunt_battle'])
@pytest.mark.parametrize('loaded', [True, False])
def test_default_strategy_passes_normal_task_entry(entry: str, loaded: bool) -> None:
    """默认两秒转向不阻断普通任务，真正缺少策略仍在出战前失败。"""
    classes = {
        'simulation': GamepadCombatSimulation,
        'hunt_deploy': GamepadHuntDeploy,
        'hunt_battle': GamepadHuntBattle,
    }
    operation = object.__new__(classes[entry])
    battle = Mock()
    battle.auto_op = SimpleNamespace(auto_turn_interval=2) if loaded else None
    operation.ctx = SimpleNamespace(auto_battle_context=battle, controller=Mock(), ocr=Mock())
    operation.ctx.ocr.run_ocr.return_value = {}
    operation.plan = SimpleNamespace(auto_battle_config='全配队通用', predefined_team_idx=-1)
    operation.prepare_only = False
    operation._sent = False
    operation.last_screenshot = object()
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    operation.original = Mock()

    if entry == 'simulation':
        result = operation.prepare_auto_battle()
    elif entry == 'hunt_deploy':
        result = operation.deploy()
    else:
        result = operation.start()

    assert result.is_success is loaded
    if loaded:
        assert battle.auto_op.auto_turn_interval == 2
    else:
        assert result.status == '自动战斗策略未加载'
        operation.ctx.controller.btn_tap.assert_not_called()
        operation.ctx.controller.begin_battle_input_scope.assert_not_called()
        operation.original.start_auto_op.assert_not_called()


@pytest.mark.parametrize('platform,speed,turns', [
    ('darwin', 0, False),
    ('darwin', -1, False),
    ('darwin', float('nan'), False),
    ('darwin', float('inf'), False),
    ('darwin', 771.9, True),
    ('win32', 0, True),
])
def test_periodic_turn_preserves_lock_and_saved_interval(
    monkeypatch: pytest.MonkeyPatch, platform: str, speed: float, turns: bool,
) -> None:
    """调用生产周期循环，Mac 缺参数不转向，锁定与 Windows 行为保持。"""
    monkeypatch.setattr(auto_battle_operator, 'sys', SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(auto_battle_operator, 'time', SimpleNamespace(time=lambda: 100))
    operation = object.__new__(AutoBattleOperator)
    game_ctx = SimpleNamespace(controller=Mock())
    if platform == 'darwin':
        game_ctx.macos_config = SimpleNamespace(turn_distance_per_second=speed)
    operation.ctx = SimpleNamespace(ctx=game_ctx, lock=Mock(), last_check_in_battle=True)
    operation.auto_lock_interval = 1
    operation.auto_turn_interval = 2
    operation.last_lock_time = 0
    operation.last_turn_time = 0
    operation.is_running = True
    operation._periodic_generation = 1
    operation._stop_event = Mock()
    operation._stop_event.wait.return_value = True

    operation.operate_periodically(1)

    assert game_ctx.controller.turn_by_distance.call_count == int(turns)
    operation.ctx.lock.assert_called_once()
    assert operation.auto_turn_interval == 2

    if platform == 'darwin' and not turns:
        # 同一缓存策略在补齐参数后重启，无需重建或改写配置即可恢复转向。
        game_ctx.macos_config.turn_distance_per_second = 771.9
        operation.last_turn_time = 0
        operation.operate_periodically(1)
        game_ctx.controller.turn_by_distance.assert_called_once_with(100)
