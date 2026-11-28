"""验证柜台交互只发送给当前双箭头内的目标。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad import shop_approach


def test_dialogue_name_needs_both_points_facing_inward() -> None:
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    text = Rect(60, 43, 160, 73)
    left = np.array([(65, 50), (79, 58), (65, 66)])
    right = np.array([(155, 50), (141, 58), (155, 66)])
    assert not shop_approach.has_interaction_arrows(image, text)
    cv2.fillConvexPoly(image, left, (255, 255, 255))
    assert not shop_approach.has_interaction_arrows(image, text)
    cv2.fillConvexPoly(image, right, (255, 255, 255))
    assert shop_approach.has_interaction_arrows(image, text)
    assert shop_approach.has_interaction_arrows(image, Rect(51, 43, 146, 73))


def test_visible_but_unfocused_clerk_does_not_interact(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = Mock(standard_width=1920)
    loader = Mock()
    loader.get_area.return_value = SimpleNamespace(rect=Rect(140, 120, 1810, 800))
    operation = shop_approach.GamepadApproachShop(
        SimpleNamespace(controller=controller, screen_loader=loader, run_context=Mock()), '18号',
    )
    image = np.zeros((120, 1440, 3), dtype=np.uint8)
    operation.last_screenshot = image
    operation.last_screenshot_time = 1
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    world = Mock(return_value=operation.round_success())
    monkeypatch.setattr(operation, 'round_by_find_area', world)
    monkeypatch.setattr(operation, '_target', lambda: (image, Rect(1060, 43, 1160, 73)))
    monkeypatch.setattr(operation, '_interact_ready', lambda: True)
    evidence = Mock(return_value='saved')
    monkeypatch.setattr(shop_approach, 'save_shop_frame', evidence)

    operation.approach()
    operation.approach()
    controller.move_camera.assert_called_once()
    controller.interact.assert_not_called()

    operation.last_screenshot_time = 2
    monkeypatch.setattr(shop_approach, 'has_interaction_arrows', lambda *_: True)
    operation.approach()
    operation.approach()
    controller.interact.assert_called_once()
    evidence.assert_called_once()
    world.return_value = operation.round_retry()
    assert operation.approach().is_success


@pytest.mark.parametrize(('state', 'label'), [
    ('outlined', Rect(793, 258, 880, 283)),
    ('before', Rect(798, 190, 861, 212)),
])
def test_coffee_real_frames_interact_once_without_extra_movement(
    monkeypatch: pytest.MonkeyPatch, state: str, label: Rect,
) -> None:
    """新帧箭头宽端有黑描边，仍须和旧帧一样核对双箭头与绿色A。"""
    target_area = Rect(140, 120, 1810, 800)
    ready_area = Rect(1410, 1010, 1498, 1065)
    matches = MatchResultList()
    matches.append(MatchResult(1, label.x1, label.y1, label.width, label.height))
    loader = SimpleNamespace(get_area=lambda _screen, name: SimpleNamespace(
        rect=target_area if name == '手柄-附近互动目标' else ready_area,
    ))
    controller = Mock(standard_width=1920)
    ctx = SimpleNamespace(
        controller=controller, screen_loader=loader, run_context=Mock(),
        ocr=SimpleNamespace(crop_and_run_ocr=lambda *_args: {'咖啡店': matches}),
    )
    operation = shop_approach.GamepadApproachShop(ctx, '咖啡店')
    path = Path(__file__).resolve().parents[3] / f'screens/咖啡店/ios_liufen_coffee_interaction_{state}.webp'
    operation.last_screenshot = cv2_utils.read_image(str(path))
    operation.last_screenshot_time = 1
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_success()))
    monkeypatch.setattr(shop_approach, 'save_shop_frame', Mock(return_value='saved'))
    assert operation._interact_ready()
    assert shop_approach.has_interaction_arrows(operation._target()[0], label)
    operation.approach()
    operation.approach()
    controller.interact.assert_called_once_with(press=True, press_time=0.2, release=True)
    controller.move_w.assert_not_called()
    controller.move_camera.assert_not_called()


def test_outward_arrow_pair_is_still_rejected() -> None:
    """扩大边带只容描边，不把向外箭头当交互焦点。"""
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    cv2.fillConvexPoly(image, np.array([(79, 50), (65, 58), (79, 66)]), (255, 255, 255))
    cv2.fillConvexPoly(image, np.array([(141, 50), (155, 58), (141, 66)]), (255, 255, 255))
    assert not shop_approach.has_interaction_arrows(image, Rect(60, 43, 160, 73))
