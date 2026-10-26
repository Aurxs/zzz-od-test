"""手柄武备列表恢复与初始同名确认的最小输入边界。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.operation.gamepad.lost_void_gear import GamepadLostVoidChooseGear


def words(text: str, x: int, y: int, width: int = 80, height: int = 30) -> dict[str, MatchResultList]:
    matches = MatchResultList()
    matches.append(MatchResult(1, x, y, width, height))
    return {text: matches}


def test_gear_confirmation_requires_same_target_and_confirms_only_once() -> None:
    ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)), controller=Mock())
    operation = GamepadLostVoidChooseGear(ctx)
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image = np.zeros((360, 820, 3), dtype=np.uint8)
    image[260:340, 450:700] = (190, 215, 0)
    ocr = words('确认选择[绝境]战斗维生包作为初始武备吗？', 100, 60, 600)
    ocr.update(words('确认', 520, 290))
    operation.navigation._read_area = Mock(return_value=(image, ocr))
    operation._after_round_wait = Mock()
    operation._target = '[终结]其他武备'
    assert operation.choose().is_fail
    ctx.controller.btn_tap.assert_not_called()
    operation._target = '[绝境]战斗维生包'
    assert not operation.choose().is_success
    assert not operation.choose().is_success
    ctx.controller.btn_tap.assert_called_once_with('south')
    assert operation._equipped


def test_gear_scan_homes_before_recording_first_slot() -> None:
    import cv2
    from one_dragon.base.geometry.rectangle import Rect
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.circle(frame, (580, 985), 66, (190, 215, 0), 4)
    ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)), controller=Mock(),
                          screen_loader=SimpleNamespace(get_area=Mock(return_value=SimpleNamespace(rect=Rect(190,892,1740,1072)))))
    operation = GamepadLostVoidChooseGear(ctx)
    operation.last_screenshot = frame
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    operation.navigation._read_area = lambda screen, name: (
        (frame[892:1072,190:1740], {}) if name == '武备列表' else
        (frame[459:567,452:1504], words('[携游]敕令玄幡', 25, 60, 250)) if name == '武备名称' else None
    )
    operation.parser._find_gears_with_status = Mock(return_value=([],SimpleNamespace(
        get_absolute_rect_pairs=lambda: [(None,(210,920,340,1050)),(None,(515,920,645,1050))])))
    assert not operation.choose().is_success
    assert operation._first_name is None and not operation._candidates
    ctx.controller.btn_tap.assert_called_once_with('dpad_left')

