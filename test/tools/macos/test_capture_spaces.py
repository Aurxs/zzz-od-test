"""跨 Space 的原生回调恢复与重复像素保护，不调用真实系统服务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.controller.macos import macos_window_capture as module
from one_dragon.base.controller.macos.macos_game_launcher import select_game_window


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> tuple[module.MacWindowCapture, object, SimpleNamespace]:
    """模拟带新 host 时间但可能重复像素的 Complete 回调。"""
    state = SimpleNamespace(now=100.0, pixel=10, status=0)
    rect = SimpleNamespace(origin=SimpleNamespace(x=0, y=0), size=SimpleNamespace(width=16, height=9))
    cm = SimpleNamespace(
        CMSampleBufferIsValid=lambda sample: True,
        CMSampleBufferGetSampleAttachmentsArray=lambda *args: [{
            'status': state.status, 'time': int(state.now * 1000), 'rect': rect, 'scale': 1,
        }],
        CMSampleBufferGetImageBuffer=lambda sample: object(),
    )
    quartz = SimpleNamespace(
        kCVPixelFormatType_32BGRA=1, kCVPixelBufferLock_ReadOnly=1,
        CVGetCurrentHostTime=lambda: int(state.now * 1000), CVGetHostClockFrequency=lambda: 1000,
        CVPixelBufferGetPixelFormatType=lambda buffer: 1,
        CVPixelBufferGetWidth=lambda buffer: 16, CVPixelBufferGetHeight=lambda buffer: 9,
        CVPixelBufferGetBytesPerRow=lambda buffer: 64,
        CGRectMakeWithDictionaryRepresentation=lambda value, out: (True, value),
        CVPixelBufferLockBaseAddress=lambda *args: 0, CVPixelBufferUnlockBaseAddress=lambda *args: 0,
        CVPixelBufferGetBaseAddress=lambda buffer: SimpleNamespace(
            as_buffer=lambda size: bytes([state.pixel]) * size,
        ),
    )
    sck = SimpleNamespace(
        SCStreamOutputTypeScreen=0, SCStreamFrameInfoStatus='status', SCStreamFrameInfoDisplayTime='time',
        SCStreamFrameInfoContentRect='rect', SCStreamFrameInfoScaleFactor='scale',
        SCFrameStatusComplete=0, SCFrameStatusIdle=1, SCFrameStatusStopped=5,
    )
    monkeypatch.setattr(module, '_native_api', lambda: (cm, None, None, quartz, sck, None))
    monkeypatch.setattr(module.time, 'monotonic', lambda: state.now)
    capture = module.MacWindowCapture()
    stream = object()
    capture._stream, capture._running = stream, True
    return capture, stream, state


def test_inactive_recovers_only_with_changed_complete_pixels(source: tuple) -> None:
    """Inactive 后 Complete 仍可能重复旧图，必须看到变化才恢复，Idle 不能续期。"""
    capture, stream, state = source
    capture._receive_sample(stream, None, 0)
    capture._set_stream_active(stream, False)
    capture._receive_sample(stream, None, 0)
    baseline = capture._latest
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert capture.last_error is None
    state.now += 1
    capture._receive_sample(stream, None, 0)
    assert capture._latest is baseline
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert '拒绝使用冻结画面' in capture.last_error
    state.pixel += 1
    capture._receive_sample(stream, None, 0)
    fresh = capture.latest_raw_frame(max_age_seconds=0.5)
    assert fresh is not None and np.all(fresh.image == state.pixel)
    assert fresh.monotonic_time == state.now
    state.now += 0.6
    state.status = 1
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert '未变化' in capture.last_error
    assert capture._latest is fresh


def test_active_and_diagnostics_do_not_fabricate_frames(source: tuple) -> None:
    """Active 和读取诊断都不是采集证据；旧流通知无效，真正停止不可恢复。"""
    capture, stream, state = source
    capture._receive_sample(stream, None, 0)
    capture._set_stream_active(object(), False)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is not None
    capture._set_stream_active(stream, False)
    capture._set_stream_active(stream, True)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    state.status = 1
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    state.now += 1
    diag = capture.diagnostics()
    assert diag.callback_age_seconds == 1 and diag.observation_age_seconds is None
    diag.sample_counts.clear()
    assert capture.diagnostics().sample_counts
    state.status = 0
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is not None
    capture._fail_stream(stream, '停止')
    capture._set_stream_active(stream, True)
    capture._receive_sample(stream, None, 0)
    assert capture.latest_raw_frame(max_age_seconds=0.5) is None
    assert capture.last_error == '停止'


def test_inactive_during_conversion_discards_inflight_frame(source: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """已开始复制的帧不能跨过失活通知成为恢复依据。"""
    capture, stream, _ = source
    convert = module.bgra_buffer_to_rgb

    def interrupted(*args: object, **kwargs: object) -> np.ndarray:
        capture._set_stream_active(stream, False)
        return convert(*args, **kwargs)

    monkeypatch.setattr(module, 'bgra_buffer_to_rgb', interrupted)
    capture._receive_sample(stream, None, 0)
    assert capture._latest is None


def test_discovery_and_selection_include_other_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """枚举显式请求全部窗口，其他桌面仍按身份和大小正常选中。"""
    native = Mock()
    monkeypatch.setattr(module, '_native_api', lambda: (None, None, None, None, native, None))
    capture = module.MacWindowCapture()
    content = SimpleNamespace(windows=lambda: [])

    def wait(invoke: object, operation: str) -> tuple:
        invoke('completion')
        return content, None

    monkeypatch.setattr(capture, '_wait', wait)
    assert capture._shareable_windows() == []
    native.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_.assert_called_once_with(
        True, False, 'completion',
    )
    window = module.MacWindow('game', 1, 2, '游戏', 953, 564, on_screen=False)
    assert select_game_window([window], '') is window
