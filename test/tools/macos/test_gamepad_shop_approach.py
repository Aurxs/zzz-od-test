"""验证柜台交互只发送给当前双箭头内的目标。"""

from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
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
