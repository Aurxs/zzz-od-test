"""启动点击只用假窗口和假 Quartz 验证，不发送实机输入。"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.controller.macos import macos_bootstrap_pointer
from one_dragon.base.controller.macos.macos_bootstrap_pointer import (
    MacBootstrapError,
    MacBootstrapPointer,
    MacBootstrapWindow,
    game_point_to_screen,
)
from one_dragon.base.controller.macos.macos_window_capture import (
    MacWindow,
    MacWindowCapture,
)


def test_retina_title_bar_and_current_window_position() -> None:
    """56 像素标题栏按当前 Retina 比例换成 28 点，允许副屏负坐标。"""
    window = MacWindow('game.bundle', 123, 456, '游戏', 1920, 1136)
    current = MacBootstrapWindow('game.bundle', 123, 456, -200, 50, 960, 568, 2)
    assert game_point_to_screen(window, current, 960, 540, top_inset_pixels=56) == (
        280,
        348,
    )
    assert game_point_to_screen(window, current, 0, 0, top_inset_pixels=56) == (
        -200,
        78,
    )
    resized = replace(
        current, left=100, top=200, width=1920, height=1136, pixels_per_point=1
    )
    assert game_point_to_screen(window, resized, 960, 540, top_inset_pixels=56) == (
        1060,
        796,
    )


def test_reject_changed_identity_invalid_coordinates_and_aspect() -> None:
    """身份、范围、尺寸或标题栏不明确时停止，不能补猜测值。"""
    window = MacWindow('game.bundle', 123, 456, '游戏', 960, 568)
    current = MacBootstrapWindow('game.bundle', 123, 456, 0, 0, 960, 568, 2)
    for changed in (
        replace(current, bundle_id='other.bundle'),
        replace(current, pid=124),
        replace(current, window_id=457),
    ):
        with pytest.raises(MacBootstrapError, match='身份'):
            game_point_to_screen(window, changed, 100, 100, top_inset_pixels=56)
    for x, y in ((-1, 0), (1920, 0), (0, 1080), (float('nan'), 0), (0, float('inf'))):
        with pytest.raises(MacBootstrapError, match='范围'):
            game_point_to_screen(window, current, x, y, top_inset_pixels=56)
    for changed, inset, message in (
        (current, 0, '16:9'),
        (current, 1136, '16:9'),
        (replace(current, pixels_per_point=0), 56, '比例无效'),
        (replace(current, on_screen=False), 56, '不在屏幕'),
    ):
        with pytest.raises(MacBootstrapError, match=message):
            game_point_to_screen(window, changed, 100, 100, top_inset_pixels=inset)
    with pytest.raises(ValueError, match='PID'):
        MacBootstrapPointer(replace(window, pid=0))


def test_native_click_refreshes_bounds_posts_only_to_pid_and_checks_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """移动窗口后重新读取边界，权限或窗口消失时拒绝输入，不走全局鼠标。"""
    bounds = {'X': 100.0, 'Y': 50.0, 'Width': 960.0, 'Height': 568.0}

    def frame() -> SimpleNamespace:
        """由当前假边界生成同一窗口的 SCK 帧信息。"""
        return SimpleNamespace(
            origin=SimpleNamespace(x=bounds['X'], y=bounds['Y']),
            size=SimpleNamespace(width=bounds['Width'], height=bounds['Height']),
        )

    app = Mock()
    app.bundleIdentifier.return_value = 'game.bundle'
    app.processID.return_value = 123
    candidate = Mock()
    candidate.owningApplication.return_value = app
    candidate.windowID.return_value = 456
    candidate.isOnScreen.return_value = True
    candidate.frame.side_effect = frame
    capture = Mock(spec=MacWindowCapture)
    capture._shareable_windows.return_value = [candidate]
    content_filter = Mock()
    content_filter.contentRect.side_effect = frame
    content_filter.pointPixelScale.return_value = 2
    sck = Mock()
    sck.SCContentFilter.alloc.return_value.initWithDesktopIndependentWindow_.return_value = content_filter
    quartz = SimpleNamespace(
        kCGWindowListOptionIncludingWindow=8,
        kCGWindowNumber='id',
        kCGWindowOwnerPID='pid',
        kCGWindowIsOnscreen='on_screen',
        kCGWindowLayer='layer',
        kCGWindowBounds='bounds',
        kCGEventSourceStatePrivate=-1,
        kCGMouseButtonLeft=0,
        kCGEventLeftMouseDown=1,
        kCGEventLeftMouseUp=2,
        kCGMouseEventClickState=1,
        kCGMouseEventWindowUnderMousePointer=91,
        kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent=92,
        CGWindowListCopyWindowInfo=Mock(
            return_value=[
                {
                    'id': 456,
                    'pid': 123,
                    'on_screen': True,
                    'layer': 0,
                    'bounds': bounds,
                }
            ]
        ),
        CGPreflightPostEventAccess=Mock(return_value=True),
        CGEventSourceCreate=Mock(return_value=object()),
        CGEventCreateMouseEvent=Mock(
            side_effect=lambda source, event_type, point, button: (event_type, point)
        ),
        CGEventSetFlags=Mock(),
        CGEventSetIntegerValueField=Mock(),
        CGEventPostToPid=Mock(),
        CGEventPost=Mock(side_effect=AssertionError('禁止全局投递')),
        CGWarpMouseCursorPosition=Mock(side_effect=AssertionError('禁止移动桌面光标')),
    )
    monkeypatch.setattr(
        macos_bootstrap_pointer,
        '_native_api',
        lambda: (None, None, None, quartz, sck, None),
    )
    monkeypatch.setattr(macos_bootstrap_pointer.time, 'sleep', Mock())
    pointer = MacBootstrapPointer(
        MacWindow('game.bundle', 123, 456, '游戏', 960, 568),
        top_inset_pixels=56,
        window_capture=capture,
    )
    assert pointer.resolve_point(960, 540) == (580, 348)
    quartz.CGEventPostToPid.assert_not_called()
    assert pointer.click(960, 540) is True
    bounds['X'] = 300
    assert pointer.click(960, 540) is True
    assert quartz.CGEventPostToPid.call_args_list == [
        ((123, (1, (580, 348))),),
        ((123, (2, (580, 348))),),
        ((123, (1, (780, 348))),),
        ((123, (2, (780, 348))),),
    ]
    assert capture._shareable_windows.call_count == 3
    for event in ((1, (580, 348)), (2, (580, 348)), (1, (780, 348)), (2, (780, 348))):
        quartz.CGEventSetIntegerValueField.assert_any_call(event, 91, 456)
        quartz.CGEventSetIntegerValueField.assert_any_call(event, 92, 456)
    quartz.CGPreflightPostEventAccess.return_value = False
    with pytest.raises(MacBootstrapError, match='辅助功能'):
        pointer.click(960, 540)
    quartz.CGPreflightPostEventAccess.return_value = True
    capture._shareable_windows.return_value = []
    with pytest.raises(MacBootstrapError, match='消失'):
        pointer.click(960, 540)
    assert quartz.CGEventPostToPid.call_count == 4
    quartz.CGEventPost.assert_not_called()
    quartz.CGWarpMouseCursorPosition.assert_not_called()
    app.activateWithOptions_.assert_not_called()


@pytest.fixture
def foreground_pointer(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """用明确的前台应用和鼠标状态模拟 AppKit / Quartz，不调用系统输入。"""
    previous = Mock()
    previous.processIdentifier.return_value = 77
    target = Mock()
    target.processIdentifier.return_value = 123
    target.bundleIdentifier.return_value = 'game.bundle'
    state = SimpleNamespace(front=previous, cursor=(20.0, 30.0))

    def activate(app: object) -> bool:
        """模拟一次准确的应用激活。"""
        state.front = app
        return True

    target.isActive.side_effect = lambda: state.front is target
    target.activateWithOptions_.side_effect = lambda options: activate(target)
    previous.activateWithOptions_.side_effect = lambda options: activate(previous)
    appkit = Mock()
    workspace = appkit.NSWorkspace.sharedWorkspace.return_value
    workspace.frontmostApplication.side_effect = lambda: state.front
    appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value = target
    appkit.NSApplicationActivateIgnoringOtherApps = 2

    def warp(point: tuple[float, float]) -> int:
        """仅记录假光标位置。"""
        state.cursor = point
        return 0

    quartz = SimpleNamespace(
        kCGEventSourceStatePrivate=-1, kCGMouseButtonLeft=0,
        kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2, kCGHIDEventTap=0,
        kCGMouseEventClickState=1, kCGMouseEventWindowUnderMousePointer=91,
        kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent=92,
        CGPreflightPostEventAccess=Mock(return_value=True),
        CGEventCreate=Mock(return_value=object()),
        CGEventGetLocation=Mock(side_effect=lambda event: SimpleNamespace(x=state.cursor[0], y=state.cursor[1])),
        CGWarpMouseCursorPosition=Mock(side_effect=warp),
        CGEventSourceCreate=Mock(return_value=object()),
        CGEventCreateMouseEvent=Mock(side_effect=lambda source, kind, point, button: (kind, point)),
        CGEventSetFlags=Mock(), CGEventSetIntegerValueField=Mock(),
        CGEventPost=Mock(), CGEventPostToPid=Mock(),
    )
    monkeypatch.setattr(macos_bootstrap_pointer, '_native_api', lambda: (None, None, None, quartz, None, None))
    monkeypatch.setattr(macos_bootstrap_pointer, '_foreground_api', lambda: appkit)
    monkeypatch.setattr(macos_bootstrap_pointer.time, 'sleep', Mock())
    pointer = MacBootstrapPointer(
        MacWindow('game.bundle', 123, 456, '游戏', 1920, 1080), foreground=True,
    )
    resolve = Mock(return_value=(580.0, 348.0))
    monkeypatch.setattr(pointer, 'resolve_point', resolve)
    return SimpleNamespace(
        pointer=pointer, quartz=quartz, previous=previous, target=target,
        state=state, resolve=resolve,
    )


@pytest.mark.parametrize('activation_accepted', [False, True])
def test_foreground_focus_failure_never_clicks_or_moves_cursor(
    foreground_pointer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    activation_accepted: bool,
) -> None:
    """激活被拒绝或一秒内未置前都不移动光标、也不发送事件。"""
    fake = foreground_pointer
    fake.target.activateWithOptions_.side_effect = None
    fake.target.activateWithOptions_.return_value = activation_accepted
    monkeypatch.setattr(macos_bootstrap_pointer.time, 'monotonic', Mock(side_effect=[0, 1.01]))
    with pytest.raises(MacBootstrapError, match='激活游戏|未成为前台'):
        fake.pointer.click(960, 540)
    fake.quartz.CGEventPost.assert_not_called()
    fake.quartz.CGWarpMouseCursorPosition.assert_not_called()
    fake.resolve.assert_not_called()
    fake.previous.activateWithOptions_.assert_not_called()


def test_foreground_exception_sends_up_and_restores_original_state(
    foreground_pointer: SimpleNamespace,
) -> None:
    """按下投递异常也只松开一次，并恢复未被用户改变的鼠标与焦点。"""
    fake = foreground_pointer

    def post(tap: int, event: tuple[int, tuple[float, float]]) -> None:
        """仅模拟按下投递出现异常。"""
        if event[0] == 1:
            raise RuntimeError('测试中的投递异常')

    fake.quartz.CGEventPost.side_effect = post
    with pytest.raises(RuntimeError, match='投递异常'):
        fake.pointer.click(960, 540)
    assert fake.quartz.CGEventPost.call_args_list == [
        call(0, (1, (580.0, 348.0))), call(0, (2, (580.0, 348.0))),
    ]
    assert fake.quartz.CGWarpMouseCursorPosition.call_args_list == [
        call((580.0, 348.0)), call((20.0, 30.0)),
    ]
    assert fake.state.front is fake.previous
    fake.quartz.CGEventPostToPid.assert_not_called()


def test_foreground_preserves_user_focus_and_pointer_changes(
    foreground_pointer: SimpleNamespace,
) -> None:
    """用户在事件处理期间切应用并移动鼠标，结束清理不覆盖新状态。"""
    fake = foreground_pointer
    user_app = Mock()
    user_app.processIdentifier.return_value = 88

    def post(tap: int, event: tuple[int, tuple[float, float]]) -> None:
        """模拟松开后用户立即操作别的应用。"""
        if event[0] == 2:
            fake.state.front = user_app
            fake.state.cursor = (700.0, 800.0)

    fake.quartz.CGEventPost.side_effect = post
    assert fake.pointer.click(960, 540) is True
    assert fake.state.front is user_app
    assert fake.state.cursor == (700.0, 800.0)
    fake.quartz.CGWarpMouseCursorPosition.assert_called_once_with((580.0, 348.0))
    fake.previous.activateWithOptions_.assert_not_called()
    assert fake.quartz.CGEventPost.call_count == 2


def test_activation_false_return_still_confirms_actual_foreground(
    foreground_pointer: SimpleNamespace,
) -> None:
    """系统请求返回 false 但精确目标已激活时，仍按实际焦点继续一次点击。"""
    fake = foreground_pointer

    def activate(options: int) -> bool:
        """模拟异步激活状态已更新但返回值仍为 false。"""
        fake.state.front = fake.target
        return False

    fake.target.activateWithOptions_.side_effect = activate
    assert fake.pointer.click(960, 540)
    assert fake.quartz.CGEventPost.call_count == 2
    assert fake.state.front is fake.previous


def test_worker_activation_and_restoration_are_dispatched_to_main_thread(
    foreground_pointer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GUI 工作线程只等待，游戏激活与原应用恢复均在主线程执行。"""
    fake = foreground_pointer
    pending: Queue[Callable[[], None]] = Queue()
    queue = SimpleNamespace(addOperationWithBlock_=pending.put)
    monkeypatch.setattr(macos_bootstrap_pointer, '_main_operation_queue', lambda: queue)
    main_thread = threading.get_ident()
    observed: list[int] = []

    def activate(app: object) -> bool:
        """记录实际发出激活请求的线程。"""
        observed.append(threading.get_ident())
        fake.state.front = app
        return False  # 以实际 active/PID 判断，恢复也不能只看返回值。

    fake.target.activateWithOptions_.side_effect = lambda options: activate(fake.target)
    fake.previous.activateWithOptions_.side_effect = lambda options: activate(fake.previous)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fake.pointer.click, 960, 540)
        for _ in range(2):
            pending.get(timeout=1)()
        assert future.result(timeout=1)
    assert observed == [main_thread, main_thread]
    assert fake.state.front is fake.previous
