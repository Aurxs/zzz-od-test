"""用实拍画面与当帧 OCR 快照验证手柄快捷手册，不发送真实输入。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.focus import (
    find_yellow_frames,
    has_filled_highlight,
    text_inside_frame,
)
from zzz_od.operation.gamepad.transport_by_compendium import (
    GamepadTransportByCompendium,
)

SCREENS = Path(__file__).resolve().parents[3] / 'screens' / '快捷手册'
AREAS = {
    ('快捷手册', '手柄-顶部标签'): Rect(700, 115, 1645, 205),
    ('快捷手册', '手柄-分类列表'): Rect(160, 300, 440, 925),
    ('快捷手册', '手柄-副本列表'): Rect(470, 245, 1690, 955),
    ('菜单', '手柄-确认弹窗'): Rect(600, 460, 1300, 760),
    ('菜单', '手柄-确认按钮'): Rect(960, 585, 1255, 665),
}


class FrameOcr:
    """只回放真实帧的文字框，颜色及轮廓仍由实拍图计算。"""

    def __init__(self) -> None:
        """加载归档快照，初始不返回任何文字。"""
        self.metadata: dict[str, list[dict[str, str | int]]] = json.loads(
            (SCREENS / 'ios_gamepad_ocr.json').read_text(encoding='utf-8')
        )
        self.state: str = ''

    def crop_and_run_ocr(
        self, image: np.ndarray, rect: Rect
    ) -> dict[str, MatchResultList]:
        """按请求区域返回局部坐标，与运行时 OCR 接口一致。"""
        results: dict[str, MatchResultList] = {}
        for item in self.metadata.get(self.state, []):
            x, y = int(item['x']), int(item['y'])
            width, height = int(item['width']), int(item['height'])
            if not (rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2):
                continue
            matches = MatchResultList()
            matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
            results[str(item['text'])] = matches
        return results


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadTransportByCompendium:
    """构造严格的假输入接口，并省去节点动画等待。"""
    monkeypatch.setattr(GamepadTransportByCompendium, '_after_round_wait', Mock())
    loader = Mock()
    loader.get_area.side_effect = lambda screen, area: SimpleNamespace(rect=AREAS[(screen, area)])
    ctx = SimpleNamespace(
        controller=Mock(spec=['click', 'btn_tap']),
        screen_loader=loader,
        ocr=FrameOcr(),
        run_context=Mock(),
        current_instance_idx=2,
    )
    return GamepadTransportByCompendium(ctx, '训练', '实战模拟室', '基础材料')


def set_frame(operation: GamepadTransportByCompendium, state: str) -> None:
    """切换到对应归档图和 OCR 快照。"""
    operation.ctx.ocr.state = state
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    assert operation.last_screenshot is not None


def test_real_frames_distinguish_category_fill_from_mission_frame() -> None:
    """同样显示基础材料时，只有整行边框才算右列表焦点。"""
    category = cv2_utils.read_image(str(SCREENS / 'ios_training_simulation_category.webp'))
    focused = cv2_utils.read_image(str(SCREENS / 'ios_training_basic_focus.webp'))
    assert has_filled_highlight(category, Rect(1144, 142, 1206, 177), 'yellow')
    assert has_filled_highlight(category, Rect(228, 453, 377, 490), 'blue')
    assert not has_filled_highlight(category, Rect(242, 344, 362, 380), 'blue')
    assert not find_yellow_frames(category[245:955, 470:1690])
    frames = find_yellow_frames(focused[245:955, 470:1690])
    assert text_inside_frame(Rect(67, 110, 196, 149), frames)
    assert not text_inside_frame(Rect(67, 310, 196, 349), frames)


def test_navigation_confirms_each_frame_before_next_input(
    operation: GamepadTransportByCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """从大世界打开后回放到传送弹窗，重复同帧不再连按 A。"""
    assert operation.check_target().is_success
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_success()))
    assert not operation.open_compendium().is_success
    assert not operation.open_compendium().is_success
    operation.ctx.controller.click.assert_called_once_with(gamepad_key='compendium')
    set_frame(operation, 'ios_daily')
    assert operation.open_compendium().is_success
    assert not operation.choose_training().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('right_shoulder')
    set_frame(operation, 'ios_training_default')
    assert operation.choose_training().is_success
    assert not operation.choose_simulation().is_success
    set_frame(operation, 'ios_training_simulation_category')
    assert operation.choose_simulation().is_success
    assert not operation.choose_basic_material().is_success
    assert not operation.choose_basic_material().is_success
    set_frame(operation, 'ios_training_basic_focus')
    assert operation.choose_basic_material().is_success
    assert not operation.request_teleport().is_success
    assert not operation.request_teleport().is_success
    set_frame(operation, 'ios_teleport_confirm')
    assert operation.request_teleport().is_success
    assert operation.confirm_teleport().is_success
    assert operation.confirm_teleport().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [
        call('right_shoulder'), call('dpad_down'),
        call('south'), call('south'), call('south'),
    ]
    operation.ctx.controller.click.assert_called_once_with(gamepad_key='compendium')


def test_unknown_target_and_missing_confirm_focus_send_no_input(
    operation: GamepadTransportByCompendium,
) -> None:
    """未支持目标及未高亮的确认按钮均不能继续确认。"""
    operation.mission_type_name = '代理人晋升'
    assert operation.check_target().is_fail
    set_frame(operation, 'ios_teleport_confirm')
    # 保留弹窗与确认文字快照，只去掉按钮图像高亮，验证不能仅凭文字按 A。
    operation.last_screenshot[585:665, 960:1255] = 0
    assert not operation.confirm_teleport().is_success
    operation.ctx.ocr.state = ''
    assert not operation.choose_training().is_success
    assert not operation.choose_simulation().is_success
    operation.last_screenshot = None
    assert not operation.open_compendium().is_success
    assert not operation.wait_for_simulation().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.controller.click.assert_not_called()


def test_opening_is_not_recorded_when_controller_rejects_input(
    operation: GamepadTransportByCompendium, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """采集保护临时拒绝动作时不标成已打开，恢复后仍能重试。"""
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_success()))
    operation.ctx.controller.click.return_value = False
    assert not operation.open_compendium().is_success
    assert not operation._opened
    operation.ctx.controller.click.return_value = True
    assert not operation.open_compendium().is_success
    assert operation._opened
    assert not operation.open_compendium().is_success
    assert operation.ctx.controller.click.call_count == 2


def test_destination_requires_both_anchors(
    operation: GamepadTransportByCompendium, monkeypatch: pytest.MonkeyPatch
) -> None:
    """确认框消失或只有一个入口文字不能算传送成功。"""
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    find_area = Mock(side_effect=[
        operation.round_retry(), operation.round_retry(),
        operation.round_success(), operation.round_retry(),
        operation.round_success(), operation.round_success(),
    ])
    monkeypatch.setattr(operation, 'round_by_find_area', find_area)
    assert not operation.wait_for_simulation().is_success
    assert not operation.wait_for_simulation().is_success
    assert operation.wait_for_simulation().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
