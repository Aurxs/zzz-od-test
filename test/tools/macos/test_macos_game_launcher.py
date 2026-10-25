"""用假安装包、假进程和假窗口验证冷启动，不启动真实应用。"""

from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.controller.macos import macos_game_launcher
from one_dragon.base.controller.macos.macos_game_launcher import (
    MacGameLauncher,
    MacGameLaunchError,
)
from one_dragon.base.controller.macos.macos_window_capture import (
    MacWindow,
    MacWindowCapture,
)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """所有原生接口都替换为可观察的假对象。"""
    bundle = tmp_path / 'com.miHoYo.Nap.app'
    bundle.mkdir()
    with (bundle / 'Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleIdentifier': 'com.miHoYo.Nap', 'CFBundleExecutable': 'Nap'}, stream)
    (bundle / 'Nap').touch()
    window = MacWindow('com.miHoYo.Nap', 123, 456, '', 1920, 1136)
    app = Mock()
    app.processIdentifier.return_value = 123
    app.bundleIdentifier.return_value = 'com.miHoYo.Nap'
    app.isTerminated.return_value = False
    state = SimpleNamespace(apps=[], ready=False, seconds=0.0)
    capture = Mock(spec=MacWindowCapture)
    capture.list_windows.side_effect = lambda bundle_id: [window] if state.ready else []
    configuration = Mock()
    workspace = Mock()

    def open_app(url: str, config: object, completed: object) -> None:
        """只模拟系统完成回调，不启动进程。"""
        state.apps = [app]
        state.ready = True
        completed(app, None)

    workspace.openApplicationAtURL_configuration_completionHandler_.side_effect = open_app
    appkit = SimpleNamespace(
        NSRunningApplication=SimpleNamespace(
            runningApplicationsWithBundleIdentifier_=lambda bundle_id: state.apps,
        ),
        NSWorkspaceOpenConfiguration=SimpleNamespace(configuration=lambda: configuration),
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace),
    )
    foundation = SimpleNamespace(NSURL=SimpleNamespace(fileURLWithPath_=lambda path: path))
    monkeypatch.setattr(macos_game_launcher, '_launch_api', lambda: (appkit, foundation))
    monkeypatch.setattr(macos_game_launcher.time, 'monotonic', lambda: state.seconds)
    launcher = MacGameLauncher(capture, 'com.miHoYo.Nap', app_path=str(bundle), timeout_seconds=0.3)
    return SimpleNamespace(
        launcher=launcher, workspace=workspace, config=configuration,
        capture=capture, window=window, app=app, state=state, bundle=bundle,
    )


def test_cold_start_requests_once_and_marks_new_game(setup: SimpleNamespace) -> None:
    """身份匹配的安装包只请求一次，等待到精确进程的正常窗口。"""
    fake = setup
    assert fake.launcher.ensure_window() == fake.window
    assert fake.launcher.started_game
    fake.workspace.openApplicationAtURL_configuration_completionHandler_.assert_called_once()
    fake.config.setActivates_.assert_called_once_with(False)
    fake.config.setCreatesNewApplicationInstance_.assert_called_once_with(False)
    assert fake.launcher.ensure_window() == fake.window
    assert not fake.launcher.started_game
    assert fake.workspace.openApplicationAtURL_configuration_completionHandler_.call_count == 1


def test_existing_process_waits_without_relaunch(
    setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有进程但主窗口尚未出现，只等待，不重启或重新发送启动请求。"""
    fake = setup
    fake.state.apps = [fake.app]
    monkeypatch.setattr(fake.launcher, '_wait_tick', lambda: setattr(fake.state, 'ready', True))
    assert fake.launcher.ensure_window() == fake.window
    assert not fake.launcher.started_game
    fake.workspace.openApplicationAtURL_configuration_completionHandler_.assert_not_called()


def test_invalid_bundle_and_ambiguous_windows_never_launch(setup: SimpleNamespace) -> None:
    """安装包身份不符或同面积多个窗口均停止，保留系统进程。"""
    fake = setup
    with (fake.bundle / 'Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleIdentifier': 'other.bundle', 'CFBundleExecutable': 'Nap'}, stream)
    with pytest.raises(MacGameLaunchError, match='Bundle ID'):
        fake.launcher.ensure_window()
    fake.capture.list_windows.side_effect = None
    fake.capture.list_windows.return_value = [fake.window, fake.window]
    with pytest.raises(MacGameLaunchError, match='唯一'):
        fake.launcher.ensure_window()
    fake.workspace.openApplicationAtURL_configuration_completionHandler_.assert_not_called()


def test_timeout_is_bounded_and_does_not_retry_launch(
    setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """启动后一直无窗口，截止即失败，不重复启动也不假报已启动成功。"""
    fake = setup
    fake.workspace.openApplicationAtURL_configuration_completionHandler_.side_effect = None

    def tick() -> None:
        """推进假时钟，不实际等待。"""
        fake.state.seconds += 0.1

    monkeypatch.setattr(fake.launcher, '_wait_tick', tick)
    with pytest.raises(MacGameLaunchError, match='超时'):
        fake.launcher.ensure_window()
    assert not fake.launcher.started_game
    fake.workspace.openApplicationAtURL_configuration_completionHandler_.assert_called_once()
