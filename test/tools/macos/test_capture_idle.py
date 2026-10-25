"""区分静态画面的 Idle 确认与真正没有采集回调。"""

from types import SimpleNamespace

import numpy as np
import pytest

from one_dragon.base.controller.macos import macos_window_capture
from one_dragon.base.controller.macos.sck_frame_converter import CapturedFrame


@pytest.fixture
def idle_capture(monkeypatch: pytest.MonkeyPatch) -> tuple[
    macos_window_capture.MacWindowCapture, object, dict[str, int], CapturedFrame,
]:
    """用有效 host 时钟和一张旧 Complete 帧模拟同一个采集流。"""
    metadata = {'status': 1, 'display_time': 999}
    cm = SimpleNamespace(
        CMSampleBufferIsValid=lambda sample: True,
        CMSampleBufferGetSampleAttachmentsArray=lambda sample, create: [metadata],
    )
    quartz = SimpleNamespace(CVGetCurrentHostTime=lambda: 1000, CVGetHostClockFrequency=lambda: 10)
    sck = SimpleNamespace(
        SCStreamOutputTypeScreen=0, SCStreamFrameInfoStatus='status',
        SCStreamFrameInfoDisplayTime='display_time',
        SCFrameStatusComplete=0, SCFrameStatusIdle=1, SCFrameStatusStopped=5,
    )
    monkeypatch.setattr(macos_window_capture, '_native_api', lambda: (cm, None, None, quartz, sck, None))
    monkeypatch.setattr(macos_window_capture.time, 'monotonic', lambda: 100)
    capture = macos_window_capture.MacWindowCapture()
    stream = object()
    frame = CapturedFrame(np.zeros((9, 16, 3), dtype=np.uint8), 7, 1000, 90, 16, 9)
    capture._stream = stream
    capture._running = True
    capture._latest = frame
    return capture, stream, metadata, frame


def test_idle_confirms_static_pixels_without_changing_frame_time(
    idle_capture: tuple[macos_window_capture.MacWindowCapture, object, dict[str, int], CapturedFrame],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有效 Idle 保持旧像素可用，但时间和序号不变；断流后仍会超时。"""
    capture, stream, _, original = idle_capture
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is original
    assert capture.last_error is None
    normalized = capture.latest_frame(max_age_seconds=0.5)
    assert normalized is not None
    assert (normalized.sequence, normalized.capture_time, normalized.monotonic_time) == (7, 1000, 90)

    monkeypatch.setattr(macos_window_capture.time, 'monotonic', lambda: 100.6)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert '过期' in capture.last_error


def test_idle_cannot_restore_invalid_or_other_stream_frames(
    idle_capture: tuple[macos_window_capture.MacWindowCapture, object, dict[str, int], CapturedFrame],
) -> None:
    """异流、无 Complete 或无效时间的 Idle 无效，空白、停止和关闭均清帧。"""
    capture, stream, metadata, frame = idle_capture
    capture._receive_sample(object(), None, 0)
    assert capture._last_observation_monotonic is None
    capture._latest = None
    capture._receive_sample(stream, None, 0)
    assert capture._last_observation_monotonic is None
    capture._latest = frame
    metadata['display_time'] = 1001
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert capture._last_observation_monotonic is None

    metadata.update(status=2, display_time=999)
    capture._receive_sample(stream, None, 0)
    assert capture._latest is None
    metadata['status'] = 1
    capture._receive_sample(stream, None, 0)
    assert capture._last_observation_monotonic is None
    capture._latest = frame
    metadata['status'] = 5
    capture._receive_sample(stream, None, 0)
    assert capture._latest is None and not capture._running
    capture._running, capture._latest = True, frame
    capture._fail_stream(stream, '窗口已关闭')
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
