"""独立助手只验证原生入口、配置保留和输入生命周期。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.operation.gamepad import battle_assistant as mac


def context() -> SimpleNamespace:
    controller = Mock()
    controller.battle_input_blocked = False
    return SimpleNamespace(controller=controller, auto_battle_context=Mock(), run_context=Mock())


def test_macos_input_does_not_use_windows_driver_or_change_setting(monkeypatch) -> None:
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as mode
    from zzz_od.gui.view.battle_assistant.battle_assistant_interface import (
        BattleAssistantInterface,
    )

    monkeypatch.setattr(mode.sys, 'platform', 'darwin')
    monkeypatch.setattr(mode.pc_button_utils, 'is_vgamepad_installed', Mock(side_effect=AssertionError('不应检查 Windows 驱动')))
    ctx = context()
    ctx.controller.is_game_window_ready = True
    ctx.controller.gamepad.is_connected = True
    ctx.battle_assistant_config = SimpleNamespace(background_mode=True)
    assert mode.apply_battle_assistant_input_mode(ctx)[0]
    ctx.controller.enable_foreground_mode.assert_not_called()
    ctx.controller.enable_background_mode.assert_not_called()
    ctx.controller.active_window.assert_not_called()
    assert ctx.battle_assistant_config.background_mode is True
    page = Mock()
    BattleAssistantInterface._on_background_mode_changed(page, True)
    page.background_mode_opt.setValue.assert_not_called()
    ctx.controller.gamepad.is_connected = False
    assert not mode.apply_battle_assistant_input_mode(ctx)[0]


def test_wait_battle_block_pause_resume_and_close(monkeypatch) -> None:
    ctx = context()
    native = Mock(return_value=False)
    monkeypatch.setattr(mac, 'is_native_battle', native)
    clock = [1.0]
    monkeypatch.setattr(mac.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(mac, 'MacBattleHudGuard', Mock(return_value=Mock(return_value=True)))
    session = mac.MacBattleAssistantSession(ctx, auto_ultimate_enabled=False)
    assert not session.update(None)
    assert not session.update(None)
    ctx.controller.pause_input.assert_called_once()
    ctx.auto_battle_context.start_auto_battle.assert_not_called()
    native.return_value = True
    assert session.update(Mock())
    assert ctx.auto_battle_context.auto_ultimate_enabled is False
    ctx.controller.battle_input_blocked = True
    ctx.controller.refresh_battle_input_scope.return_value = False
    assert not session.update(Mock())
    assert not session.update(Mock())
    ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    clock[0] = 2.0
    ctx.controller.refresh_battle_input_scope.return_value = True
    assert session.update(Mock())
    ctx.auto_battle_context.resume_auto_battle.assert_called_once()
    session.pause()
    ctx.controller.end_battle_input_scope.assert_called_once()
    ctx.controller.battle_input_blocked = False
    native.return_value = False
    assert session.update(Mock())
    session.close()
    session.close()
    assert not session.update(Mock())
    assert ctx.controller.end_battle_input_scope.call_count == 2


def test_stop_error_still_releases_scope(monkeypatch) -> None:
    ctx = context()
    monkeypatch.setattr(mac, 'is_native_battle', Mock(return_value=True))
    session = mac.MacBattleAssistantSession(ctx)
    session.update(Mock())
    ctx.auto_battle_context.stop_auto_battle.side_effect = RuntimeError('停止异常')
    with pytest.raises(RuntimeError):
        session.close()
    ctx.controller.end_battle_input_scope.assert_called_once()
    assert not session.update(Mock())


def test_entry_accepts_native_battle_without_world_bootstrap(monkeypatch) -> None:
    ctx = context()
    ctx.macos_session_preparation = Mock()
    ctx.macos_session_preparation.prepare.return_value = OperationResult(True)
    op = mac.GamepadBattleAssistantEntry(ctx)
    op._after_round_wait = Mock()
    op.last_screenshot = Mock()
    native = Mock(return_value=True)
    monkeypatch.setattr(mac, 'is_native_battle', native)
    monkeypatch.setattr(mac, 'is_native_battle_menu', Mock(return_value=False))
    assert op.prepare().is_success
    ctx.macos_session_preparation.prepare.assert_not_called()
    native.return_value = False
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    assert op.prepare().is_success
    ctx.macos_session_preparation.prepare.assert_called_once()


def test_native_hint_real_frame_and_card_page_negative() -> None:
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.base.screen.template_loader import TemplateLoader
    from one_dragon.utils import cv2_utils

    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    ctx = SimpleNamespace(auto_battle_context=Mock(), screen_loader=loader, tm=TemplateMatcher(TemplateLoader()))
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = True
    root = Path(__file__).resolve().parents[3] / 'screens'
    assert mac.is_native_battle(ctx, cv2_utils.read_image(str(root / '战斗画面' / 'ios_assistant_native_entry.webp')))
    assert not mac.is_native_battle(ctx, cv2_utils.read_image(str(root / '恶名狩猎' / 'ios_buff_three_cards.webp')))


def test_dodge_cleanup_runs_base_after_session_failure(monkeypatch) -> None:
    from zzz_od.application.battle_assistant.dodge_assitant.dodge_assistant_app import (
        DodgeAssistantApp,
    )
    from zzz_od.application.zzz_application import ZApplication

    app = object.__new__(DodgeAssistantApp)
    app._mac_session = Mock()
    app._mac_session.close.side_effect = RuntimeError('停止异常')
    base = Mock()
    monkeypatch.setattr(ZApplication, 'after_operation_done', base)
    result = OperationResult(False)
    with pytest.raises(RuntimeError):
        app.after_operation_done(result)
    base.assert_called_once_with(app, result)


@pytest.mark.parametrize('mode,allowed', [('无报酬模式OFF剩余奖励次数:0/3', True), ('无报酬模式ON剩余奖励次数:0/3', False), ('无报酬模式OFF剩余奖励次数:1/3', False)])
def test_unrewarded_preparation_never_uses_free_reward_or_energy(mode: str, allowed: bool) -> None:
    from zzz_od.operation.gamepad.notorious_hunt import GamepadHuntPrepare

    op = GamepadHuntPrepare(context(), SimpleNamespace(mission_type_name='库萨里库', predefined_team_idx=-1), unrewarded=True)
    op._after_round_wait = Mock()
    op.navigation._read_area = Mock(return_value=(None, {mode: []}))
    op.navigation._text_rect = Mock(return_value=Mock())
    assert op.check_target().is_success is allowed
    op.ctx.controller.btn_tap.assert_not_called()


def test_disable_deep_only_toggles_known_target_once(monkeypatch) -> None:
    from zzz_od.operation.gamepad import deep_hunt

    ctx = context()
    op = deep_hunt.GamepadDisableDeepHunt(ctx, '库萨里库')
    op._after_round_wait = Mock()
    op.save_screenshot = Mock()
    monkeypatch.setattr(deep_hunt, 'hunt_title_selected', Mock(return_value=False))
    monkeypatch.setattr(deep_hunt, 'read_preset_area', Mock(return_value=(None, {'挑战等级电量消耗159/60': []})))
    assert op.disable().is_fail
    ctx.controller.btn_tap.assert_not_called()
    deep_hunt.hunt_title_selected.return_value = True
    monkeypatch.setattr(deep_hunt, 'deep_hunt_enabled', Mock(return_value=True))
    op.disable()
    op.disable()
    ctx.controller.btn_tap.assert_called_once_with('right_stick_click')


@pytest.mark.parametrize('message,allowed', [('本周内获取恶名狩猎奖励的次数已耗尽，无法获得挑战奖励，是否继续挑战', True), ('是否开启深度追猎，额外消耗电量继续挑战', False)])
def test_unrewarded_notice_does_not_accept_energy_dialog(monkeypatch, message: str, allowed: bool) -> None:
    from one_dragon.base.geometry.rectangle import Rect
    from zzz_od.operation.gamepad import notorious_hunt

    ctx = context()
    ctx.ocr = Mock()
    ctx.ocr.run_ocr.return_value = {message: [], '确认': [SimpleNamespace(rect=Rect(950, 600, 1120, 680))]}
    op = notorious_hunt.GamepadConfirmUnrewardedHunt(ctx)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock()
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    monkeypatch.setattr(notorious_hunt, 'has_filled_highlight', lambda *args: True)
    op.confirm()
    assert ctx.controller.btn_tap.called is allowed


def test_paused_context_cannot_recreate_input_scope(monkeypatch) -> None:
    ctx = context()
    monkeypatch.setattr(mac, 'is_native_battle', Mock(return_value=True))
    ctx.run_context.is_context_running = False
    session = mac.MacBattleAssistantSession(ctx)
    assert not session.update(Mock())
    ctx.controller.begin_battle_input_scope.assert_not_called()
    ctx.run_context.is_context_running = True
    assert session.update(Mock())
    session.pause()
    ctx.run_context.is_context_running = False
    assert not session.update(Mock())
    assert ctx.controller.begin_battle_input_scope.call_count == 1


def test_menu_start_waits_and_resume_uses_only_back(monkeypatch) -> None:
    ctx = context()
    op = mac.GamepadBattleAssistantEntry(ctx)
    op._after_round_wait = Mock()
    op.last_screenshot = Mock()
    monkeypatch.setattr(mac, 'is_native_battle', Mock(return_value=False))
    monkeypatch.setattr(mac, 'is_native_battle_menu', Mock(return_value=True))
    assert op.prepare().is_success
    ctx.controller.btn_tap.assert_not_called()
    resume = mac.GamepadResumeBattle(ctx)
    resume._after_round_wait = Mock()
    resume.resume()
    resume.resume()
    ctx.controller.btn_tap.assert_called_once_with('east')


def test_native_menu_requires_controller_keys() -> None:
    ctx = context()
    ctx.screen_loader = Mock()
    ctx.ocr = Mock()
    ctx.ocr.crop_and_run_ocr.return_value = {word: [] for word in ('重新开始','退出战斗','返回','A','B')}
    assert mac.is_native_battle_menu(ctx, Mock())
    ctx.ocr.crop_and_run_ocr.return_value = {word: [] for word in ('重新开始','退出战斗','返回')}
    assert not mac.is_native_battle_menu(ctx, Mock())
