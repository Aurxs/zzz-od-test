"""迷失之地出战开关与画面护栏，不执行真实挑战。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidDeploy


@pytest.mark.parametrize('prepare_only, ready, expected', [(True, True, False), (False, False, False), (False, True, True)])
def test_deploy_requires_explicit_run_and_both_preparation_anchors(
    monkeypatch: pytest.MonkeyPatch, prepare_only: bool, ready: bool, expected: bool,
) -> None:
    """默认只加载；真实出战必须显式关闭只准备并确认两个编队标识。"""
    ctx = SimpleNamespace(controller=Mock(spec=['btn_tap']), run_context=Mock())
    operation = GamepadLostVoidDeploy(ctx, 'Mac全配队通用', prepare_only=prepare_only)
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'round_by_find_area', lambda *args: (
        operation.round_success() if ready else operation.round_retry()
    ))
    result = operation.deploy()
    assert operation.ctx.controller.btn_tap.called is expected
    if expected:
        operation.ctx.controller.btn_tap.assert_called_once_with('start')
    if prepare_only:
        assert result.is_success and result.status == '仅准备模型，未出战'
