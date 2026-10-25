"""验证公共导入不依赖桌面输入，以及调试图片的跨平台行为。"""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.utils import cv2_utils, debug_utils


def test_common_imports_without_pc_modules() -> None:
    """在独立进程中禁止系统输入模块，确认公共配置仍可导入。"""
    source_dir = Path(__file__).resolve().parents[4] / 'src'
    script = dedent('''
        import importlib.abc
        import sys

        class RejectPcImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
                """导入 Windows 或桌面输入模块时直接让测试失败。"""
                forbidden = (
                    'win32', 'pynput', 'pyautogui',
                    'one_dragon.base.controller.pc_button',
                    'zzz_od.controller.zzz_pc_controller',
                )
                if fullname.startswith(forbidden):
                    raise AssertionError(f'公共导入加载了系统输入模块: {fullname}')
                return None

        sys.path.insert(0, sys.argv[1])
        sys.meta_path.insert(0, RejectPcImports())
        from one_dragon.base.controller.gamepad_button import Ds4ButtonEnum, XboxButtonEnum
        from one_dragon.utils import debug_utils
        from zzz_od.config.game_config import _KEY_DEFAULTS
        from zzz_od.operation.turning.turn_compensation import AngleTurnCompensator

        assert _KEY_DEFAULTS['xbox_key']['normal_attack'] == XboxButtonEnum.X.value.value
        assert _KEY_DEFAULTS['ds4_key']['normal_attack'] == Ds4ButtonEnum.SQUARE.value.value
        assert callable(debug_utils.save_debug_image)
        assert callable(AngleTurnCompensator.turn)
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script, str(source_dir)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_save_debug_image_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mac 保存调试图片时保留 RGB 内容，剪贴板操作明确返回未支持。"""
    image = np.full((2, 2, 3), (10, 20, 30), dtype=np.uint8)
    path = tmp_path / 'image.png'
    monkeypatch.setattr(debug_utils, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(debug_utils, 'get_debug_image_path', lambda filename: str(path))

    assert debug_utils.save_debug_image(image, 'image', copy_screenshot=True) == 'image'
    assert np.array_equal(cv2_utils.read_image(str(path)), image)
    assert debug_utils.copy_image_to_clipboard(image) is False


@pytest.mark.parametrize('set_data_fails', [False, True])
def test_windows_clipboard_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    set_data_fails: bool,
) -> None:
    """Windows 仍写入 DIB，写入成功或失败后都会关闭剪贴板。"""
    clipboard = SimpleNamespace(
        OpenClipboard=Mock(),
        EmptyClipboard=Mock(),
        SetClipboardData=Mock(side_effect=RuntimeError('写入失败') if set_data_fails else None),
        CloseClipboard=Mock(),
    )
    monkeypatch.setattr(debug_utils, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setitem(sys.modules, 'win32clipboard', clipboard)
    monkeypatch.setitem(sys.modules, 'win32con', SimpleNamespace(CF_DIB=8))

    assert debug_utils.copy_image_to_clipboard(np.zeros((2, 2, 3), dtype=np.uint8)) is not set_data_fails
    clipboard.OpenClipboard.assert_called_once_with()
    clipboard.EmptyClipboard.assert_called_once_with()
    clipboard.CloseClipboard.assert_called_once_with()
    format_id, dib = clipboard.SetClipboardData.call_args.args
    assert format_id == 8
    assert dib[:4] == b'\x28\x00\x00\x00'
