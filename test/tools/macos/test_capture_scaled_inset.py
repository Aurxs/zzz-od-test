"""标题栏逻辑点随帧缩放转换，旧像素配置与帧时间保持原语义。"""

from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.controller.macos import macos_window_capture
from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame
from one_dragon.base.controller.macos.macos_bootstrap_pointer import MacBootstrapWindow, game_point_to_screen
from one_dragon.base.controller.macos.macos_window_capture import MacWindow


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
