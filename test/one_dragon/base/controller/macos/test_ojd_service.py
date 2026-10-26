"""验证固定官方组件的校验与安装，不访问网络、管理员授权或真实设备。"""

from __future__ import annotations

import hashlib
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from one_dragon.base.controller.macos import ojd_service


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[list[str]]]:
    """模拟系统命令的文件结果，签名校验仍经过生产代码。"""
    app = tmp_path / 'Applications' / 'OpenJoystickDriver.app'
    app.parent.mkdir()
    commands: list[list[str]] = []
    payload = b'official pinned disk image fixture'
    monkeypatch.setattr(ojd_service, 'OJD_APP', app)
    monkeypatch.setattr(ojd_service, 'OJD_SHA256', hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(ojd_service.os_utils, 'get_work_dir', lambda: str(tmp_path))

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        output = b''
        if command[0] == 'curl':
            Path(command[-1]).write_bytes(payload)
        elif command[:2] == ['hdiutil', 'attach']:
            mount = Path(command[command.index('-mountpoint') + 1])
            contents = mount / app.name / 'Contents'
            (contents / 'MacOS').mkdir(parents=True)
            (contents / 'MacOS' / 'OpenJoystickDriver').write_bytes(b'signed binary')
            (contents / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'com.openjoystickdriver',
                'CFBundleShortVersionString': ojd_service.OJD_VERSION,
            }))
        elif command[0] == '/usr/bin/ditto':
            shutil.copytree(command[1], command[2])
        elif command[0] == '/bin/mv':
            Path(command[-2]).rename(Path(command[-1]) / Path(command[-2]).name)
        elif command[0] == '/bin/rmdir':
            Path(command[-1]).rmdir()
        elif command[:2] == ['codesign', '-d']:
            output = plistlib.dumps({'com.apple.developer.hid.virtual.device': True})
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b'')

    monkeypatch.setattr(ojd_service.subprocess, 'run', run)
    return app, commands


def test_install_verifies_and_reuses_signed_bundle(installation: tuple[Path, list[list[str]]]) -> None:
    """下载只发生一次，复用不覆盖包，不启动服务或注册驱动。"""
    app, commands = installation
    link = ojd_service.install_ojd()
    assert link.name == 'ojd' and link.resolve() == app / 'Contents/MacOS/OpenJoystickDriver'
    assert ojd_service.install_ojd() == link
    assert sum(command[0] == 'curl' for command in commands) == 1
    assert sum(command[0] == '/usr/bin/ditto' for command in commands) == 1
    assert any(command[:2] == ['hdiutil', 'detach'] for command in commands)
    signing_checks = [command for command in commands if command[:2] == ['codesign', '--verify']]
    assert len(signing_checks) == 3
    assert all('9PQP6CDMQT' in command[command.index('-R') + 1] for command in signing_checks)
    assert any(command[0] == 'spctl' for command in commands)
    assert not any('service' in command or 'transport-extension' in command or '--sign' in command for command in commands)


def test_corrupt_download_is_never_mounted(installation: tuple[Path, list[list[str]]], monkeypatch: pytest.MonkeyPatch) -> None:
    """哈希不符时停止，不执行下载内容也不建立命令入口。"""
    app, commands = installation
    monkeypatch.setattr(ojd_service, 'OJD_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='下载校验失败'):
        ojd_service.install_ojd()
    assert not app.exists()
    assert not any(command[0] in ('hdiutil', 'codesign', '/usr/bin/ditto') for command in commands)
    assert not (app.parents[1] / '.install/ojd/ojd').exists()

