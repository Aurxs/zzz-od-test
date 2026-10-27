"""局内战斗与初始武备确认的最小输入边界。"""

from types import SimpleNamespace
from unittest.mock import Mock, call
from pathlib import Path

import numpy as np
import pytest

from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel






def test_battle_requires_hud_and_scope_precedes_strategy() -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    battle = Mock()
    battle.auto_op = SimpleNamespace(auto_turn_interval=0)
    operation.ctx = SimpleNamespace(auto_battle_context=battle, controller=Mock())
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.round_retry = Mock(return_value='wait')
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.round_success = Mock(return_value='start')
    battle.is_normal_attack_btn_available.return_value = False
    assert operation.init_auto_op() == 'wait'
    battle.start_auto_battle.assert_not_called()
    operation.ctx.controller.begin_battle_input_scope.assert_not_called()
    order = Mock()
    order.attach_mock(operation.ctx.controller.begin_battle_input_scope, 'guard')
    order.attach_mock(battle.start_auto_battle, 'start')
    battle.is_normal_attack_btn_available.return_value = True
    operation._unknown_hud_since = 123
    assert operation.init_auto_op() == 'start'
    assert operation._unknown_hud_since == 0
    assert [item[0] for item in order.mock_calls] == ['guard', 'start']
    order.attach_mock(battle.stop_auto_battle, 'stop')
    order.attach_mock(operation.ctx.controller.end_battle_input_scope, 'end')
    order.attach_mock(operation.ctx.controller.resume_input, 'resume')
    order.reset_mock()
    operation._unknown_hud_since = 123
    operation._stop_battle(resume_menu=True)
    assert operation._unknown_hud_since == 0
    assert order.mock_calls == [call.stop(), call.end(), call.resume()]


def test_attack_inner_variant_accepts_glow_and_rejects_reward_menus() -> None:
    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.template_loader import TemplateLoader
    from one_dragon.utils import cv2_utils
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext

    battle = object.__new__(AutoBattleContext)
    battle.ctx = SimpleNamespace(tm=TemplateMatcher(TemplateLoader()))
    battle.area_btn_normal = SimpleNamespace(rect=Rect(1403, 916, 1505, 1017))
    battle.normal_attack_template_variants = ()
    screens = Path(__file__).resolve().parents[3] / 'screens'
    glow = cv2_utils.read_image(str(screens / '迷失之地-大世界' / 'ios_attack_glow.webp'))
    assert not battle.is_normal_attack_btn_available(glow)
    battle.normal_attack_template_variants = (('ios_gamepad', 'lost_void_attack_inner'),)
    assert battle.is_normal_attack_btn_available(glow)
    for folder, name in (
        ('迷失之地-通用选择', 'ios_single_initial.webp'),
        ('迷失之地-邦布商店', 'ios_gold_store.webp'),
        ('迷失之地-挑战结果', 'ios_final_s.webp'),
    ):
        frame = cv2_utils.read_image(str(screens / folder / name))
        assert not battle.is_normal_attack_btn_available(frame), (folder, name)


@pytest.mark.parametrize('fails', [False, True])
def test_lost_void_restores_attack_variants_on_every_exit(monkeypatch: pytest.MonkeyPatch, fails: bool) -> None:
    from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel

    battle = SimpleNamespace(normal_attack_template_variants=())
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(auto_battle_context=battle, run_context=SimpleNamespace(is_context_running=False))
    operation._stop_battle = Mock()
    result = SimpleNamespace(success=True)

    def execute_original(_: LostVoidRunLevel) -> SimpleNamespace:
        assert battle.normal_attack_template_variants == (('ios_gamepad', 'lost_void_attack_inner'),)
        if fails:
            raise RuntimeError('模拟退出')
        return result

    monkeypatch.setattr(LostVoidRunLevel, 'execute', execute_original)
    if fails:
        with pytest.raises(RuntimeError, match='模拟退出'):
            operation.execute()
    else:
        assert operation.execute() is result
    assert battle.normal_attack_template_variants == ()
    operation._stop_battle.assert_called_once()


@pytest.mark.parametrize('speed', [0, 771.9])
def test_original_auto_turn_requires_saved_macos_calibration(speed: float) -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    battle = Mock()
    battle.auto_op = SimpleNamespace(auto_turn_interval=2)
    operation.ctx = SimpleNamespace(auto_battle_context=battle, controller=Mock(), macos_config=SimpleNamespace(turn_distance_per_second=speed))
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.round_success = Mock(return_value='start')
    operation.round_fail = Mock(return_value='failed')
    assert operation.init_auto_op() == ('start' if speed else 'failed')
    assert battle.start_auto_battle.call_count == int(speed > 0)
    assert operation.ctx.controller.begin_battle_input_scope.call_count == int(speed > 0)


def recovery_operation() -> GamepadLostVoidRunLevel:
    from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType

    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(
        auto_battle_context=Mock(),
        controller=SimpleNamespace(battle_input_blocked=False, refresh_battle_input_scope=Mock(side_effect=[False, True])),
        battle_assistant_config=SimpleNamespace(screenshot_interval=0.1),
    )
    operation._invalid_battle_frames = 0
    operation._battle_active = True
    operation._recovering_battle_frame = False
    operation._unknown_hud_since = 0
    operation.region_type = LostVoidRegionType.ENTRY
    operation.last_screenshot = None
    operation._stop_battle = Mock()
    operation.check_and_update_current_screen = Mock(return_value=None)
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.round_wait = Mock(return_value='wait')
    operation.round_fail = Mock(return_value='failed')
    return operation


def test_missing_battle_frame_stops_strategy_until_fresh_hud_passes() -> None:
    operation = recovery_operation()
    assert operation.in_battle() == 'wait'
    assert not operation._battle_active
    operation.ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    assert operation.in_battle() == 'wait'
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    assert operation.in_battle() == 'wait'
    operation.ctx.auto_battle_context.resume_auto_battle.assert_called_once()
    assert operation._battle_active and not operation._recovering_battle_frame


def test_three_missing_battle_frames_terminate_without_resuming() -> None:
    operation = recovery_operation()
    assert operation.in_battle() == 'wait'
    assert operation.in_battle() == 'wait'
    assert operation.in_battle() == 'failed'
    operation._stop_battle.assert_called_once()
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()


def test_interact_button_returns_to_navigation_only_after_three_fresh_frames() -> None:
    operation = recovery_operation()
    operation.ctx.controller.battle_input_blocked = True
    operation._battle_interact_frames = 0
    operation._battle_interact_frame_time = -1
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.last_screenshot_time = 100
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    operation.round_success = Mock(return_value='navigation')
    assert operation.in_battle() == 'wait'
    assert operation.in_battle() == 'wait'
    assert operation._battle_interact_frames == 1
    operation.last_screenshot_time = 101
    assert operation.in_battle() == 'wait'
    operation.last_screenshot_time = 102
    assert operation.in_battle() == 'navigation'
    operation._stop_battle.assert_called_once_with(resume_menu=True)
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    operation.round_success.assert_called_once_with('识别需移动交互')


def test_interact_visible_before_battle_returns_without_starting_strategy() -> None:
    operation = recovery_operation()
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    operation.round_by_find_area.return_value = SimpleNamespace(is_success=True)
    operation.round_success = Mock(return_value='navigation')
    assert operation.init_auto_op() == 'navigation'
    operation.ctx.auto_battle_context.start_auto_battle.assert_not_called()
    operation.round_success.assert_called_once_with('识别需移动交互')


def test_black_loading_is_next_level_only_after_known_entry_interaction() -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.interact_target = SimpleNamespace(is_entry=True, icon='战斗-鸣徽')
    operation.round_success = Mock(return_value='next')
    assert operation.handle_interact() == 'next'
    operation.round_success.assert_called_once_with(operation.STATUS_NEXT_LEVEL, data='战斗-鸣徽')
    operation.interact_target = None
    operation.ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)), screen_loader=SimpleNamespace(get_area=Mock(return_value=None)))
    operation.try_talk = Mock(return_value=None)
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.check_and_update_current_screen = Mock(return_value=None)
    operation.save_screenshot = Mock()
    operation.round_fail = Mock(return_value='unknown')
    operation._unknown_interact_rounds = 0
    operation.round_wait = Mock(return_value='waiting')
    for _ in range(3):
        assert operation.handle_interact() == 'waiting'
    assert operation.handle_interact() == 'unknown'


def test_interaction_animation_waits_for_known_card_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_common

    operation = recovery_operation()
    operation.ctx.lost_void = SimpleNamespace(in_normal_world=Mock(return_value=False))
    operation.ctx.screen_loader = SimpleNamespace(get_area=Mock(return_value=None))
    operation.ctx.controller.btn_tap = Mock()
    operation.last_screenshot = np.full((1080, 1920, 3), 60, dtype=np.uint8)
    operation.interact_target = None
    operation.try_talk = Mock(return_value=None)
    operation._unknown_interact_rounds = 0
    common = Mock()
    common.can_handle.side_effect = [False, True]
    common.execute.return_value = SimpleNamespace(success=True, status='已确认')
    monkeypatch.setattr(lost_void_common, 'GamepadLostVoidChooseCommon', lambda ctx: common)
    assert operation.handle_interact() == 'wait'
    assert operation._unknown_interact_rounds == 1
    common.execute.assert_not_called()
    assert operation.handle_interact() == 'wait'
    assert operation._unknown_interact_rounds == 0
    common.execute.assert_called_once()
    operation.ctx.controller.btn_tap.assert_not_called()


def test_entry_repeated_gear_uses_original_three_repeat_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import LostVoidDetector
    from zzz_od.operation.gamepad import lost_void_common, lost_void_gear

    operation = recovery_operation()
    operation.ctx.lost_void = SimpleNamespace(in_normal_world=Mock(return_value=False))
    operation.ctx.screen_loader = SimpleNamespace(get_area=Mock(return_value=None))
    operation.last_screenshot = np.full((1080, 1920, 3), 60, dtype=np.uint8)
    operation.interact_target = None
    operation.try_talk = Mock(return_value=None)
    operation.round_by_find_area.side_effect = lambda image, screen, area: SimpleNamespace(is_success=area in ('按钮-携带', '文本-详情'))
    operation.entry_gear_name_list = ['首个武备']
    operation.entry_gear_repeat_times = 0
    operation.entry_door_block_times = 8
    operation.had_been_list = []
    common = Mock()
    common.can_handle.return_value = False
    monkeypatch.setattr(lost_void_common, 'GamepadLostVoidChooseCommon', lambda ctx: common)
    gear = SimpleNamespace(parser=SimpleNamespace(STATUS_REPEATED='重复武备选择'), execute=Mock(return_value=SimpleNamespace(success=True, status='重复武备选择')))
    monkeypatch.setattr(lost_void_gear, 'GamepadLostVoidChooseGear', lambda ctx, completed: gear)
    for count in (1, 2, 3, 4):
        assert operation.handle_interact() == 'wait'
        assert operation.entry_gear_repeat_times == count
        assert operation.entry_door_block_times == 0
        assert operation.entry_gear_interact_done
        assert 'NPC武备' in operation.had_been_list
        assert operation.had_been_list.count(LostVoidDetector.CLASS_INTERACT[5:]) == int(count >= 3)


@pytest.mark.parametrize(('dx', 'direction'), [(-240, -0.5), (240, 0.5), (30, None)])
def test_entry_correction_uses_calibrated_camera_instead_of_sideways_movement(dx: float, direction: float | None) -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(controller=Mock(), macos_config=SimpleNamespace(turn_distance_per_second=771.9, turn_stick_amplitude=0.5))
    operation._sidestep_by_dx(dx)
    if direction is None:
        operation.ctx.controller.move_camera.assert_not_called()
    else:
        operation.ctx.controller.move_camera.assert_called_once_with(direction, 0, press_time=0.15)
    operation.ctx.controller.move_a.assert_not_called()
    operation.ctx.controller.move_d.assert_not_called()




def test_colored_gate_transition_keeps_next_region_after_fast_load() -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.last_screenshot = np.full((1080,1920,3),60,dtype=np.uint8)
    operation.interact_target = SimpleNamespace(is_entry=True,icon='偶遇事件')
    operation.ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)),
                                    screen_loader=SimpleNamespace(get_area=Mock(return_value=None)))
    operation.try_talk = Mock(return_value=None)
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.check_and_update_current_screen = Mock(return_value=None)
    operation.round_success = Mock(return_value='next')
    assert operation.handle_interact() == 'next'
    operation.round_success.assert_called_with(operation.STATUS_NEXT_LEVEL,data='偶遇事件')
    operation._previous_node = None
    operation._previous_round_result = SimpleNamespace(status=operation.STATUS_NEXT_LEVEL,data='偶遇事件')
    operation.ctx.lost_void.in_normal_world.return_value = True
    assert operation.after_interact() == 'next'
    operation.round_success.assert_called_with(operation.STATUS_NEXT_LEVEL,data='偶遇事件')
