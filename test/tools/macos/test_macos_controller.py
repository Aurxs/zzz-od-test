"""使用假输入和假采集验证 Mac 控制器，不启动客户端或发送真实输入。"""

from __future__ import annotations

import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.config.game_account_config import GamePlatformEnum
from one_dragon.base.controller.gamepad_input import GamepadInput, GamepadState
from one_dragon.base.controller.macos.macos_game_launcher import MacGameLauncher
from one_dragon.base.controller.macos.macos_window_capture import (
    MacWindow,
    MacWindowCapture,
)
from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame
from one_dragon.utils import os_utils
from zzz_od.config.game_config import GameConfig
from zzz_od.config.macos_config import MacOsConfig
from zzz_od.context import zzz_context
from zzz_od.controller import zzz_macos_controller


@pytest.fixture
def controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> zzz_macos_controller.ZMacController:
    """隔离配置目录，注入不会调用原生 API 的输入与采集对象。"""
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    gamepad = Mock(spec=GamepadInput)
    gamepad.is_connected = True
    capture = Mock(spec=MacWindowCapture)
    capture.window = MacWindow('com.miHoYo.Nap', 123, 456, '游戏', 1920, 1080)
    capture.last_error = None
    capture.latest_frame.return_value = CapturedFrame(
        np.full((1080, 1920, 3), 20, dtype=np.uint8), 1, 123.0, 123.0, 1920, 1080,
    )
    launcher = MacGameLauncher(capture, 'com.miHoYo.Nap', app_path=str(tmp_path / 'missing.app'))
    monkeypatch.setattr(launcher, '_running_process_ids', Mock(return_value=[]))
    return zzz_macos_controller.ZMacController(
        GameConfig(1), MacOsConfig(1), gamepad=gamepad, window_capture=capture,
        game_launcher=launcher,
    )


def test_constructor_and_unknown_inputs_do_not_fallback(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """构造不启动输入，未知键和坐标操作也不会转成桌面键鼠。"""
    controller.gamepad.connect.assert_not_called()
    controller.window_capture.start.assert_not_called()
    assert controller.run_generation == 0
    with pytest.raises(ValueError, match='不支持的手柄按键'):
        controller.btn_tap('mouse_left')
    with pytest.raises(NotImplementedError, match='坐标点击'):
        controller.click()
    with pytest.raises(ValueError, match='未配置手柄动作'):
        controller.click(gamepad_key='unknown')
    with pytest.raises(NotImplementedError, match='文本输入'):
        controller.input_str('不发送')
    controller.gamepad.tap.assert_not_called()
    controller.gamepad.tap_combo.assert_not_called()


def test_window_selection_ignores_helpers_and_accepts_empty_main_title(
    controller: zzz_macos_controller.ZMacController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同客户端包含菜单和辅助窗口时，选择没有标题的唯一大游戏窗口。"""
    main = MacWindow('com.miHoYo.Nap', 123, 789, '', 1920, 1080)
    controller.window_capture.list_windows.return_value = [
        MacWindow('com.miHoYo.Nap', 123, 111, '菜单', 1920, 33),
        MacWindow('com.miHoYo.Nap', 123, 222, '辅助', 320, 64),
        main,
    ]
    monkeypatch.setattr(controller, '_start_frame_monitor', Mock())

    assert controller.init_before_context_run() is True

    controller.window_capture.start.assert_called_once_with(main, fps=30, top_inset_pixels=0)
    assert controller.run_generation == 1
    controller.window_capture.list_windows.return_value = []
    assert controller.init_before_context_run() is False
    assert controller.run_generation == 2  # 失败重连也使旧准备缓存失效。


def test_semantic_actions_use_xbox_config(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """既有动作名称和显式手柄区域动作都只进入新输入接口。"""
    controller._input_paused = False
    controller.normal_attack(press=True, press_time=0.2)
    controller.normal_attack(release=True)
    assert controller.click(gamepad_key='compendium') is True
    controller.gamepad.press.assert_called_once_with('xbox_x', 0.2)
    controller.gamepad.release.assert_called_once_with('xbox_x')
    controller.gamepad.tap_combo.assert_called_once_with(['xbox_lt', 'xbox_a'])


def test_cold_start_connects_neutral_before_launch_and_only_resumes_after_frame(
    controller: zzz_macos_controller.ZMacController, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """先建立中立设备，等启动窗口与新帧后才允许输入；失败完整清理。"""
    launcher = Mock()
    launcher.started_game = True
    controller.game_launcher = launcher
    monkeypatch.setattr(controller, '_start_frame_monitor', Mock())
    history = Mock()
    for name, callback in (
        ('connect', controller.gamepad.connect), ('suspend', controller.gamepad.suspend),
        ('launch', launcher.ensure_window), ('capture', controller.window_capture.start),
        ('resume', controller.gamepad.resume),
    ):
        history.attach_mock(callback, name)

    def launch() -> MacWindow:
        """即使假采集已有帧，启动等待中也不允许任何按键。"""
        with pytest.raises(RuntimeError, match='已暂停'):
            controller.btn_tap('south')
        return controller.window_capture.window

    launcher.ensure_window.side_effect = launch
    assert controller.init_before_context_run()
    assert [entry[0] for entry in history.mock_calls] == ['connect', 'suspend', 'launch', 'capture', 'resume']
    assert controller.started_game_this_run
    controller.gamepad.tap.assert_not_called()
    launcher.ensure_window.side_effect = RuntimeError('假启动失败')
    assert not controller.init_before_context_run()
    assert not controller.started_game_this_run
    assert controller._input_paused


def test_screenshot_preserves_capture_time_mask_and_bounded_history(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """使用帧自带时间，UID 遮挡不改原帧，历史同时受数量与帧龄限制。"""
    original = controller.window_capture.latest_frame.return_value
    controller.max_screenshot_cnt = 2
    capture_time, image = controller.screenshot()
    assert capture_time == original.capture_time == 123.0
    assert image is not original.image
    assert np.all(original.image == 20)
    assert not np.array_equal(image[1060:1079, 1680:1804], original.image[1060:1079, 1680:1804])
    for capture_time in (124.0, 125.0, 140.0):
        controller.window_capture.latest_frame.return_value = replace(original, capture_time=capture_time)
        controller.screenshot()
        assert len(controller.screenshot_history) <= 2
    assert [item.create_time for item in controller.screenshot_history] == [140.0]


def test_missing_frame_suspends_input_and_rejects_new_actions(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """画面过期后关掉输入，后来的普通攻击不能继续按键。"""
    controller._input_paused = False
    controller.window_capture.latest_frame.return_value = None
    assert controller.screenshot()[1] is None
    controller.gamepad.suspend.assert_called_once_with()
    with pytest.raises(RuntimeError, match='已暂停'):
        controller.normal_attack()
    controller.gamepad.tap.assert_not_called()


def test_frame_monitor_suspends_on_capture_failure(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """原始图仍存在，但缩放后无法得到有效内容帧时也要暂停长按。"""
    controller._input_paused = False
    controller.window_capture.latest_frame.return_value = None
    stop = Mock(spec=threading.Event)
    stop.wait.return_value = False
    controller._monitor_frames(stop)
    assert controller._input_paused is True
    controller.gamepad.suspend.assert_called_once_with()


def test_frame_monitor_stops_on_pause_and_cleanup(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """恢复时启动有限监测线程，暂停和重复清理不会留下线程。"""
    controller.resume_input()
    thread = controller._monitor_thread
    assert thread is not None and thread.is_alive()
    controller.pause_input()
    assert not thread.is_alive()
    assert controller._monitor_thread is None


@pytest.mark.parametrize('holding', [False, True])
def test_monitor_transient_gap_only_latches_pause_for_held_input(
    controller: zzz_macos_controller.ZMacController, holding: bool,
) -> None:
    """空闲回调抖动不锁死菜单，持杆时仍立即归零；过期新动作仍拒绝。"""
    controller._input_paused = False
    controller.gamepad.state = GamepadState(right_stick=(1.0, 0.0)) if holding else GamepadState()
    controller.window_capture.latest_frame.return_value = None
    stop = Mock(spec=threading.Event)
    stop.wait.side_effect = [False, True]
    controller._monitor_frames(stop)
    assert controller._input_paused is holding
    if holding:
        controller.gamepad.suspend.assert_called_once_with()
    else:
        controller.gamepad.suspend.assert_not_called()
        with pytest.raises(RuntimeError, match='没有有效'):
            controller.btn_tap('south')
        controller.gamepad.tap.assert_not_called()
    controller.cleanup_after_app_shutdown()
    controller.cleanup_after_app_shutdown()
    assert controller._monitor_thread is None


def test_battle_scope_blocks_result_inputs_and_keeps_releases_available(
    controller: zzz_macos_controller.ZMacController,
) -> None:
    """结算首帧归零，迟到的 X、组合键和摇杆动作均不能进入底层。"""
    controller._input_paused = False
    hud_check = Mock(return_value=True)
    controller.begin_battle_input_scope(hud_check)
    controller.normal_attack()
    controller.gamepad.tap.assert_called_once_with('xbox_x')
    controller.gamepad.reset_mock()

    hud_check.return_value = False
    frame = controller.window_capture.latest_frame.return_value
    controller.window_capture.latest_frame.return_value = replace(frame, sequence=2)
    controller.normal_attack()
    controller.btn_press('xbox_x', 0.3)
    assert controller.click(gamepad_key='compendium') is False
    controller.macos_config.turn_degrees_per_second = 90
    controller.turn_by_angle_diff(45)
    controller.normal_attack(release=True)

    assert controller.battle_input_blocked is True
    assert controller._input_paused is True
    controller.gamepad.suspend.assert_called_once_with()
    controller.gamepad.tap.assert_not_called()
    controller.gamepad.press.assert_not_called()
    controller.gamepad.tap_combo.assert_not_called()
    controller.gamepad.set_stick.assert_not_called()
    controller.gamepad.release.assert_called_once_with('xbox_x')


def test_battle_scope_monitor_cancels_hold_and_requires_explicit_refresh(
    controller: zzz_macos_controller.ZMacController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """过场暂停长按，HUD 回来前不恢复，回来后也必须由业务显式复核。"""
    controller._input_paused = False
    hud_check = Mock(return_value=True)
    controller.begin_battle_input_scope(hud_check)
    controller.normal_attack(press=True)
    hud_check.return_value = False
    frame = controller.window_capture.latest_frame.return_value
    controller.window_capture.latest_frame.return_value = replace(frame, sequence=2)
    stop = Mock(spec=threading.Event)
    stop.wait.return_value = False
    controller._monitor_frames(stop)

    assert controller.battle_input_blocked is True
    controller.gamepad.suspend.assert_called_once_with()
    assert controller.refresh_battle_input_scope() is False
    hud_check.return_value = True
    controller.window_capture.latest_frame.return_value = replace(frame, sequence=3)
    controller.gamepad.reset_mock()
    controller.normal_attack()
    controller.gamepad.tap.assert_not_called()
    monkeypatch.setattr(controller, '_start_frame_monitor', Mock())
    assert controller.refresh_battle_input_scope() is True
    assert controller.battle_input_blocked is False
    controller.normal_attack()
    controller.gamepad.resume.assert_called_once_with()
    controller.gamepad.tap.assert_called_once_with('xbox_x')


def test_battle_scope_rejects_non_battle_start_and_requires_menu_resume(
    controller: zzz_macos_controller.ZMacController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非战斗不允许开场，退出单场限制仍暂停，菜单按键须显式恢复。"""
    controller._input_paused = False
    with pytest.raises(RuntimeError, match='未识别到战斗标识'):
        controller.begin_battle_input_scope(lambda image: False)
    assert controller._battle_input_scope is None
    assert controller._input_paused is True
    with pytest.raises(RuntimeError, match='已暂停'):
        controller.btn_press('xbox_b', 0.2)
    monkeypatch.setattr(controller, '_start_frame_monitor', Mock())
    controller.resume_input()
    controller.begin_battle_input_scope(lambda image: True)
    controller.end_battle_input_scope()
    assert controller._input_paused is True
    controller.resume_input()
    controller.btn_press('xbox_b', 0.2)
    controller.gamepad.press.assert_called_once_with('xbox_b', 0.2)


def test_macos_config_roundtrip_keeps_cli_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """实例配置可重新读取，CLI 链接名与普通路径值原样保存。"""
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    config = MacOsConfig(1)
    config.ojd_cli_path = '/应用/ojd'
    config.bundle_id = 'test.game'
    config.capture_fps = 20
    config.max_frame_age_seconds = 0.8
    restored = MacOsConfig(1)
    assert restored.ojd_cli_path == '/应用/ojd'
    assert restored.bundle_id == 'test.game'
    assert restored.capture_fps == 20
    assert restored.max_frame_age_seconds == 0.8
    assert MacOsConfig(2).bundle_id == 'com.miHoYo.Nap'


@pytest.mark.parametrize('platform', ['PC', 'unknown'])
def test_darwin_rejects_other_platforms_without_windows_controller(
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 不偷偷迁移 PC 账号，也不会为未知平台加载 Windows 控制器。"""
    context = zzz_context.ZContext.__new__(zzz_context.ZContext)
    context.game_account_config = SimpleNamespace(platform=platform)
    context.controller = None
    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setitem(sys.modules, 'zzz_od.controller.zzz_pc_controller', None)
    with pytest.raises(RuntimeError, match='macos_playcover'):
        context.init_controller()
    assert context.game_account_config.platform == platform
    assert context.controller is None


def test_context_constructs_only_mac_controller(
    controller: zzz_macos_controller.ZMacController, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 Mac 账号使用新控制器，重复初始化同一配置不会重建。"""
    context = zzz_context.ZContext.__new__(zzz_context.ZContext)
    context.controller = None
    context.game_account_config = SimpleNamespace(platform=GamePlatformEnum.MACOS_PLAYCOVER.value.value)
    context.game_config = controller.game_config
    context.macos_config = controller.macos_config
    context.project_config = SimpleNamespace(screen_standard_width=1920, screen_standard_height=1080)
    created: list[object] = []

    class FakeMacController:
        """只记录构造，不连接任何设备。"""

        def __init__(self, game_config: GameConfig, macos_config: MacOsConfig,
                     standard_width: int, standard_height: int) -> None:
            """保存对象身份，用于判断重复初始化。"""
            self.game_config: GameConfig = game_config
            self.macos_config: MacOsConfig = macos_config
            created.append(self)

    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(zzz_macos_controller, 'ZMacController', FakeMacController)
    monkeypatch.setitem(sys.modules, 'zzz_od.controller.zzz_pc_controller', None)
    context.init_controller()
    context.init_controller()
    assert context.controller is created[0]
    assert len(created) == 1


def test_reload_releases_old_instance_and_refreshes_macos_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """实例刷新先停旧输入，再清除 Mac 配置缓存并重建控制器。"""
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='darwin'))
    context = zzz_context.ZContext.__new__(zzz_context.ZContext)
    old = Mock()
    context.controller = old
    context.run_context = Mock(is_context_stop=False)
    context.current_instance_idx = 2
    context.macos_config = MacOsConfig(1)
    context.game_config = object()
    context.init_controller = Mock()
    context.template_loader = SimpleNamespace(template={'old': object()})
    context.auto_battle_context = Mock(spec=['init_screen_area'])

    context.reload_instance_config()

    context.run_context.stop_running.assert_called_once_with()
    old.cleanup_after_app_shutdown.assert_called_once_with()
    assert context.controller is None
    assert 'game_config' not in context.__dict__
    assert context.macos_config.instance_idx == 2
    context.init_controller.assert_called_once_with()
    assert context.template_loader.template == {}
    context.auto_battle_context.init_screen_area.assert_called_once_with()
