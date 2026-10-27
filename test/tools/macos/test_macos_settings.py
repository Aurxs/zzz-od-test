"""验证设置页面隔离 Windows 功能，且不改写用户配置。"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QWidget

from one_dragon_qt.view.setting import (
    setting_custom_interface,
    setting_env_interface,
    setting_push_interface,
)
from zzz_od.gui.view.setting import app_setting_interface


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    """由测试命令使用 offscreen 平台，不打开桌面窗口。"""
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_overlay_page_is_created_only_on_windows(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 保留普通设置页，Windows 仍按原顺序加入悬浮窗页。"""
    monkeypatch.setattr(app_setting_interface, 'sys', SimpleNamespace(platform=platform))
    overlay_widget = QWidget()
    overlay_widget.setObjectName('setting_overlay_interface')
    overlay_widget.nav_text = '悬浮窗'
    overlay_factory = Mock(return_value=overlay_widget)
    overlay_module = ModuleType('zzz_od.gui.view.setting.setting_overlay_interface')
    overlay_module.SettingOverlayInterface = overlay_factory
    monkeypatch.setitem(sys.modules, overlay_module.__name__, overlay_module)

    interface = app_setting_interface.AppSettingInterface(SimpleNamespace())
    names = [interface.stacked_widget.widget(i).objectName()
             for i in range(interface.stacked_widget.count())]
    expected = ['setting_game_interface', 'setting_env_interface',
                'setting_push_interface', 'setting_custom_interface']
    if platform == 'win32':
        expected.insert(1, 'setting_overlay_interface')
        overlay_factory.assert_called_once()
    else:
        expected.insert(1, 'setting_gamepad_interface')
        overlay_factory.assert_not_called()
    assert names == expected
    interface.close()


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_environment_settings_keep_windows_options_on_windows(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """平台专用控件及其配置只在 Windows 初始化，通用配置仍可读取。"""
    monkeypatch.setattr(setting_env_interface, 'sys', SimpleNamespace(platform=platform))
    env = SimpleNamespace(
        developer_mode=False, proxy_type='None', get_prop_adapter=Mock(return_value=None),
    )
    ctx = SimpleNamespace(
        env_config=env,
        repo_config=SimpleNamespace(get_source_options=lambda name: []),
        init_controller=Mock(), init_async=Mock(),
    )
    interface = setting_env_interface.SettingEnvInterface(ctx)
    interface.on_interface_shown()

    assert hasattr(interface, 'screenshot_method_opt') is (platform == 'win32')
    assert hasattr(interface, 'key_start_running_input') is (platform == 'win32')
    assert hasattr(interface, 'copy_screenshot_opt') is (platform == 'win32')
    config_keys = {call.args[0] for call in env.get_prop_adapter.call_args_list}
    windows_keys = {'screenshot_method', 'copy_screenshot', 'key_start_running',
                    'key_stop_running', 'key_screenshot', 'key_debug'}
    assert windows_keys <= config_keys if platform == 'win32' else not windows_keys & config_keys
    assert {'is_debug', 'developer_mode', 'pip_source', 'proxy_type'} <= config_keys
    ctx.init_controller.assert_not_called()
    ctx.init_async.assert_not_called()
    interface.close()


def test_banner_picker_uses_qt_pictures_directory(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取消图片选择时不写文件，默认目录取自 Qt。"""
    picker = Mock(return_value=('', ''))
    monkeypatch.setattr(setting_custom_interface.QFileDialog, 'getOpenFileName', picker)
    interface = setting_custom_interface.SettingCustomInterface(SimpleNamespace())

    interface._on_banner_select_clicked()

    assert picker.call_args.args[2] == QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation,
    )
    interface.close()


def test_notification_command_uses_qt_clipboard(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主动复制命令使用 Qt，不访问系统剪贴板或 Windows 模块。"""
    clipboard = Mock()
    monkeypatch.setattr(setting_push_interface, 'QApplication', SimpleNamespace(
        clipboard=lambda: clipboard,
    ))
    ctx = SimpleNamespace(push_service=SimpleNamespace(
        get_channel_config=lambda name: {'URL': 'https://example.com/webhook'},
    ))
    interface = setting_push_interface.SettingPushInterface(ctx)
    interface._show_success_message = Mock()

    interface._generate_curl('unix')

    clipboard.setText.assert_called_once()
    assert 'https://example.com/webhook' in clipboard.setText.call_args.args[0]
    interface._show_success_message.assert_called_once()
    interface.close()
