"""Mac 双向镜头校准的最小行为检查，不连接游戏。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import LostVoidDetector
from zzz_od.operation.gamepad import lost_void_turn as module
from zzz_od.application.game_config_checker.mouse_sensitivity_checker.mouse_sensitivity_checker import MouseSensitivityChecker


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> module.GamepadLostVoidCalibrateTurn:
    ctx = SimpleNamespace(
        macos_config=SimpleNamespace(turn_distance_per_second=100.0, turn_stick_amplitude=1.0),
        controller=Mock(spec=['move_camera']),
        lost_void=SimpleNamespace(in_normal_world=Mock(return_value=True), detector=Mock()),
        run_context=SimpleNamespace(is_context_running=True),
    )
    operation = module.GamepadLostVoidCalibrateTurn(ctx, force=True)
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.last_screenshot_time = 100
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'save_screenshot', Mock())
    monkeypatch.setattr(module.gpu_executor, 'submit', lambda fn, *args, **kwargs: SimpleNamespace(result=lambda: fn(*args, **kwargs)))
    return operation


def targets(operation: module.GamepadLostVoidCalibrateTurn, positions: list[float]) -> None:
    operation.ctx.lost_void.detector.run.return_value = SimpleNamespace(results=[
        SimpleNamespace(center=(x, 300), detect_class=SimpleNamespace(class_name=LostVoidDetector.CLASS_INTERACT))
        for x in positions
    ])


def test_round_trip_saves_only_after_consistent_return(operation: module.GamepadLostVoidCalibrateTurn) -> None:
    for x in [1100, 950]:
        targets(operation, [x])
        assert not operation.calibrate().is_success
        assert operation.ctx.macos_config.turn_distance_per_second == 100
    targets(operation, [1090])
    result = operation.calibrate()
    assert result.is_success and result.data['round_trip_error'] == 10
    assert operation.ctx.macos_config.turn_distance_per_second == 906.2
    assert operation.ctx.macos_config.turn_stick_amplitude == 0.5
    assert operation.ctx.controller.move_camera.call_args_list == [
        call(0.5, 0, press_time=0.16), call(-0.5, 0, press_time=0.16),
    ]


def test_inconsistent_return_keeps_original_parameters(operation: module.GamepadLostVoidCalibrateTurn) -> None:
    for x in [1100, 950]:
        targets(operation, [x])
        operation.calibrate()
    targets(operation, [1000])
    assert operation.calibrate().is_fail
    assert operation.ctx.macos_config.turn_distance_per_second == 100
    assert operation.ctx.macos_config.turn_stick_amplitude == 1


def test_ambiguous_target_and_paused_run_send_no_input(operation: module.GamepadLostVoidCalibrateTurn) -> None:
    targets(operation, [500, 1300])
    assert not operation.calibrate().is_success
    targets(operation, [1100])
    operation.ctx.run_context.is_context_running = False
    assert operation.calibrate().is_fail
    operation.ctx.controller.move_camera.assert_not_called()


def test_existing_calibration_is_kept_without_force(operation: module.GamepadLostVoidCalibrateTurn) -> None:
    operation.force = False
    assert operation.calibrate().is_success
    operation.ctx.controller.move_camera.assert_not_called()


def test_original_app_calls_real_calibration_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """原 GUI 的实际首节点必须执行校准，不能仅返回完成状态。"""
    monkeypatch.setattr('zzz_od.application.game_config_checker.mouse_sensitivity_checker.mouse_sensitivity_checker.sys.platform', 'darwin')
    fake = Mock()
    fake.execute.return_value = SimpleNamespace(success=True, data={'distance_per_second': 900})
    monkeypatch.setattr(module, 'GamepadLostVoidCalibrateTurn', Mock(return_value=fake))
    operation = object.__new__(MouseSensitivityChecker)
    operation.ctx = object()
    operation.round_success = Mock()
    operation.back_at_first()
    fake.execute.assert_called_once_with()
    operation.round_success.assert_called_once_with('Mac校准已完成', data={'distance_per_second': 900})
