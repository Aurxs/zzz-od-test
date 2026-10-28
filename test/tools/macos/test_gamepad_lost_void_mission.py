"""银色箭头造成边框缺口时仍核对完整卡片，不接受无边框的默认项。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.lost_void import GamepadLostVoidBackToWorld, GamepadLostVoidChooseMission


@pytest.mark.parametrize('highlighted', [True, False])
@pytest.mark.parametrize('filename', ['ios_purge_focus_gap.webp', 'ios_purge_focus_notification.webp'])
def test_purge_card_with_arrow_gap_requires_real_border(highlighted: bool, filename: str) -> None:
    image = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-入口-常规' / filename))
    operation = GamepadLostVoidChooseMission(SimpleNamespace(controller=Mock()), '战线肃清')
    operation.last_screenshot = image
    operation._after_round_wait = Mock()
    operation.check_and_update_current_screen = Mock(return_value=None)
    matches = MatchResultList()
    matches.append(MatchResult(1, 811, 118, 129, 42))
    crop = image[200:880, 100:1810] if highlighted else np.full_like(image[200:880, 100:1810], 100)
    operation.navigation._read_area = Mock(return_value=(crop, {'战线肃清': matches}))
    assert not operation.choose_mission().is_success
    assert not operation.choose_mission().is_success
    if highlighted:
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
    else:
        operation.ctx.controller.btn_tap.assert_not_called()


def test_back_from_mission_detail_returns_once_before_next_frame() -> None:
    operation = GamepadLostVoidBackToWorld(SimpleNamespace(controller=Mock()))
    operation.last_screenshot = object()
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.navigation._read_area = Mock(return_value=None)
    operation.check_and_update_current_screen = Mock(return_value='迷失之地-战线肃清')
    assert not operation.back().is_success
    assert not operation.back().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('east')


def test_return_closes_optional_broadcast_without_claiming() -> None:
    operation=GamepadLostVoidBackToWorld(SimpleNamespace(controller=Mock()))
    operation.last_screenshot=object()
    operation._after_round_wait=Mock()
    operation.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=False))
    def words(*texts: str) -> dict[str,MatchResultList]:
        result={}
        for text in texts:
            matches=MatchResultList()
            matches.append(MatchResult(1,10,10,100,30))
            result[text]=matches
        return result
    operation.navigation._read_area=Mock(side_effect=lambda screen,name:
        (None,words('全新放送','累计登录7天')) if name=='登录后-活动说明' else
        (None,words('B','返回')) if name=='登录后-活动按键' else None)
    assert not operation.back().is_success
    assert not operation.back().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('east')
    assert operation._sent=={'全新放送':1}


def test_unknown_return_frame_wait_is_bounded_and_sends_no_more_input() -> None:
    operation=GamepadLostVoidBackToWorld(SimpleNamespace(controller=Mock(),
        screen_loader=SimpleNamespace(get_area=Mock(return_value=None))))
    operation.last_screenshot=object()
    operation._after_round_wait=Mock()
    operation.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=False))
    operation.navigation._read_area=Mock(return_value=None)
    operation.check_and_update_current_screen=Mock(return_value=None)
    operation.save_screenshot=Mock()
    operation._sent={'零号空洞入口':1}
    for _ in range(4):
        assert not operation.back().is_fail
    assert operation.back().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()
