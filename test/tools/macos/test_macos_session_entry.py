"""用假会话验证平台入口和恢复，不连接游戏或发送输入。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.application_base import Application
from one_dragon.base.operation.operation import Operation
from zzz_od.application.one_dragon_app.zzz_one_dragon_app import ZOneDragonApp
from zzz_od.application.zzz_application import ZApplication
from zzz_od.operation.enter_game import game_session_entry
from zzz_od.operation.enter_game.mac_bootstrap_game_session import (
    MacBootstrapGameSession,
)
from zzz_od.operation.zzz_operation import ZOperation


@pytest.fixture
def context() -> SimpleNamespace:
    """提供就绪标志和严格限制接口的假控制器。"""
    return SimpleNamespace(
        controller=Mock(spec=['active_window', 'init_before_context_run']),
        is_game_window_ready=True,
        current_instance_idx=1,
        run_context=Mock(),
    )


def test_macos_imports_and_construction_do_not_load_windows_login() -> None:
    """独立进程禁止 Windows 登录和桌面输入依赖，覆盖三个公共入口。"""
    source_dir = Path(__file__).resolve().parents[4] / 'src'
    script = dedent('''
        import importlib.abc
        import mimetypes  # 先完成标准库对可选 winreg 的跨平台探测。
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock

        class RejectWindowsImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
                """Windows 登录依赖或桌面输入一经导入就让测试失败。"""
                forbidden = (
                    'winreg', 'win32', 'pynput', 'pyautogui',
                    'zzz_od.operation.enter_game.auto_hdr',
                    'zzz_od.operation.enter_game.open_game',
                    'zzz_od.operation.enter_game.open_and_enter_game',
                    'zzz_od.operation.enter_game.switch_account',
                )
                if fullname.startswith(forbidden):
                    raise AssertionError(f'Mac 入口加载了 Windows 依赖: {fullname}')
                return None

        sys.path.insert(0, sys.argv[1])
        sys.platform = 'darwin'
        sys.meta_path.insert(0, RejectWindowsImports())
        from zzz_od.application.zzz_application import ZApplication
        from zzz_od.application.one_dragon_app.zzz_one_dragon_app import ZOneDragonApp
        from zzz_od.operation.enter_game.mac_bootstrap_game_session import MacBootstrapGameSession
        from zzz_od.operation.zzz_operation import ZOperation

        ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=1)
        for op in (ZApplication(ctx, 'test'), ZOperation(ctx), ZOneDragonApp(ctx)):
            assert isinstance(op.op_to_enter_game, MacBootstrapGameSession)
        ctx.controller.init_before_context_run.assert_not_called()
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script, str(source_dir)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('operation_type', [ZApplication, ZOperation, ZOneDragonApp])
def test_windows_entries_keep_original_operations(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    operation_type: type[Operation],
) -> None:
    """Windows 仍构造原登录和换号操作，入口构造不会初始化控制器。"""
    open_entry = Mock(return_value=Mock(spec=Operation))
    switch_entry = Mock(return_value=Mock(spec=Operation))
    monkeypatch.setattr(game_session_entry, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setitem(sys.modules, 'zzz_od.operation.enter_game.open_and_enter_game',
                        SimpleNamespace(OpenAndEnterGame=open_entry))
    monkeypatch.setitem(sys.modules, 'zzz_od.operation.enter_game.switch_account',
                        SimpleNamespace(SwitchAccount=switch_entry))

    if operation_type is ZApplication:
        operation = ZApplication(context, 'test')
    else:
        operation = operation_type(context)

    assert operation.op_to_enter_game is open_entry.return_value
    open_entry.assert_called_once_with(context)
    if operation_type is ZOneDragonApp:
        assert operation._op_to_switch_account is switch_entry.return_value
        switch_entry.assert_called_once_with(context)
    else:
        switch_entry.assert_not_called()
    context.controller.init_before_context_run.assert_not_called()


@pytest.mark.parametrize('window_ready', [False, True])
def test_macos_entry_construction_does_not_send_input(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    window_ready: bool,
) -> None:
    """构造统一准备入口不触发窗口采集或输入，窗口存在不代表已确认手柄。"""
    monkeypatch.setattr(game_session_entry, 'sys', SimpleNamespace(platform='darwin'))
    context.is_game_window_ready = window_ready
    operation = ZOperation(context)

    assert isinstance(operation.op_to_enter_game, MacBootstrapGameSession)
    assert operation.check_game_window().is_success is window_ready
    if not window_ready:
        result = operation.op_to_enter_game.prepare_session()
        assert result.is_fail
        assert '打开游戏' in result.status
    context.controller.assert_not_called()
    assert context.controller.mock_calls == []


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_resume_only_activates_windows_window(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
    platform: str,
) -> None:
    """恢复总会委托框架，只有 Windows 激活窗口且不重复初始化输入。"""
    monkeypatch.setattr(game_session_entry, 'sys', SimpleNamespace(platform=platform))
    framework_resume = Mock()
    monkeypatch.setattr(Application, 'handle_resume', framework_resume)
    application = ZApplication(context, 'test', op_to_enter_game=Mock(spec=Operation))

    application.handle_resume()

    framework_resume.assert_called_once_with(application)
    assert context.controller.active_window.call_count == (0 if platform == 'darwin' else 1)
    context.controller.init_before_context_run.assert_not_called()


def test_custom_application_entry_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
) -> None:
    """调用方传入的入口不被平台默认入口覆盖。"""
    monkeypatch.setattr(game_session_entry, 'sys', SimpleNamespace(platform='darwin'))
    entry = Mock(spec=Operation)

    application = ZApplication(context, 'test', op_to_enter_game=entry)

    assert application.op_to_enter_game is entry
