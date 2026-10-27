"""验证 Mac 账户设置只在用户修改时保存连接配置。"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from one_dragon.base.config.game_account_config import (
    GameAccountConfig,
    GamePlatformEnum,
)
from one_dragon.base.config.yaml_config import YamlConfig
from zzz_od.config.game_config import GameConfig
from zzz_od.config.macos_config import MacOsConfig
from zzz_od.gui.view.setting import (
    setting_game_interface,
    setting_gamepad_interface,
    zzz_setting_instance_interface,
)
from zzz_od.macos.manual_gamepad import ManualGamepadSession


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    """由测试命令指定 offscreen，仅创建普通 Qt 控件。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[zzz_setting_instance_interface.ZSettingInstanceInterface, SimpleNamespace, Path]]:
    """使用真实配置和适配器，仅将配置文件路径放到临时目录。"""
    def config_paths(config: YamlConfig) -> tuple[str, str, None]:
        path = str(tmp_path / f'{config.module_name}.yml')
        return path, path, None

    monkeypatch.setattr(YamlConfig, '_get_yaml_file_paths', config_paths)
    monkeypatch.setattr(zzz_setting_instance_interface, 'sys', SimpleNamespace(platform='darwin'))
    account_path = tmp_path / 'game_account.yml'
    account_path.write_text(
        'game_path: C:/games/Zenless.exe\ngame_region: cn_b\naccount: existing\n',
        encoding='utf-8',
    )
    ctx = SimpleNamespace(
        game_account_config=GameAccountConfig(1), macos_config=MacOsConfig(1),
        env_config=SimpleNamespace(developer_mode=True),
        one_dragon_config=SimpleNamespace(
            instance_list=[], current_instance_force_login=False,
            set_current_instance_force_login=Mock(),
        ),
        run_context=SimpleNamespace(is_context_stop=False, stop_running=Mock()),
        controller=Mock(), ready_for_application=True, initialization_error=None,
        init_controller=Mock(), dispatch_event=Mock(),
    )
    interface = zzz_setting_instance_interface.ZSettingInstanceInterface(ctx)
    interface.on_interface_shown()
    for _ in range(3):
        qapp.processEvents()
    yield interface, ctx, account_path
    interface.close()


@pytest.fixture
def game_settings(
    qapp: QApplication,
    settings: tuple[zzz_setting_instance_interface.ZSettingInstanceInterface, SimpleNamespace, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path]]:
    """真实游戏设置页读取与账户页相同的当前账户配置。"""
    _, ctx, account_path = settings
    ctx.game_config = GameConfig(1)
    monkeypatch.setattr(setting_game_interface, 'sys', SimpleNamespace(platform='darwin'))
    interface = setting_game_interface.SettingGameInterface(ctx)
    interface.on_interface_shown()
    for _ in range(3):
        qapp.processEvents()
    yield interface, ctx, account_path
    interface.close()


def test_showing_macos_settings_keeps_default_pc_configuration(
    settings: tuple[zzz_setting_instance_interface.ZSettingInstanceInterface, SimpleNamespace, Path],
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
) -> None:
    """异步加载控件值后仍保留默认 PC，不创建 Mac 配置或清理连接。"""
    interface, ctx, account_path = settings
    assert account_path.read_text(encoding='utf-8') == (
        'game_path: C:/games/Zenless.exe\ngame_region: cn_b\naccount: existing\n'
    )
    assert ctx.game_account_config.platform == GamePlatformEnum.PC.value.value
    runtime = game_settings[0].macos_runtime_settings
    assert not hasattr(interface, 'platform_opt')
    assert not hasattr(interface, 'macos_menu_interval_opt')
    assert runtime.platform_opt.getValue() == GamePlatformEnum.PC.value.value
    assert runtime.macos_bundle_opt.getValue() == ctx.macos_config.bundle_id
    assert not hasattr(interface, 'macos_ojd_opt')
    assert not hasattr(interface, 'macos_gamepad_settings')
    assert ctx.macos_config.ojd_auto_start is False
    assert runtime.macos_top_inset_opt.spin_box.value() == 0
    assert runtime.macos_auto_top_inset_opt.btn.isChecked()
    assert not runtime.macos_top_inset_opt.isEnabled()
    assert not runtime.macos_top_inset_points_opt.isEnabled()
    assert not (account_path.parent / 'macos.yml').exists()
    assert ctx.ready_for_application is True
    ctx.run_context.stop_running.assert_not_called()
    ctx.controller.cleanup_after_app_shutdown.assert_not_called()
    ctx.init_controller.assert_not_called()
    ctx.dispatch_event.assert_not_called()


def test_user_selecting_macos_saves_platform_and_cleans_old_controller(
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
) -> None:
    """通过下拉框主动选 Mac 才落盘，并停用原连接以等待重新启动。"""
    game_interface, ctx, _ = game_settings
    interface = game_interface.macos_runtime_settings
    old_controller = ctx.controller
    value = GamePlatformEnum.MACOS_PLAYCOVER.value.value

    interface.platform_opt.combo_box.setCurrentIndex(
        interface.platform_opt.combo_box.findData(value),
    )

    saved = GameAccountConfig(1)
    assert saved.platform == value
    assert saved.account == 'existing'
    ctx.run_context.stop_running.assert_called_once_with()
    old_controller.cleanup_after_app_shutdown.assert_called_once_with()
    assert ctx.controller is None
    assert ctx.ready_for_application is False
    assert '重新启动' in ctx.initialization_error
    ctx.dispatch_event.assert_called_once()
    ctx.init_controller.assert_not_called()


def test_macos_hides_unused_controls_and_keeps_xbox_configuration(
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
    qapp: QApplication,
) -> None:
    """游戏页不再构造已迁走的手柄或无效Windows控件，旧配置不改写。"""
    interface, ctx, _ = game_settings
    ctx.game_config.data.update({
        'background_mode': True, 'background_gamepad_type': 'ds4', 'launch_argument': True,
        'key_normal_attack': 'j', 'ds4_key_normal_attack': 'ds4_circle',
    })
    original = dict(ctx.game_config.data)
    interface.on_interface_shown()
    interface.show()
    for _ in range(3):
        qapp.processEvents()
    for name in (
        'input_way_opt', 'hdr_btn', 'launch_argument_switch', 'screen_size_opt',
        'full_screen_opt', 'popup_window_switch', 'monitor_opt', 'launch_argument_advance',
        '_keyboard_group', 'background_mode_switch', 'background_gamepad_type_opt',
        'mouse_flash_duration_opt', '_xbox_cards', '_xbox_action_cards',
    ):
        assert not hasattr(interface, name)
    assert ctx.game_config.data == original
    ctx.run_context.stop_running.assert_not_called()
    ctx.controller.cleanup_after_app_shutdown.assert_not_called()
    ctx.dispatch_event.assert_not_called()
    ctx.init_controller.assert_not_called()


def test_macos_hides_windows_login_controls_in_developer_mode(
    qapp: QApplication,
    settings: tuple[zzz_setting_instance_interface.ZSettingInstanceInterface, SimpleNamespace, Path],
) -> None:
    """切换区服和刷新开发者可见性也不会恢复 Windows 登录控件。"""
    interface, _, _ = settings
    interface.show()
    interface.set_ui_of_game_region('cn')
    interface._update_developer_visibility()
    qapp.processEvents()

    for control in (
        interface.game_path_opt, interface.custom_win_title_opt, interface.game_region_opt,
        interface.game_account_opt, interface.game_password_opt, interface.help_bilibili_opt,
        interface.bilibili_account_name, interface.force_login_opt,
    ):
        assert control.isHidden()
    assert interface._account_settings_group.isHidden()
    assert not hasattr(interface, 'platform_opt')
    assert not hasattr(interface, 'macos_bundle_opt')


def test_gamepad_settings_preserve_application_readiness(
    qapp: QApplication,
    settings: tuple[zzz_setting_instance_interface.ZSettingInstanceInterface, SimpleNamespace, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """手柄设置移到独立二级页，修改参数后仍能使用准备游戏。"""
    _, ctx, _ = settings
    ctx.game_config = GameConfig(1)
    ctx.run_context.current_app_id = None
    ctx.manual_gamepad = ManualGamepadSession(ctx)
    interface = setting_gamepad_interface.SettingGamepadInterface(ctx)
    interface.on_interface_shown()
    for _ in range(3):
        qapp.processEvents()
    assert interface.macos_gamepad_settings.path.getValue() == ctx.macos_config.ojd_cli_path
    old_controller = ctx.controller
    interface.macos_gamepad_settings.auto_start.btn.setChecked(True)
    assert ctx.macos_config.ojd_auto_start is True
    assert ctx.ready_for_application is True
    assert ctx.initialization_error is None
    old_controller.cleanup_after_app_shutdown.assert_called_once_with()
    ctx.init_controller.assert_called_once_with()
    interface.close()


def test_menu_interval_setting_saves_without_reconnecting(
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
) -> None:
    """界面等待配置即时保存，不断开手柄与采集。"""
    game_interface, ctx, _ = game_settings
    interface = game_interface.macos_runtime_settings
    assert interface.macos_menu_interval_opt.spin_box.value() == 500
    interface.macos_menu_interval_opt.spin_box.setValue(800)
    assert MacOsConfig(1).menu_action_interval_ms == 800
    ctx.run_context.stop_running.assert_not_called()
    ctx.controller.cleanup_after_app_shutdown.assert_not_called()


def test_auto_capture_switch_preserves_manual_values_and_disconnects(
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
    qapp: QApplication,
) -> None:
    """默认自动且保留旧值，关闭后启用手动输入，沿用原连接清理。"""
    game_interface, ctx, _ = game_settings
    ctx.macos_config.capture_top_inset_points = 28
    ctx.macos_config.capture_top_inset_pixels = 56
    runtime = game_interface.macos_runtime_settings
    runtime.reload()
    for _ in range(3):
        qapp.processEvents()
    old_controller = ctx.controller
    runtime.macos_auto_top_inset_opt.btn.setChecked(False)
    saved = MacOsConfig(1)
    assert saved.capture_auto_top_inset is False
    assert (saved.capture_top_inset_points, saved.capture_top_inset_pixels) == (28, 56)
    assert runtime.macos_top_inset_opt.isEnabled()
    assert runtime.macos_top_inset_points_opt.isEnabled()
    old_controller.cleanup_after_app_shutdown.assert_called_once_with()
    ctx.run_context.stop_running.assert_called_once_with()
    assert ctx.controller is None


def test_runtime_settings_rebind_current_account(
    game_settings: tuple[setting_game_interface.SettingGameInterface, SimpleNamespace, Path],
    qapp: QApplication, tmp_path: Path,
) -> None:
    """切换账户再打开设置后，控件读取并写入新账户而不是旧适配器。"""
    interface, ctx, _ = game_settings
    original = ctx.macos_config
    replacement = MacOsConfig(2)
    replacement.file_path = str(tmp_path / 'second-macos.yml')
    replacement.data = {}
    replacement.menu_action_interval_ms = 1200
    replacement.capture_top_inset_pixels = 42
    replacement.capture_auto_top_inset = False
    ctx.macos_config = replacement
    interface.on_interface_shown()
    for _ in range(3):
        qapp.processEvents()
    runtime = interface.macos_runtime_settings
    assert runtime.macos_menu_interval_opt.spin_box.value() == 1200
    assert runtime.macos_top_inset_opt.spin_box.value() == 42
    assert not runtime.macos_auto_top_inset_opt.btn.isChecked()
    assert runtime.macos_top_inset_opt.isEnabled()
    runtime.macos_menu_interval_opt.spin_box.setValue(900)
    assert replacement.menu_action_interval_ms == 900
    assert original.menu_action_interval_ms == 500
    ctx.run_context.stop_running.assert_not_called()
