"""普通区域持续空挥时重新寻路，不判定挑战成功。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel


def contact_operation() -> GamepadLostVoidRunLevel:
    """只提供恢复判断需要的状态，不启动模型或设备。"""
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.region_type = LostVoidRegionType.COMBAT_RESONIUM
    operation._battle_active = True
    operation._battle_no_contact_since = 100
    operation._battle_contact_frame_time = 100
    operation.last_screenshot_time = 129
    operation.last_screenshot = object()
    operation.ctx = SimpleNamespace(
        run_context=SimpleNamespace(is_context_running=True),
        controller=SimpleNamespace(battle_input_blocked=False),
        auto_battle_context=SimpleNamespace(
            auto_op=SimpleNamespace(is_running=True, target_lock_interval=1,
                                    running_executor=SimpleNamespace(running=True)),
            is_normal_attack_btn_available=Mock(return_value=True),
            state_record_service=SimpleNamespace(get_state_recorder=Mock(return_value=None)),
        ),
    )
    return operation


def test_continuous_actions_do_not_hide_thirty_seconds_without_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """只在连续新帧和期限满足后重找，旧帧不会触发恢复。"""
    operation = contact_operation()
    now = [129.0]
    monkeypatch.setattr('zzz_od.operation.gamepad.lost_void_run_level.time.time', lambda: now[0])
    assert not operation._should_search_after_no_contact()
    now[0] = 130
    assert not operation._should_search_after_no_contact()
    operation.last_screenshot_time = 130
    assert operation._should_search_after_no_contact()


def test_no_contact_stops_strategy_before_returning_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复仅返回原寻路边，不返回通关结果。"""
    from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import (
        LostVoidRunLevel,
    )

    operation = contact_operation()
    operation._recovering_battle_frame = False
    operation.current_frame_in_battle = True
    operation._should_search_after_no_contact = Mock(return_value=True)
    operation._stop_battle = Mock()
    operation.save_screenshot = Mock()
    operation.round_success = Mock(return_value='search')
    operation._recover_idle_battle = Mock()
    monkeypatch.setattr(LostVoidRunLevel, 'in_battle', lambda _: SimpleNamespace(is_success=False, is_fail=False))
    assert operation.in_battle() == 'search'
    operation._stop_battle.assert_called_once_with(resume_menu=True)
    operation.round_success.assert_called_once_with('识别需移动交互')
    operation._recover_idle_battle.assert_not_called()


@pytest.mark.parametrize('signal', ['目标-近距离锁定', '闪避识别-红光', '闪避识别-黄光',
                                   '前台-血量扣减', '按键可用-连携技'])
def test_recent_contact_resets_search_wait(monkeypatch: pytest.MonkeyPatch, signal: str) -> None:
    operation = contact_operation()
    monkeypatch.setattr('zzz_od.operation.gamepad.lost_void_run_level.time.time', lambda: 131)
    operation.last_screenshot_time = 131
    operation.ctx.auto_battle_context.state_record_service.get_state_recorder.side_effect = (
        lambda name: SimpleNamespace(last_record_time=130) if name == signal else None
    )
    assert not operation._should_search_after_no_contact()
    assert operation._battle_no_contact_since == 0


@pytest.mark.parametrize('guard', ['paused', 'blocked', 'stale', 'menu', 'boss', 'elite', 'disabled'])
def test_contact_recovery_respects_input_and_boss_boundaries(monkeypatch: pytest.MonkeyPatch, guard: str) -> None:
    operation = contact_operation()
    monkeypatch.setattr('zzz_od.operation.gamepad.lost_void_run_level.time.time', lambda: 131)
    operation.last_screenshot_time = 131
    if guard == 'paused':
        operation.ctx.run_context.is_context_running = False
    elif guard == 'blocked':
        operation.ctx.controller.battle_input_blocked = True
    elif guard == 'stale':
        operation.last_screenshot_time = 129
    elif guard == 'menu':
        operation.ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    elif guard == 'disabled':
        operation.ctx.auto_battle_context.auto_op.target_lock_interval = 0
    else:
        operation.region_type = LostVoidRegionType.BOSS if guard == 'boss' else LostVoidRegionType.ELITE
    assert not operation._should_search_after_no_contact()
    assert operation._battle_no_contact_since == 0
