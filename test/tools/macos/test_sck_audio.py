"""离线检查 SCK 声音的原生复制、连续转换和失效边界，不打开设备。"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from scipy.signal import resample_poly

from one_dragon.base.controller.macos import macos_window_capture as capture_module
from one_dragon.base.controller.macos.sck_audio_converter import (
    CapturedAudio,
    StreamingAudioConverter,
    copy_audio_sample,
)
from zzz_od.auto_battle import auto_battle_dodge_context as dodge_module


def test_resampling_preserves_filter_and_phase_across_arbitrary_blocks() -> None:
    """1 样本的小块也与整段因果转换一致，48k→32k 不多不漏。"""
    source = np.random.default_rng(2).normal(size=48000)
    expected = StreamingAudioConverter(48000).push(source)
    converter = StreamingAudioConverter(48000)
    edges = [0, 1, 3, 482, 483, 496, 809, 1090, 16001, 48000]
    actual = np.concatenate([converter.push(source[a:b]) for a, b in zip(edges[:-1], edges[1:], strict=True)])
    assert actual.size == 32000
    np.testing.assert_allclose(actual, expected, atol=2e-15)
    # 与现有模板转换使用相同 FIR，因果输出仅多 10 个目标采样的固定延迟。
    np.testing.assert_allclose(expected[10:], resample_poly(source, 2, 3)[:-10], atol=2e-15)


@pytest.mark.parametrize('frequency, amplitude', [(6000, 0.7), (20000, 0.01)])
def test_resampling_filters_frequencies_above_target_nyquist(frequency: int, amplitude: float) -> None:
    """保留可识别频段，抑制降采样产生的高频混叠。"""
    wave = np.sin(2 * np.pi * frequency * np.arange(48000) / 48000)
    result = StreamingAudioConverter(48000).push(wave)[100:]
    rms = float(np.sqrt(np.mean(result * result)))
    assert (rms > amplitude) if frequency == 6000 else (rms < amplitude)


@pytest.mark.skipif(sys.platform != 'darwin', reason='仅本机 CoreMedia 内存样本，不涉及窗口或设备')
@pytest.mark.parametrize('channels, planar', [(1, False), (2, False), (2, True)])
def test_native_pcm_copy_supports_real_coremedia_layouts(channels: int, planar: bool) -> None:
    """创建内存 CMSampleBuffer 验证 PyObjC 桥，不用假的原生指针替代。"""
    import CoreAudio as ca
    import CoreMedia as cm

    values = np.arange(24, dtype=np.float32).reshape(24 // channels, channels) / 24
    flags = ca.kAudioFormatFlagIsFloat | ca.kAudioFormatFlagIsPacked
    if planar:
        flags |= ca.kAudioFormatFlagIsNonInterleaved
    bytes_per_frame = 4 if planar else 4 * channels
    fmt = ca.AudioStreamBasicDescription(
        48000, ca.kAudioFormatLinearPCM, flags, bytes_per_frame, 1, bytes_per_frame, channels, 32, 0,
    )
    error, description = cm.CMAudioFormatDescriptionCreate(None, fmt, 0, None, 0, None, None, None)
    assert error == 0
    timing = cm.CMSampleTimingInfo(cm.CMTimeMake(1, 48000), cm.CMTimeMake(96000, 48000), cm.kCMTimeInvalid)
    error, sample = cm.CMSampleBufferCreate(
        None, None, True, None, None, description, values.shape[0], 1, [timing], 0, [], None,
    )
    assert error == 0
    buffers = ca.AudioBufferList(channels if planar else 1)
    for index, buffer in enumerate(buffers):
        array = values[:, index].copy() if planar else values.ravel()
        buffer.mNumberChannels = 1 if planar else channels
        buffer.create_buffer(array.nbytes)
        memoryview(buffer.mData).cast('B')[:] = array.tobytes()
    assert cm.CMSampleBufferSetDataBufferFromAudioBufferList(sample, None, None, 0, buffers) == 0
    actual = copy_audio_sample(sample)
    assert actual.sample_rate == 48000 and actual.presentation_time == 2
    np.testing.assert_allclose(actual.samples, values.mean(axis=1), atol=1e-7)
    for buffer in buffers:
        memoryview(buffer.mData).cast('B')[:] = bytes(buffer.mDataByteSize)
    assert np.any(actual.samples)  # 复制后的波形不引用原生缓冲。


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> tuple[dodge_module.MacAudioRecorder, Mock, Mock]:
    """保留生产订阅逻辑，执行器只记录清理任务，避免产生后台线程。"""
    executor = Mock()
    monkeypatch.setattr(dodge_module, '_dodge_check_executor', executor)
    capture, error = Mock(), Mock()
    result = dodge_module.MacAudioRecorder(error, lambda: capture)
    result.start_running_async()
    result._start_mac_audio(result._generation)
    return result, capture, error


def test_recorder_continuous_48k_to_32k_uses_current_subscription(recorder: tuple) -> None:
    """半秒滚动缓冲直接供生产分类器使用，清空命中缓冲不重置滤波相位。"""
    result, capture, _ = recorder
    callback = capture.start_audio.call_args.args[0]
    wave = np.sin(2 * np.pi * 3000 * np.arange(48000) / 48000)
    for start in range(0, wave.size, 480):
        callback(CapturedAudio(wave[start:start + 480], 48000, start / 48000))
    expected = StreamingAudioConverter(48000).push(wave)[-16000:]
    np.testing.assert_allclose(result.get_latest_audio(), expected, atol=1e-15)
    converter = result._converter
    result.clear_audio()
    assert result._converter is converter
    assert not result.get_latest_audio().any()


def test_stop_discards_late_callbacks_and_resume_discards_old_generation(recorder: tuple) -> None:
    """暂停、恢复及上次失败的迟到回调都不能污染新录音。"""
    result, capture, error = recorder
    callback, failure = capture.start_audio.call_args.args
    chunk = CapturedAudio(np.ones(480), 48000, 0)
    callback(chunk)
    result.stop_running()
    capture.stop_audio.assert_called_once_with()
    callback(chunk)
    assert result.get_latest_audio().size == 0
    result.start_running_async()
    result._start_mac_audio(result._generation)
    callback(chunk)
    failure(RuntimeError('上一轮错误'))
    assert result.running and result.get_latest_audio().size == 0
    error.assert_not_called()
    capture.start_audio.call_args.args[0](chunk)
    assert result.get_latest_audio().size == 16000


def test_gap_clears_old_audio_and_resampling_state(recorder: tuple) -> None:
    """样本时间不连续后丢弃旧提示，不拼接两个时间段触发闪避。"""
    result, capture, _ = recorder
    callback = capture.start_audio.call_args.args[0]
    callback(CapturedAudio(np.ones(24000), 48000, 0))
    assert result.get_latest_audio().any()
    callback(CapturedAudio(np.zeros(480), 48000, 1))
    assert not result.get_latest_audio().any()


def test_stale_audio_falls_back_once_and_preserves_video(recorder: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """系统不再发送样本时清空旧提示，通知一次并移除声音消费者。"""
    result, capture, error = recorder
    now = result._started_monotonic
    monkeypatch.setattr(dodge_module.time, 'monotonic', lambda: now + 1)
    assert result.get_latest_audio().size == 0
    assert result.get_latest_audio().size == 0
    error.assert_called_once()
    result._release_mac_audio(result._generation)
    capture.stop_audio.assert_called_once_with()
    capture.stop.assert_not_called()


def test_capture_audio_failure_and_old_stream_do_not_invalidate_video(monkeypatch: pytest.MonkeyPatch) -> None:
    """音频解析异常只关闭声音回调，画面和旧流隔离保持不变。"""
    capture = capture_module.MacWindowCapture()
    stream, frame = object(), object()
    capture._stream, capture._running, capture._latest = stream, True, frame
    callback, error = Mock(), Mock()
    capture._audio_callback, capture._audio_error_callback = callback, error
    cm = SimpleNamespace(CMSampleBufferIsValid=lambda _: True, CMSampleBufferDataIsReady=lambda _: True)
    sck = SimpleNamespace(SCStreamOutputTypeScreen=0, SCStreamOutputTypeAudio=1)
    monkeypatch.setattr(capture_module, '_native_api', lambda: (cm, None, None, None, sck, None))
    monkeypatch.setattr(capture_module, 'copy_audio_sample', Mock(side_effect=ValueError('坏样本')))
    capture._receive_sample(object(), None, 1)
    error.assert_not_called()
    capture._receive_sample(stream, None, 1)
    capture._receive_sample(stream, None, 1)
    error.assert_called_once()
    callback.assert_not_called()
    assert capture._latest is frame and capture._running and capture.last_error is None


def test_audio_subscription_updates_existing_stream_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """复用既有 SCStream 和窗口过滤器；停止只移除声音而不停止视频。"""
    capture = capture_module.MacWindowCapture()
    stream, config, output = Mock(), Mock(), Mock()
    stream.addStreamOutput_type_sampleHandlerQueue_error_.return_value = (True, None)
    capture._stream, capture._configuration, capture._output, capture._running = stream, config, output, True
    dispatch = SimpleNamespace(dispatch_queue_create=Mock(return_value=object()))
    sck = SimpleNamespace(SCStreamOutputTypeAudio=1)
    cm = SimpleNamespace(
        CMTimeGetSeconds=lambda value: value, CMClockGetTime=lambda _: 100,
        CMClockGetHostTimeClock=lambda: None,
    )
    monkeypatch.setattr(capture_module, '_native_api', lambda: (cm, dispatch, None, None, sck, None))
    capture._wait = Mock(return_value=(None,))
    callback, error = Mock(), Mock()
    capture.start_audio(callback, error)
    config.copy.return_value.setCapturesAudio_.assert_called_once_with(True)
    with pytest.raises(capture_module.MacCaptureError, match='已有声音订阅'):
        capture.start_audio(callback, error)
    capture.stop_audio()
    assert capture._running and capture._stream is stream
    stream.removeStreamOutput_type_error_.assert_called_once_with(output, 1, None)
    stream.stopCaptureWithCompletionHandler_.assert_not_called()
    assert capture._audio_callback is None


@pytest.mark.parametrize('template_id', [1, 2, 3])
def test_production_templates_match_after_mac_stream_conversion(recorder: tuple, template_id: int) -> None:
    """三个正式 WAV 经 48k 回调和原匹配器仍得到各自分类，命中后只消费一次。"""
    from pathlib import Path

    result, capture, _ = recorder
    context = dodge_module.AutoBattleDodgeContext(Mock())
    context._audio_recorder = result
    context.init_audio_template()
    source = context._load_audio_template(Path(f'assets/template/dodge_audio/template_{template_id}.wav'))
    window = np.zeros(16000)
    window[:min(source.size, window.size)] = source[:window.size]
    native_wave = resample_poly(window, 3, 2)
    callback = capture.start_audio.call_args.args[0]
    for start in range(0, native_wave.size, 479):
        callback(CapturedAudio(native_wave[start:start + 479], 48000, start / 48000))
    correlations = context.get_max_corr(result.get_latest_audio())
    assert int(np.argmax(correlations)) + 1 == template_id
    assert correlations[template_id - 1] > result.trigger_threshold
    assert context.check_dodge_audio(1) == dodge_module.AudioTemplateEnum(template_id)
    assert context.check_dodge_audio(2) is False


def test_capture_rejects_old_queued_audio_after_resubscription(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一个原生流上的旧排队音频不能被新订阅当成当前声音。"""
    capture = capture_module.MacWindowCapture()
    capture._stream, capture._running, capture._audio_start_pts = object(), True, 100.0
    capture._audio_callback, capture._audio_error_callback = Mock(), Mock()
    cm = SimpleNamespace(
        CMSampleBufferIsValid=lambda _: True, CMSampleBufferDataIsReady=lambda _: True,
        CMTimeGetSeconds=lambda value: value, CMClockGetTime=lambda _: 100.1,
        CMClockGetHostTimeClock=lambda: None,
    )
    sck = SimpleNamespace(SCStreamOutputTypeAudio=1)
    monkeypatch.setattr(capture_module, '_native_api', lambda: (cm, None, None, None, sck, None))
    audio = CapturedAudio(np.ones(480), 48000, 99.99)
    reader = Mock(return_value=audio)
    monkeypatch.setattr(capture_module, 'copy_audio_sample', reader)
    capture._receive_sample(capture._stream, None, 1)
    capture._audio_callback.assert_not_called()
    current = CapturedAudio(np.ones(480), 48000, 100.05)
    reader.return_value = current
    capture._receive_sample(capture._stream, None, 1)
    capture._audio_callback.assert_called_once_with(current)


def test_audio_error_notification_cannot_interrupt_cleanup() -> None:
    """界面通知已关闭时仍能作废声音回调，不把异常抛回原生线程。"""
    capture = capture_module.MacWindowCapture()
    capture._stream, capture._running = object(), True
    capture._audio_callback = Mock()
    notification = Mock(side_effect=RuntimeError('界面已关闭'))
    capture._audio_error_callback = notification
    capture._fail_audio(capture._stream, '声音停止')
    assert capture._audio_callback is None and capture._audio_error_callback is None
    assert capture._running and '界面已关闭' in capture.audio_error
    capture._fail_audio(capture._stream, '重复通知')
    notification.assert_called_once()


def test_failed_audio_start_releases_output_and_leaves_video_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝音频权限或配置失败不破坏已经工作的图像采集。"""
    capture = capture_module.MacWindowCapture()
    stream, config, output = Mock(), Mock(), Mock()
    stream.addStreamOutput_type_sampleHandlerQueue_error_.return_value = (True, None)
    capture._stream, capture._configuration, capture._output, capture._running = stream, config, output, True
    cm = SimpleNamespace(
        CMTimeGetSeconds=lambda value: value, CMClockGetTime=lambda _: 100,
        CMClockGetHostTimeClock=lambda: None,
    )
    dispatch = SimpleNamespace(dispatch_queue_create=Mock(return_value=object()))
    sck = SimpleNamespace(SCStreamOutputTypeAudio=1)
    monkeypatch.setattr(capture_module, '_native_api', lambda: (cm, dispatch, None, None, sck, None))
    capture._wait = Mock(side_effect=[('拒绝音频',), (None,)])
    with pytest.raises(capture_module.MacCaptureError, match='拒绝音频'):
        capture.start_audio(Mock(), Mock())
    assert capture._running and capture._stream is stream and capture._audio_callback is None
    stream.removeStreamOutput_type_error_.assert_called_once_with(output, 1, None)
