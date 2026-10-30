"""只验证内存计数、有限对象快照与监测生命周期，不启动设备或模型。"""

import ctypes
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.macos import memory_monitor as memory


def test_native_reader_keeps_footprint_distinct_from_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    """压缩时 RSS 很小也必须保留真实账本和峰值，原生线程数来自 taskinfo。"""
    def rusage(pid: int, flavor: int, pointer: object) -> int:
        assert (pid, flavor) == (123, 4)
        usage = ctypes.cast(pointer, ctypes.POINTER(memory._RusageInfoV4)).contents
        usage.resident_size = 600 * 1024**2
        usage.phys_footprint = 8 * 1024**3
        usage.lifetime_max_phys_footprint = 9 * 1024**3
        return 0

    def taskinfo(pid: int, flavor: int, address: int, pointer: object, size: int) -> int:
        assert (pid, flavor, address) == (123, 4, 0)
        ctypes.cast(pointer, ctypes.POINTER(memory._TaskInfo)).contents.counts[9] = 86
        return size

    library = SimpleNamespace(proc_pid_rusage=Mock(side_effect=rusage), proc_pidinfo=Mock(side_effect=taskinfo))
    monkeypatch.setattr(memory.ctypes, 'CDLL', Mock(return_value=library))
    result = memory.MacProcessMemoryReader().read(123)
    assert result['footprint_bytes'] == 8 * 1024**3
    assert result['rss_bytes'] == 600 * 1024**2
    assert result['peak_footprint_bytes'] == 9 * 1024**3
    assert result['native_threads'] == 86
    assert ctypes.sizeof(memory._RusageInfoV4) == 296
    assert ctypes.sizeof(memory._TaskInfo) == 96


def test_details_do_not_load_models_and_deduplicate_images() -> None:
    """尚未加载迷失模型也能采样，共享的截图数组只计一次。"""
    image = SimpleNamespace(nbytes=1920 * 1080 * 3)
    ctx = SimpleNamespace(
        controller=SimpleNamespace(screenshot_history=[SimpleNamespace(image=image)] * 10),
        auto_battle_context=SimpleNamespace(dodge_context=SimpleNamespace(_flash_model=None), _op_cache={}),
        ocr=SimpleNamespace(_model=None), current_instance_idx=2,
        run_context=SimpleNamespace(current_application=None, current_app_id=None,
                                    event_bus=SimpleNamespace(callbacks={'暂停': [object(), object()]})),
        callbacks={'业务': [object()]},
    )
    result = memory.context_memory_details(ctx)
    assert result['screenshot_history_count'] == 10
    assert result['screenshot_history_bytes'] == image.nbytes
    assert result['lost_void_history_bytes'] == 0
    assert result['session_ids'] == {'lost_void': None, 'flash': None, 'ocr_det': None, 'ocr_rec': None}
    assert result['run_event_listener_count'] == 2
    assert result['context_event_listener_count'] == 1
    assert 'lost_void' not in ctx.__dict__


def test_monitor_records_start_periodic_and_shutdown_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重复启动/停止不会增加线程或退出行，游戏账本独立保存。"""
    reader = SimpleNamespace(read=lambda pid: {'pid': pid, 'footprint_bytes': 100, 'rss_bytes': 10})
    monkeypatch.setattr(memory, 'MacProcessMemoryReader', lambda: reader)
    monitor = memory.MacMemoryMonitor(tmp_path, lambda: {'game_pid': 987}, interval_seconds=60)
    monitor.start()
    worker = monitor._thread
    monitor.start()
    assert monitor._thread is worker
    monitor.sample('periodic')
    monitor.stop()
    monitor.stop()
    rows = [json.loads(line) for line in monitor.output_path.read_text().splitlines()]
    assert [row['phase'] for row in rows] == ['start', 'periodic', 'shutdown']
    assert rows[1]['game']['pid'] == 987
    assert rows[1]['process']['footprint_bytes'] == 100
    assert worker is not None and not worker.is_alive()


def test_sampling_failure_does_not_break_application(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """权限/文件等诊断错误只记警告，不影响业务。"""
    monkeypatch.setattr(memory, 'MacProcessMemoryReader', lambda: SimpleNamespace(read=Mock(side_effect=OSError('denied'))))
    warning = Mock()
    monkeypatch.setattr(memory.log, 'warning', warning)
    monitor = memory.MacMemoryMonitor(tmp_path, lambda: {})
    monitor.sample('periodic')
    warning.assert_called_once()
    assert not monitor.output_path.exists()
