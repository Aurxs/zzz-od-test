"""验证开发 .app 的路径与元数据，不编译或启动实际应用。"""

from __future__ import annotations

import importlib.util
import json
import plistlib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def dev_app_tool() -> ModuleType:
    """直接加载只依赖标准库的开发工具。"""
    path = Path(__file__).resolve().parents[4] / 'tools' / 'macos' / 'create_dev_app.py'
    spec = importlib.util.spec_from_file_location('create_dev_app', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_escapes_paths_and_keeps_native_process(dev_app_tool: ModuleType) -> None:
    """空格、引号、反斜线与中文进入 C 字符串，不交给 shell 解析。"""
    path = Path('/tmp/开发 repo "quote" \\ slash $HOME')
    source = dev_app_tool.launcher_source(path)
    assert f'chdir({json.dumps(str(path), ensure_ascii=False)})' in source
    assert json.dumps(str(path / '.venv' / 'bin' / 'python'), ensure_ascii=False) in source
    assert 'Py_InitializeFromConfig' in source
    assert 'Py_RunMain' in source
    assert 'exec(' not in source


def test_generated_bundle_has_explicit_identity_and_exact_python_paths(
    dev_app_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只模拟解释器查询和编译，生成明确的 Bundle ID 与原生启动路径。"""
    repo = tmp_path / "repo with 'quotes'"
    python = repo / '.venv' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.touch()
    entry = repo / 'src' / 'zzz_od' / 'macos' / 'main.py'
    entry.parent.mkdir(parents=True)
    entry.touch()
    include = tmp_path / 'Python headers'
    include.mkdir()
    (include / 'Python.h').touch()
    library = tmp_path / 'Python libraries' / 'libpython3.11.dylib'
    library.parent.mkdir()
    library.touch()
    commands: list[list[str]] = []

    def run(command: list[str], *, check: bool, capture_output: bool = False, text: bool = False) -> SimpleNamespace:
        """编译只创建假文件，禁止启动 GUI。"""
        commands.append(command)
        if command[0] == str(python):
            return SimpleNamespace(stdout=json.dumps({
                'include': str(include), 'libdir': str(library.parent), 'library': library.name,
            }))
        assert command[:2] == ['xcrun', 'clang']
        Path(command[command.index('-o') + 1]).write_bytes(b'fake native executable')
        return SimpleNamespace()

    monkeypatch.setattr(dev_app_tool.subprocess, 'run', run)
    bundle = dev_app_tool.create_dev_app(repo)
    with (bundle / 'Contents' / 'Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleIdentifier'] == 'io.onedragon.zzz.macos.dev'
    assert info['CFBundleExecutable'] == 'OneDragonDev'
    assert info['CFBundlePackageType'] == 'APPL'
    executable = bundle / 'Contents' / 'MacOS' / info['CFBundleExecutable']
    assert executable.stat().st_mode & 0o111
    assert commands[0][0] == str(python)
    assert str(library) in commands[1]
    assert len(commands) == 2
