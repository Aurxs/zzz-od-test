"""银色箭头造成边框缺口时仍核对完整卡片，不接受无边框的默认项。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.lost_void import (
    GamepadLostVoidBackToWorld,
    GamepadLostVoidChooseMission,
    GamepadLostVoidTransport,
)


@pytest.mark.parametrize('highlighted', [True, False])
@pytest.mark.parametrize('filename', ['ios_purge_focus_gap.webp', 'ios_purge_focus_notification.webp', 'ios_purge_focus_animated_gap.webp'])
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


@pytest.mark.parametrize('edge', ['left', 'top'])
def test_mission_focus_requires_both_horizontal_and_vertical_edges(edge: str) -> None:
    """局部遮挡可以保留焦点，整条边缺失不能靠装饰金条补成卡片。"""
    image = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens'
                                    / '迷失之地-入口-常规/ios_purge_focus_animated_gap.webp'))
    crop = image[200:880, 100:1810].copy()
    if edge == 'left':
        crop[95:325, 605:635] = 0
    else:
        crop[95:125, 605:1150] = 0
    assert GamepadLostVoidChooseMission._find_mission_frames(crop) == []


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


@pytest.mark.parametrize(('stop_at_hollow', 'focus'), [(True, '迷失之地'), (True, '枯萎之都'), (False, '迷失之地')])
def test_hollow_transport_stops_at_hub_only_when_requested(stop_at_hollow: bool, focus: str) -> None:
    """公共入口由两张玩法卡共同确认，普通迷失之地仍走原确认。"""
    operation = GamepadLostVoidTransport(SimpleNamespace(controller=Mock()), stop_at_hollow=stop_at_hollow)
    operation.last_screenshot = object()
    operation._after_round_wait = Mock()
    operation._update_notice = Mock(return_value=False)
    operation._entry_name = Mock(return_value=None)
    operation.save_screenshot = Mock(return_value='入口截图')
    labels = {
        '手柄-调查标签': ('深层调查',),
        '手柄-迷失之地入口': ('迷失之地', 'A') if focus == '迷失之地' else ('迷失之地',),
        '手柄-枯萎之都入口': ('枯萎之都', 'A') if focus == '枯萎之都' else ('枯萎之都',),
    }
    match = SimpleNamespace(max=SimpleNamespace(rect=object()))
    operation.navigation._read_area = Mock(side_effect=lambda _, area: (
        None, dict.fromkeys(labels[area], match),
    ))
    result = operation.wait_entry()
    if stop_at_hollow:
        assert result.is_success
        assert result.data == {'screenshot': '入口截图'}
        operation.ctx.controller.btn_tap.assert_not_called()
    else:
        assert not result.is_success
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
