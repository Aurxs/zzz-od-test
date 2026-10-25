"""验证 Mac 上下文的监听清理与调试截图不会操作桌面输入。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation import one_dragon_context


def test_missing_button_listener_can_start_and_stop_repeatedly() -> None:
    """未创建监听器时，重复启动、关闭以及关闭后启动都安全。"""
    context = one_dragon_context.OneDragonContext.__new__(one_dragon_context.OneDragonContext)
    context.btn_listener = None
    context._btn_listener_started = False
    context._btn_listener_closed = False

    context._start_btn_listener()
    context._start_btn_listener()
    assert context._btn_listener_started is False

    context._stop_btn_listener()
    context._stop_btn_listener()
    context._start_btn_listener()
    assert context._btn_listener_closed is True
    assert context._btn_listener_started is False


def test_macos_debug_screenshot_does_not_access_windows_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 game_win 的 Mac 控制器仍可截图，不会激活游戏窗口。"""
    context = one_dragon_context.OneDragonContext.__new__(one_dragon_context.OneDragonContext)
    image = object()
    controller = Mock(spec=['is_game_window_ready', 'screenshot'])
    controller.is_game_window_ready = True
    controller.screenshot.return_value = (0, image)
    context.controller = controller
    patched_save = Mock()
    context._save_overlay_patched_image = patched_save
    save = Mock(return_value='macos-test')
    monkeypatch.setattr(one_dragon_context, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(one_dragon_context.debug_utils, 'save_debug_image', save)

    context.screenshot_and_save_debug(copy_screenshot=False)

    controller.screenshot.assert_called_once_with(independent=True)
    save.assert_called_once_with(image, copy_screenshot=False)
    patched_save.assert_called_once_with(image, 'macos-test')
