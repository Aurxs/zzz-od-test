"""用内存帧验证 macOS 像素转换与帧过期，不申请采屏权限。"""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.controller.macos import macos_window_capture
from one_dragon.base.controller.macos.sck_frame_converter import (
    CapturedFrame,
    bgra_buffer_to_rgb,
    capture_timestamps,
    normalize_game_frame,
)


@pytest.mark.parametrize('existing_application, policy_result', [(False, True), (False, False), (True, True)])
def test_appkit_initialization_preserves_qt_application(existing_application: bool, policy_result: bool) -> None:
    """仅为无 NSApp 的 CLI 建立后台环境，不改变已有 Qt 应用。"""
    application = Mock()
    application.setActivationPolicy_.return_value = policy_result
    appkit = SimpleNamespace(
        NSApp=lambda: application if existing_application else None,
        NSApplication=SimpleNamespace(sharedApplication=Mock(return_value=application)),
        NSApplicationActivationPolicyProhibited=2,
    )
    macos_window_capture._initialize_appkit(appkit)
    if existing_application:
        appkit.NSApplication.sharedApplication.assert_not_called()
        application.setActivationPolicy_.assert_not_called()
    else:
        appkit.NSApplication.sharedApplication.assert_called_once_with()
        application.setActivationPolicy_.assert_called_once_with(2)


def test_bgra_stride_retina_crop_and_buffer_lifetime() -> None:
    """忽略行尾填充，按 Retina 点坐标裁剪，返回数据不借用原生缓冲。"""
    storage = np.zeros((6, 48), dtype=np.uint8)
    bgra = storage[:, :40].reshape(6, 10, 4)
    bgra[1:5, 2:10] = (10, 20, 30, 255)
    result = bgra_buffer_to_rgb(
        storage, 10, 6, 48,
        content_rect=(1, 0.5, 4, 2), scale_factor=2,
    )
    storage.fill(0)
    assert result.shape == (4, 8, 3)
    assert result.dtype == np.uint8
    assert np.all(result == (30, 20, 10))


def test_reject_out_of_bounds_content_rect() -> None:
    """元数据内容区超出缓冲时明确失败，不能读取错误像素。"""
    with pytest.raises(ValueError, match='超出'):
        bgra_buffer_to_rgb(bytes(16), 2, 2, 8, content_rect=(0, 0, 3, 2))


def test_normalize_requires_explicit_16_by_9_content() -> None:
    """16:10 窗口不能拉伸；明确裁掉装饰后的 16:9 游戏区可以转 1080p。"""
    image = np.full((90, 144, 3), (10, 20, 30), dtype=np.uint8)
    with pytest.raises(ValueError, match='16:9'):
        normalize_game_frame(image)
    result = normalize_game_frame(image, content_rect=(0, 9, 144, 81))
    assert result.shape == (1080, 1920, 3)
    assert np.all(result == (10, 20, 30))


def test_top_inset_removes_confirmed_title_bar() -> None:
    """完整 1920×1136 图片去掉 56 像素标题栏后保留完整游戏内容。"""
    image = np.full((1136, 1920, 3), (10, 20, 30), dtype=np.uint8)
    image[:56] = 200
    result = normalize_game_frame(image, top_inset_pixels=56)
    assert result.shape == (1080, 1920, 3)
    assert np.all(result == (10, 20, 30))
    assert np.all(image[:56] == 200)


def test_top_inset_rejects_resized_non_16_by_9_window() -> None:
    """窗口变宽后检查剩余整张游戏区，不固定裁掉右边来凑 16:9。"""
    image = np.zeros((1136, 2000, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match='2000×1080'):
        normalize_game_frame(image, top_inset_pixels=56)


@pytest.mark.parametrize('top_inset_pixels, content_rect, message', [
    (-1, None, '非负整数'),
    (56, (0, 56, 1920, 1080), '不能同时'),
])
def test_top_inset_rejects_invalid_or_conflicting_parameters(
    top_inset_pixels: int,
    content_rect: tuple[int, int, int, int] | None,
    message: str,
) -> None:
    """非法裁剪在转换和启动入口都被拒绝，不能触发原生采集。"""
    image = np.zeros((1136, 1920, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match=message):
        normalize_game_frame(image, content_rect=content_rect, top_inset_pixels=top_inset_pixels)
    capture = macos_window_capture.MacWindowCapture()
    window = macos_window_capture.MacWindow('game.bundle', 1, 2, '游戏', 960, 568)
    with pytest.raises(ValueError, match=message):
        capture.start(window, content_rect=content_rect, top_inset_pixels=top_inset_pixels)


def test_capture_timestamp_uses_source_age() -> None:
    """host 时间换算保留回调前的帧龄，不能用读帧时间刷新旧画面。"""
    epoch, monotonic = capture_timestamps(
        100, 150, 20, epoch_now=1000, monotonic_now=50,
    )
    assert epoch == 997.5
    assert monotonic == 47.5
    with pytest.raises(ValueError, match='晚于'):
        capture_timestamps(150, 100, 20, epoch_now=1000, monotonic_now=50)


def test_latest_frame_expiry_stop_and_old_stream_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """过期与停止后不返回旧帧，旧窗口的停止通知不能清掉新窗口。"""
    class FakeStream:
        """只模拟停止完成通知，不创建原生采集对象。"""

        def stopCaptureWithCompletionHandler_(self, completion: Callable[[object], None]) -> None:
            """同步完成假停止，使测试不依赖 Cocoa 主循环。"""
            completion(None)

    monkeypatch.setattr(macos_window_capture, '_native_api', lambda: (None,) * 6)
    monkeypatch.setattr(macos_window_capture.time, 'monotonic', lambda: 100)
    capture = macos_window_capture.MacWindowCapture()
    stream = FakeStream()
    capture._stream = stream
    capture._running = True
    capture._latest = CapturedFrame(np.zeros((9, 16, 3), dtype=np.uint8), 7, 1000, 99.75, 16, 9)

    capture._fail_stream(object(), '旧窗口已停止')
    frame = capture.latest_frame(max_age_seconds=0.5)
    assert frame is not None and frame.image.shape == (1080, 1920, 3)
    assert (frame.sequence, frame.capture_time, frame.monotonic_time) == (7, 1000, 99.75)
    assert (frame.raw_width, frame.raw_height) == (16, 9)
    assert capture.latest_frame(max_age_seconds=0.1) is None
    assert '过期' in capture.last_error

    capture.stop()
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert capture.window is None
