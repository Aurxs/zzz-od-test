"""只用假 OJD CLI 验证兼容层的状态、期限和清理，不访问真实输入。"""

from __future__ import annotations

import json
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from one_dragon.base.controller.gamepad_input import GamepadState
from one_dragon.base.controller.macos.ojd_gamepad_client import (
    OjdGamepadClient,
    OjdGamepadError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import Any


@pytest.fixture
def fake_ojd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """保留真实发行入口的 ojd 链接名规则，逐行保存完整帧。"""
    executable = tmp_path / 'OpenJoystickDriver'
    records = tmp_path / 'frames.jsonl'
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
            sys.exit(91)
        record({{'command': sys.argv[1:], 'executable': sys.argv[0]}})
        if sys.argv[1:] == ['--version']:
            print('0.6.0-alpha.1')
        elif sys.argv[-1] == 'status':
            print(json.dumps({{'service': {{'state': os.getenv('FAKE_STATE', 'Running'),
                                          'version': '0.6.0-alpha.1'}}}}))
        else:
            for line in sys.stdin:
                record({{'frame': json.loads(line)}})
            record({{'eof': True}})
    '''), encoding='utf-8')
    executable.chmod(0o755)
    link = tmp_path / 'ojd'
    link.symlink_to(executable)
    return link, records


@pytest.fixture
def client(fake_ojd: tuple[Path, Path]) -> Iterator[OjdGamepadClient]:
    """每个测试在结束时关闭假 feed。"""
    adapter = OjdGamepadClient(str(fake_ojd[0]), frame_interval=0.01,
                               key_press_time=0.02, combo_press_time=0.025)
    adapter.connect()
    try:
        yield adapter
    finally:
        adapter.close()


def wait_for(predicate: Callable[[], bool]) -> None:
    """只为线程或假子进程的短暂调度等待。"""
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, '未及时观察到预期状态'
        time.sleep(0.005)


def records(path: Path) -> list[dict[str, Any]]:
    """读取假进程日志。"""
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_full_state_shares_one_feed_and_preserves_symlink(
    client: OjdGamepadClient, fake_ojd: tuple[Path, Path],
) -> None:
    """移动、攻击、方向键和模拟扳机同时保持，释放一项不覆盖其余项。"""
    client.set_stick('left', 0.5, -0.25)
    client.set_stick('right', -0.2, 0.3)
    client.set_trigger('left', 0.6)
    client.set_trigger('right', 0.8)
    client.press('xbox_a')
    client.press('xbox_dpad_up')
    assert client.state == GamepadState(frozenset({'south'}), frozenset({'dpad_up'}),
                                        (0.5, -0.25), (-0.2, 0.3), 0.6, 0.8)
    client.release('South')
    assert not client.state.buttons
    assert client.state.left_stick == (0.5, -0.25)
    assert client.state.right_trigger == 0.8
    client.reset()
    assert client.state == GamepadState()
    client.close()
    calls = records(fake_ojd[1])
    feeds = [item for item in calls if 'feed' in item.get('command', [])]
    assert len(feeds) == 1
    assert all(item['executable'] == str(fake_ojd[0]) for item in calls if 'command' in item)
    frames = [item['frame'] for item in calls if 'frame' in item]
    held = next(frame for frame in frames if frame['buttons'] == ['South'] and frame['dpad'])
    assert held['axes'] == {'LeftStickX': 0.5, 'LeftStickY': -0.25,
                            'RightStickX': -0.2, 'RightStickY': 0.3,
                            'LeftTrigger': 0.6, 'RightTrigger': 0.8}
    assert all(frame['holdMilliseconds'] == 8 for frame in frames)
    assert frames[-1]['buttons'] == frames[-1]['dpad'] == []
    assert not any(frames[-1]['axes'].values())
    assert calls[-1] == {'eof': True}


def test_old_deadline_cannot_release_new_press(client: OjdGamepadClient) -> None:
    """同键重新按下后，旧调用的期限和返回均不会释放新动作。"""
    timed = threading.Thread(target=client.press, args=('xbox_a', 0.06))
    timed.start()
    wait_for(lambda: 'south' in client.state.buttons)
    client.press('xbox_a')
    timed.join(timeout=1)
    assert not timed.is_alive()
    time.sleep(0.08)
    assert 'south' in client.state.buttons
    client.release('xbox_a')


def test_short_tap_preserves_100ms_when_cli_batches_frames(
    client: OjdGamepadClient, fake_ojd: tuple[Path, Path],
) -> None:
    """Windows 的 20ms 配置在 Mac 至少保持 100ms，批量读取也不能压成 8ms。"""
    client.set_key_press_time(0.02)
    assert client.key_press_time == 0.1
    client.tap('xbox_b')
    client.close()
    frames = [item['frame'] for item in records(fake_ojd[1]) if 'frame' in item]
    pressed = [frame for frame in frames if frame['buttons'] == ['East']]
    assert pressed and pressed[0]['holdMilliseconds'] == 100
    assert sum(frame['holdMilliseconds'] == 100 for frame in pressed) == 1
    assert all(frame['holdMilliseconds'] <= 100 for frame in frames)
    assert frames[-1]['buttons'] == []


def test_combo_reverse_release_and_stop_cancel_wait(
    client: OjdGamepadClient, fake_ojd: tuple[Path, Path],
) -> None:
    """组合逐项保持并逆序释放；stop 取消等待后不会按下下一项。"""
    client.tap_combo(['xbox_lb', 'xbox_a'])
    frames = [item['frame']['buttons'] for item in records(fake_ojd[1]) if 'frame' in item]
    unique = [value for index, value in enumerate(frames) if index == 0 or value != frames[index - 1]]
    assert unique == [[], ['LeftShoulder'], ['LeftShoulder', 'South'], ['LeftShoulder'], []]
    client.combo_press_time = 0.4
    combo = threading.Thread(target=client.tap_combo, args=(['xbox_lb', 'xbox_a'],))
    combo.start()
    wait_for(lambda: 'left_shoulder' in client.state.buttons)
    client.stop()
    combo.join(timeout=1)
    assert not combo.is_alive()
    assert client.state == GamepadState()


def test_disconnect_clears_and_reconnect_never_replays(
    client: OjdGamepadClient, fake_ojd: tuple[Path, Path],
) -> None:
    """连接丢失后拒绝动作，显式重连只发送中立状态。"""
    client.press('xbox_a')
    client.set_stick('left', 1, 0)
    assert client._process is not None
    client._process.kill()
    wait_for(lambda: not client.is_connected and client.state == GamepadState())
    with pytest.raises(OjdGamepadError):
        client.press('xbox_b')
    client.connect()
    assert client.state == GamepadState()
    client.close()
    calls = records(fake_ojd[1])
    feed_positions = [index for index, item in enumerate(calls) if 'feed' in item.get('command', [])]
    assert len(feed_positions) == 2
    new_frames = [item['frame'] for item in calls[feed_positions[-1] + 1:] if 'frame' in item]
    assert new_frames and all(not frame['buttons'] and not any(frame['axes'].values()) for frame in new_frames)


def test_suspend_rejects_late_actions_and_resume_is_neutral(client: OjdGamepadClient) -> None:
    """暂停打断旧动作，并拒绝迟到输入；恢复从中立状态开始。"""
    timed = threading.Thread(target=client.press, args=('xbox_a', 0.5))
    timed.start()
    wait_for(lambda: 'south' in client.state.buttons)
    client.suspend()
    timed.join(timeout=1)
    assert not timed.is_alive()
    for action in [lambda: client.press('xbox_a'), lambda: client.tap('xbox_a'),
                   lambda: client.set_stick('left', 1, 0),
                   lambda: client.set_trigger('left', 1)]:
        with pytest.raises(OjdGamepadError, match='暂停'):
            action()
    assert client.state == GamepadState()
    client.resume()
    assert client.state == GamepadState()
    client.press('xbox_b')
    assert client.state.buttons == frozenset({'east'})


def test_stopped_service_never_opens_feed(
    fake_ojd: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """status 退出零仍必须解析 Running，且不隐式启动服务。"""
    monkeypatch.setenv('FAKE_STATE', 'Stopped')
    adapter = OjdGamepadClient(str(fake_ojd[0]))
    with pytest.raises(OjdGamepadError, match='必须运行'):
        adapter.connect()
    assert len(records(fake_ojd[1])) == 2
    assert not adapter.is_connected
    assert adapter.state == GamepadState()
