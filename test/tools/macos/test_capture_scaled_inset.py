"""标题栏逻辑点随帧缩放转换，旧像素配置与帧时间保持原语义。"""

from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.controller.macos import macos_window_capture
from one_dragon.base.controller.macos.macos_bootstrap_pointer import (
    MacBootstrapError,
    MacBootstrapPointer,
    MacBootstrapWindow,
    game_point_to_screen,
)
from one_dragon.base.controller.macos.macos_window_capture import MacWindow
from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame


@pytest.mark.parametrize('scale',[1,2])
def test_logical_inset_uses_each_frame_scale(scale: int,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos_window_capture.time,'monotonic',lambda:100.1)
    image=np.full((631*scale,1072*scale,3),30,dtype=np.uint8)
    image[:28*scale]=200
    frame=CapturedFrame(image,8,1000,100,1072*scale,631*scale,pixel_scale=scale)
    capture=macos_window_capture.MacWindowCapture()
    capture._running=True
    capture._stream=object()
    capture._latest=frame
    capture._top_inset_points=28
    result=capture.latest_frame(max_age_seconds=0.5)
    assert result is not None and result.image.shape==(1080,1920,3)
    assert np.all(result.image==30)
    assert (result.sequence,result.capture_time,result.monotonic_time)==(8,1000,100)


def test_legacy_pixels_do_not_change_with_metadata_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos_window_capture.time,'monotonic',lambda:100.1)
    image=np.full((1262,2144,3),30,dtype=np.uint8)
    image[:56]=200
    capture=macos_window_capture.MacWindowCapture()
    capture._running=True
    capture._stream=object()
    capture._latest=CapturedFrame(image,8,1000,100,2144,1262,pixel_scale=1)
    capture._top_inset_pixels=56
    result=capture.latest_frame(max_age_seconds=0.5)
    assert result is not None and np.all(result.image==30)


@pytest.mark.parametrize('scale',[1,2])
def test_startup_point_uses_logical_height_independently_of_output_scale(scale: int) -> None:
    window=MacWindow('com.miHoYo.Nap',123,456,'绝区零',1072,631)
    current=MacBootstrapWindow('com.miHoYo.Nap',123,456,100,200,1072,631,scale)
    assert game_point_to_screen(window,current,0,0,top_inset_points=28)==(100,228)


def test_invalid_logical_inset_is_rejected_before_native_capture() -> None:
    capture=macos_window_capture.MacWindowCapture()
    with pytest.raises(ValueError,match='不能同时'):
        capture.start(Mock(),top_inset_pixels=56,top_inset_points=28)


@pytest.mark.parametrize('scale', [0.5, 1, 2])
def test_auto_inset_follows_resizes_and_hidden_title_bar(
    scale: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一采集连接随每帧宽高重算顶部，保留底边、真实时间与非整除宽度。"""
    monkeypatch.setattr(macos_window_capture.time, 'monotonic', lambda: 100.1)
    capture = macos_window_capture.MacWindowCapture()
    capture._running = True
    capture._stream = object()
    capture._auto_top_inset = True
    for sequence, (width, inset) in enumerate(((1072, 28), (1440, 28), (1073, 28), (1920, 0))):
        pixels_wide = round(width * scale)
        pixels_inset = round(inset * scale)
        height = round(pixels_wide * 9 / 16) + pixels_inset
        image = np.full((height, pixels_wide, 3), 30, dtype=np.uint8)
        image[:pixels_inset] = 200
        capture._latest = CapturedFrame(image, sequence, 1000, 100, pixels_wide, height, pixel_scale=scale)
        result = capture.latest_frame(max_age_seconds=0.5)
        assert result is not None and result.image.shape == (1080, 1920, 3)
        assert np.all(result.image == 30)
        assert (result.sequence, result.capture_time, result.monotonic_time) == (sequence, 1000, 100)


@pytest.mark.parametrize('width, height, scale', [(1920, 1000, 1), (1920, 1300, 2)])
def test_auto_inset_rejects_abnormal_geometry(width: int, height: int, scale: int) -> None:
    """高度不足或超出合理标题栏高度时无有效帧，不能强行裁成 16:9。"""
    capture = macos_window_capture.MacWindowCapture()
    capture._running = True
    capture._stream = object()
    capture._auto_top_inset = True
    image = np.zeros((height, width, 3), dtype=np.uint8)
    capture.latest_raw_frame = Mock(return_value=CapturedFrame(image, 1, 1000, 100, width, height, scale))
    assert capture.latest_frame(max_age_seconds=0.5) is None
    assert '顶部余量' in capture.last_error


def test_auto_inset_rejects_conflicting_manual_options() -> None:
    """自动与手动模式互斥，在加载原生服务之前拒绝冲突配置。"""
    capture = macos_window_capture.MacWindowCapture()
    with pytest.raises(ValueError, match='不能同时'):
        capture.start(Mock(), auto_top_inset=True, top_inset_points=28)
    with pytest.raises(ValueError, match='不能同时'):
        capture.start(Mock(), auto_top_inset=True, content_rect=(0, 28, 1072, 603))


def test_auto_startup_point_uses_current_bottom_after_resize(monkeypatch: pytest.MonkeyPatch) -> None:
    """指针每次预检重读尺寸，缩放和隐藏标题栏后与截图使用相同内容区。"""
    window = MacWindow('com.miHoYo.Nap', 123, 456, '绝区零', 1072, 631)
    pointer = MacBootstrapPointer(window, auto_top_inset=True)
    for width, height, scale, inset in ((1072, 631, 1, 28), (1440, 838, 2, 28), (1920, 1080, 2, 0)):
        current = MacBootstrapWindow('com.miHoYo.Nap', 123, 456, 100, 200, width, height, scale)
        monkeypatch.setattr(pointer, '_read_window', Mock(return_value=current))
        assert pointer.resolve_point(0, 0) == (100, 200 + inset)
        assert pointer.resolve_point(960, 540) == (100 + width / 2, 200 + inset + (height - inset) / 2)
    invalid = MacBootstrapWindow('com.miHoYo.Nap', 123, 456, 100, 200, 1072, 800, 2)
    monkeypatch.setattr(pointer, '_read_window', lambda: invalid)
    with pytest.raises(MacBootstrapError, match='顶部余量'):
        pointer.resolve_point(0, 0)
