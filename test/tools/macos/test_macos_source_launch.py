"""验证 Mac 源码重启与资源检查，不启动进程或下载资源。"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.utils import app_utils
from one_dragon_qt.services import resource_update_coordinator


def test_macos_restart_uses_current_python_and_source_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当前 Python 从项目根目录重启，并保留原 PYTHONPATH。"""
    fake_sys = SimpleNamespace(platform='darwin', executable='/venv/bin/python', exit=Mock())
    monkeypatch.setattr(app_utils, 'sys', fake_sys)
    monkeypatch.setattr(app_utils.os_utils, 'get_work_dir', lambda: str(tmp_path))
    monkeypatch.setenv('PYTHONPATH', '/existing/modules')
    popen = Mock()
    version = Mock()
    monkeypatch.setattr(app_utils.subprocess, 'Popen', popen)
    monkeypatch.setattr(app_utils, 'get_exe_version', version)

    app_utils.start_one_dragon(restart=True)

    popen.assert_called_once()
    assert popen.call_args.args[0] == ['/venv/bin/python', '-m', 'zzz_od.macos.main']
    assert popen.call_args.kwargs['cwd'] == str(tmp_path)
    assert popen.call_args.kwargs['env']['PYTHONPATH'].split(os.pathsep) == [
        str(tmp_path / 'src'), '/existing/modules',
    ]
    assert 'creationflags' not in popen.call_args.kwargs
    fake_sys.exit.assert_called_once_with(0)
    assert app_utils.get_launcher_version() == ''
    version.assert_not_called()


def test_macos_resource_checks_skip_launcher_and_keep_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 Windows 更新服务时，模型检查仍注册并调用原模型检查方法。"""
    monkeypatch.setattr(resource_update_coordinator, 'sys', SimpleNamespace(platform='darwin'))
    needs_models = Mock(return_value=True)
    ctx = SimpleNamespace(model_config=SimpleNamespace(needs_model_download=needs_models))

    coordinator = resource_update_coordinator.ResourceUpdateCoordinator(
        ctx=ctx, queue=Mock(), window=Mock(), show_queue_added_tip=Mock(),
    )

    assert set(coordinator._resource_checks) == {'project_models'}
    assert set(coordinator._check_runners) == {'project_models'}
    assert coordinator._resource_checks['project_models'].check_update() is True
    needs_models.assert_called_once_with()
