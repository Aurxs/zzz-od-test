"""验证后端 Mac 最小入口不依赖 Windows 剪贴板或桌面焦点。"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.backend import backend_context as backend_module


def test_macos_keys_and_text_do_not_use_desktop_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mac 只调用手柄控制器，非法输入和文本输入不产生动作。"""
    monkeypatch.setattr(backend_module, 'sys', SimpleNamespace(platform='darwin'))
    controller = Mock(spec=['is_game_window_ready', 'btn_tap', 'btn_press'])
    controller.is_game_window_ready = True
    backend = backend_module.ZzzBackendContext(
        SimpleNamespace(ready_for_application=True, controller=controller),
    )

    assert backend.key_tap('xbox_a')['success'] is True
    assert backend.key_tap('xbox_ls_up', 0.1)['success'] is True
    for duration in (-1, float('inf'), float('nan')):
        with pytest.raises(ValueError, match='非负秒数'):
            backend.key_tap('xbox_a', duration)
    with pytest.raises(ValueError, match='不支持的手柄按键'):
        backend.key_tap('w')
    with pytest.raises(NotImplementedError, match='暂不支持文本输入'):
        backend.input_text('示例文本', use_clipboard=True)

    controller.btn_tap.assert_called_once_with('xbox_a')
    controller.btn_press.assert_called_once_with('xbox_ls_up', press_time=0.1)


def test_macos_window_query_only_reads_bound_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """窗口状态来自已有采集窗口，未知位置保留 None。"""
    monkeypatch.setattr(backend_module, 'sys', SimpleNamespace(platform='darwin'))
    capture = SimpleNamespace(window=SimpleNamespace(title='绝区零', width=1920, height=1136))
    controller = SimpleNamespace(window_capture=capture, is_game_window_ready=True)
    backend = backend_module.ZzzBackendContext(
        SimpleNamespace(ready_for_application=True, controller=controller),
    )

    status = backend.check_window()

    assert status.win_title == '绝区零'
    assert status.is_win_valid is True
    assert (status.x, status.y, status.width, status.height) == (None, None, 1920, 1136)
    assert status.is_win_active is False
    assert status.is_win_scale is False
    capture.window = None
    with pytest.raises(backend_module.BackendNotReadyError, match='未初始化'):
        backend.check_window()


def test_windows_keys_and_text_keep_existing_input_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows 保留激活、按键控制器、逐键与剪贴板输入路径。"""
    monkeypatch.setattr(backend_module, 'sys', SimpleNamespace(platform='win32'))
    clipboard = Mock()
    monkeypatch.setitem(sys.modules, 'one_dragon.base.controller.pc_clipboard',
                        SimpleNamespace(PcClipboard=clipboard))
    controller = Mock(is_game_window_ready=True)
    backend = backend_module.ZzzBackendContext(
        SimpleNamespace(ready_for_application=True, controller=controller),
    )

    backend.key_tap('f')
    backend.key_tap('w', 0.1)
    assert backend.input_text('示例', use_clipboard=False)['method'] == 'keyboard'
    assert backend.input_text('示例', use_clipboard=True)['method'] == 'clipboard'

    assert controller.active_window.call_count == 4
    controller.btn_tap.assert_called_once_with('f')
    controller.btn_controller.press.assert_called_once_with('w', press_time=0.1)
    controller.input_str.assert_called_once_with('示例')
    clipboard.copy_and_paste.assert_called_once_with('示例')
