"""抽奖机按实际分子确认机会，开始不连按，归零后返回。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.lost_void_lottery import GamepadLostVoidLottery


def operation_with_count(text: str) -> GamepadLostVoidLottery:
    image = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-抽奖机' / 'ios_one_remaining.webp'))
    words = {}
    for name, rect in [('A', (33, 36, 47, 44)), (text, (139, 37, 167, 45))]:
        matches = MatchResultList()
        matches.append(MatchResult(1, *rect))
        words[name] = matches
    operation = GamepadLostVoidLottery(SimpleNamespace(
        controller=Mock(), lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)),
    ))
    operation.last_screenshot = image
    operation._read_area = Mock(return_value=(image[880:1010, 760:1165], words))
    operation.check_and_update_current_screen = Mock(return_value='迷失之地-抽奖机')
    operation._after_round_wait = Mock()
    return operation


@pytest.mark.parametrize(('text', 'button'), [('开始1/1', 'south'), ('开始0/1', 'east'), ('开始1/2', None), ('开始1000', None)])
def test_count_numerator_controls_start_or_return(text: str, button: str | None) -> None:
    operation = operation_with_count(text)
    result = operation.use_remaining()
    if button is None:
        assert result.is_fail
        operation.ctx.controller.btn_tap.assert_not_called()
    else:
        operation.ctx.controller.btn_tap.assert_called_once_with(button)
        assert not result.is_success
    if button == 'east':
        operation.ctx.lost_void.in_normal_world.return_value = True
        assert operation.use_remaining().is_success
        operation.ctx.controller.btn_tap.assert_called_once_with('east')


def test_start_does_not_repeat_when_same_counter_remains(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_lottery as module

    operation = operation_with_count('开始1/1')
    common = Mock()
    common.can_handle.return_value = False
    monkeypatch.setattr(module, 'GamepadLostVoidChooseCommon', lambda ctx: common)
    operation._known_reward_visible = Mock(return_value=False)
    now = [100]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    assert not operation.use_remaining().is_success
    assert not operation.use_remaining().is_success
    now[0] = 109
    assert operation.use_remaining().is_fail
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
