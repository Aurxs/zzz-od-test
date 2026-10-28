"""功能卡片的圆角和线宽变化不能当成焦点丢失。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.transport import find_yellow_focus_frames


@pytest.mark.parametrize('filename', ['ios_management_function.webp', 'ios_management_focus_pulse.webp'])
def test_real_function_card_focus_survives_line_width_change(filename: str) -> None:
    path = Path(__file__).resolve().parents[3] / 'screens' / '预备编队' / filename
    image = cv2_utils.read_image(str(path))[275:960, 1250:1800]
    frames = find_yellow_focus_frames(image, 100, 175, 100, 180, min_edge_presence=0.65)
    assert len(frames) == 1
    assert frames[0].y1 > 450


def test_open_bottom_edge_is_not_a_focus_frame() -> None:
    image = np.zeros((180, 180, 3), dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (145, 155), (255, 255, 0), 4)
    image[148:] = 0
    assert not find_yellow_focus_frames(image, 100, 175, 100, 180, min_edge_presence=0.65)
