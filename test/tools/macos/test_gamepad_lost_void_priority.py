"""藏品菜单首按未响应时，只在局内新帧确认后有限重试。"""
from types import SimpleNamespace
from unittest.mock import Mock, call

from zzz_od.operation.gamepad.lost_void_priority import GamepadLostVoidUpdatePriority


def priority_operation() -> GamepadLostVoidUpdatePriority:
    """不初始化设备，直接验证菜单输入边界。"""
    operation = object.__new__(GamepadLostVoidUpdatePriority)
    operation._opened = False
    operation._open_attempts = 0
    operation._open_frame_time = -1
    operation.last_screenshot = object()
    operation.last_screenshot_time = 1
    operation.ctx = SimpleNamespace(controller=Mock(), lost_void=SimpleNamespace(in_normal_world=Mock(return_value=True)))
    operation.navigation = SimpleNamespace(_read_area=Mock(return_value=None))
    operation.round_retry = Mock(return_value='wait')
    operation.save_screenshot = Mock()
    return operation


def test_menu_open_retries_once_after_three_seconds_of_new_world_frames() -> None:
    operation = priority_operation()
    for timestamp in (1, 1, 2, 3):
        operation.last_screenshot_time = timestamp
        assert operation.enter_collections() == 'wait'
    assert operation.ctx.controller.click.call_count == 1
    for timestamp in (4, 4, 8, 12):
        operation.last_screenshot_time = timestamp
        operation.enter_collections()
    assert operation.ctx.controller.click.call_args_list == [call(gamepad_key='minimap')] * 2
    operation.save_screenshot.assert_called_once()


def test_unknown_or_missing_frames_never_retry_menu_input() -> None:
    operation = priority_operation()
    operation.enter_collections()
    operation.last_screenshot_time = 5
    operation.ctx.lost_void.in_normal_world.return_value = False
    operation.enter_collections()
    operation.last_screenshot = None
    operation.enter_collections()
    assert operation.ctx.controller.click.call_count == 1
