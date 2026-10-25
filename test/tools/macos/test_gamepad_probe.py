"""用假 CLI 验证只读默认、完整状态和停止释放，不访问真实手柄。"""

from __future__ import annotations

import json
import runpy
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

PROBE = Path(__file__).resolve().parents[4] / 'tools/macos/gamepad_probe.py'


@pytest.fixture
def fake_ojd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """创建只记录调用及帧内容的本地可执行文件。"""
    executable = tmp_path / 'ojd'
    records = tmp_path / 'calls.jsonl'
    monkeypatch.setenv('FAKE_OJD_LOG', str(records))
    executable.write_text(textwrap.dedent(f'''\
        #!{sys.executable}
        import json
        import os
        import sys

        def record(value):
            with open(os.environ['FAKE_OJD_LOG'], 'a') as output:
                output.write(json.dumps(value) + '\\n')

        if os.path.basename(sys.argv[0]) != 'ojd':
            record({{'gui_started': True}})
            sys.exit(91)
        record({{'command': sys.argv[1:]}})
        if sys.argv[1:] == ['--version']:
            print('0.6.0-alpha.1')
        elif sys.argv[-1] == 'status':
            print(json.dumps({{'service': {{'state': os.getenv('FAKE_STATE', 'Running'),
                                          'version': '0.6.0-alpha.1'}}}}, indent=2))
        else:
            for line in sys.stdin:
                frame = json.loads(line)
                record({{'frame': frame}})
                if os.getenv('FAKE_FEED_FAIL') and frame['buttons']:
                    print('fake feed error', file=sys.stderr)
                    sys.exit(7)
            record({{'eof': True}})
    '''), encoding='utf-8')
    executable.chmod(0o755)
    return executable, records


def read_records(path: Path) -> list[dict[str, Any]]:
    """读取假 CLI 已落盘的 JSONL。"""
    return [json.loads(line) for line in path.read_text().splitlines()]


def run_probe(executable: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """在独立 Python 进程中执行工具，限制测试等待。"""
    return subprocess.run([sys.executable, str(PROBE), '--ojd', str(executable), *arguments],
                          capture_output=True, text=True, check=False, timeout=6)


def test_symlink_preserves_cli_name_and_rejects_app_binary(fake_ojd: tuple[Path, Path]) -> None:
    """发行包按 argv[0] 选择入口，保留 ojd 链接且禁止直接运行 GUI 名称。"""
    executable, records = fake_ojd
    app_binary = executable.with_name('OpenJoystickDriver')
    executable.rename(app_binary)
    executable.symlink_to(app_binary)
    result = run_probe(executable)
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert next(item for item in events if item['event'] == 'version')['command'][0] == str(executable)
    calls = read_records(records)
    assert len(calls) == 2
    assert not any('gui_started' in item for item in calls)
    refused = run_probe(app_binary)
    assert refused.returncode == 1
    assert read_records(records) == calls


def test_only_neutral_allows_duration_up_to_600_seconds() -> None:
    """只验证参数边界，不启动 CLI 或实际等待长动作。"""
    parse_args = runpy.run_path(str(PROBE))['parse_args']
    assert parse_args(['--action', 'neutral', '--duration', '600']).duration == 600
    assert parse_args(['--action', 'tap', '--duration', '10']).duration == 10
    for action, duration in [('neutral', '600.01'), ('tap', '10.01'),
                             ('stick', '600'), ('combo', '600')]:
        with pytest.raises(SystemExit) as stopped:
            parse_args(['--action', action, '--duration', duration])
        assert stopped.value.code == 2


@pytest.mark.parametrize('action', [False, True], ids=['read-only', 'reject-action'])
def test_stopped_service_never_opens_feed(
    fake_ojd: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, action: bool,
) -> None:
    """status 退出零但 Stopped 时，只读报告成功，动作明确失败。"""
    executable, records = fake_ojd
    monkeypatch.setenv('FAKE_STATE', 'Stopped')
    result = run_probe(executable, *(['--action', 'tap'] if action else []))
    assert result.returncode == (1 if action else 0)
    calls = [item['command'] for item in read_records(records)]
    assert calls == [
        ['--version'], ['--json', '--no-input', '--no-color', '--timeout', '2', 'status'],
    ]
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert next(item for item in events if item['event'] == 'service_state')['running'] is False


def test_combo_keeps_complete_state_and_releases(fake_ojd: tuple[Path, Path]) -> None:
    """短帧同时保留按钮和摇杆，正常 EOF 前发送完整中立状态。"""
    executable, records = fake_ojd
    result = run_probe(executable, '--action', 'combo', '--button', 'South',
                       '--button', 'RightShoulder', '--x', '0.5', '--y', '0.25',
                       '--duration', '0.12')
    assert result.returncode == 0, result.stdout + result.stderr
    calls = read_records(records)
    assert calls[2]['command'] == [
        '--json', '--no-input', '--no-color', '--timeout', '2', 'virtual', 'feed',
        '--as', 'game-controller-compatible',
    ]
    frames = [item['frame'] for item in calls if 'frame' in item]
    assert 3 <= len(frames) <= 6
    assert all(set(frame) == {'buttons', 'dpad', 'axes', 'holdMilliseconds'} for frame in frames)
    assert all(8 <= frame['holdMilliseconds'] <= 50 for frame in frames)
    active = [frame for frame in frames if frame['buttons']]
    assert active
    for frame in active:
        assert frame['buttons'] == ['RightShoulder', 'South']
        assert frame['axes'] == {'LeftStickX': 0.5, 'LeftStickY': 0.25,
                                 'RightStickX': 0.0, 'RightStickY': 0.0,
                                 'LeftTrigger': 0.0, 'RightTrigger': 0.0}
    assert frames[0]['buttons'] == frames[-1]['buttons'] == []
    assert not any(frames[-1]['axes'].values())
    assert calls[-1] == {'eof': True}
    events = [json.loads(line) for line in result.stdout.splitlines()]
    summary = next(item for item in events if item['event'] == 'feed_summary')
    assert summary['device_created'] == summary['release_observed'] == 'unverified'
    assert summary['neutral_frame_written'] is True


def test_sigterm_sends_neutral_then_eof(fake_ojd: tuple[Path, Path]) -> None:
    """保持中途收到停止信号时仍先释放，再结束 CLI。"""
    executable, records = fake_ojd
    with subprocess.Popen(
        [sys.executable, str(PROBE), '--ojd', str(executable), '--action', 'combo',
         '--duration', '10'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as process:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if records.exists() and any(item.get('frame', {}).get('buttons')
                                        for item in read_records(records)):
                break
            time.sleep(0.01)
        else:
            process.kill()
            pytest.fail('假 CLI 未及时收到动作帧')
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 128 + signal.SIGTERM, stdout + stderr
    calls = read_records(records)
    frames = [item['frame'] for item in calls if 'frame' in item]
    assert frames[-1]['buttons'] == []
    assert not any(frames[-1]['axes'].values())
    assert calls[-1] == {'eof': True}


def test_cli_error_still_attempts_release(
    fake_ojd: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 提前退出时报告失败及释放边界，不把写管道当设备确认。"""
    executable, _ = fake_ojd
    monkeypatch.setenv('FAKE_FEED_FAIL', '1')
    result = run_probe(executable, '--action', 'tap', '--duration', '0.3')
    assert result.returncode == 1
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert any(item['event'] == 'release_write_failed' for item in events)
    summary = next(item for item in events if item['event'] == 'feed_summary')
    assert summary['cli_returncode'] == 7
    assert summary['neutral_frame_written'] is False
