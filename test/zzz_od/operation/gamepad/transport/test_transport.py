"""用地图实拍框和 OCR 快照验证手柄导航，不连接游戏。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.base.controller.gamepad_input import normalize_gamepad_key
from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.config.game_config import GameConfig
from zzz_od.operation.gamepad.transport import GamepadTransport

SCREENS = Path(__file__).resolve().parents[5] / 'screens'
AREAS: dict[str, Rect] = {
    '手柄-区域卡片': Rect(0, 95, 1920, 930),
    '手柄-传送点卡片': Rect(55, 928, 1865, 1075),
    '手柄-传送确认主句': Rect(800, 490, 1140, 570),
    '手柄-传送确认按钮': Rect(970, 595, 1255, 660),
}


class FrameOcr:
    """仅回放当前实拍帧文字；轮廓与填充从图像计算。"""

    def __init__(self) -> None:
        """加载地图代表帧 OCR 快照。"""
        self.state: str = ''
        self.metadata: dict = json.loads(
            (SCREENS / '地图' / 'ios_gamepad_ocr.json').read_text(encoding='utf-8')
        )

    def crop_and_run_ocr(self, image: object, rect: Rect) -> dict[str, MatchResultList]:
        """把全图文字框转换为请求区域内的局部坐标。"""
        result: dict[str, MatchResultList] = {}
        for item in self.metadata.get(self.state, []):
            x, y, width, height = (item[key] for key in ('x', 'y', 'width', 'height'))
            if rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2:
                matches = result.setdefault(item['text'], MatchResultList())
                matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
        return result


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadTransport:
    """使用严格假控制器，单次节点调用跳过实际动画等待。"""
    monkeypatch.setattr(GamepadTransport, '_after_round_wait', Mock())
    loader = Mock()
    loader.get_area.side_effect = lambda screen, area: SimpleNamespace(rect=AREAS[area])
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap', 'click']),
        ocr=FrameOcr(), screen_loader=loader, run_context=Mock(),
    )
    op = GamepadTransport(ctx, '澄辉坪', '阿朔')
    monkeypatch.setattr(op, 'round_by_find_area', lambda *args: (
        op.round_success() if ctx.ocr.state == 'ios_ashuo_arrived' else op.round_retry()
    ))
    return op


def set_frame(operation: GamepadTransport, state: str) -> None:
    """切换同一操作当前实拍状态。"""
    operation.ctx.ocr.state = state
    folder = '大世界-普通' if state == 'ios_ashuo_arrived' else '地图'
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / folder / f'{state}.webp'))
    assert operation.last_screenshot is not None


def test_real_map_frames_navigate_regions_then_points_once(
    operation: GamepadTransport,
) -> None:
    """初始焦点来自图像，双框同时高亮时仍正确选择阿朔小框。"""
    assert operation.check_target().is_success
    set_frame(operation, 'ios_ashuo_arrived')
    assert not operation.open_map().is_success
    assert not operation.open_map().is_success
    operation.ctx.controller.click.assert_called_once_with(gamepad_key='map')
    set_frame(operation, 'ios_map_initial')
    assert operation.open_map().is_success
    assert not operation.choose_area().is_success
    assert not operation.choose_area().is_success
    set_frame(operation, 'ios_map_chenghui')
    assert operation._focus(True) is None
    assert not operation.choose_area().is_success
    assert not operation.choose_area().is_success
    set_frame(operation, 'ios_map_point_focus')
    assert operation.choose_area().is_success
    assert not operation.choose_point().is_success
    assert not operation.choose_point().is_success
    set_frame(operation, 'ios_map_ashuo_focus')
    assert operation.choose_area().is_success
    assert operation.choose_point().is_success
    assert not operation.request_teleport().is_success
    assert not operation.request_teleport().is_success
    set_frame(operation, 'ios_map_confirm')
    assert operation.request_teleport().is_success
    assert operation.confirm_teleport().is_success
    assert operation.confirm_teleport().is_success
    assert not operation.wait_for_world().is_success
    set_frame(operation, 'ios_ashuo_arrived')
    assert operation.wait_for_world().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [
        call('dpad_left'), call('south'), call('dpad_right'), call('south'), call('south'),
    ]


def test_unknown_target_unrequested_dialog_and_missing_focus_send_nothing(
    operation: GamepadTransport,
) -> None:
    """未支持目标、不明弹窗和未知页均不触发输入。"""
    operation.tp_name = '随便观'
    assert operation.check_target().is_fail
    set_frame(operation, 'ios_map_confirm')
    assert operation.open_map().is_fail
    assert operation.choose_area().is_fail
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.ctx.ocr.state = ''
    assert not operation.open_map().is_success
    assert not operation.choose_area().is_success
    assert not operation.choose_point().is_success
    assert not operation.request_teleport().is_success
    assert not operation.confirm_teleport().is_success
    assert not operation.wait_for_world().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.controller.click.assert_not_called()


def test_map_action_exists_in_default_game_configuration(
    operation: GamepadTransport,
) -> None:
    """打开地图的实际动作名必须存在于默认配置，并能转换成原生手柄键。"""
    config = GameConfig.__new__(GameConfig)
    YamlOperator.__init__(config)
    actions = config.get_gamepad_action_keys('xbox')
    set_frame(operation, 'ios_ashuo_arrived')
    assert not operation.open_map().is_success
    action = operation.ctx.controller.click.call_args.kwargs['gamepad_key']
    assert action in actions
    assert [normalize_gamepad_key(key) for key in actions[action]] == ['dpad_right']


def test_invisible_names_and_unhighlighted_confirm_do_not_guess(
    operation: GamepadTransport,
) -> None:
    """目标不可见不翻页；保留确认文字而去掉填充也不能按 A。"""
    set_frame(operation, 'ios_map_chenghui')
    operation.area_name = '光映广场'
    assert operation.choose_area().is_fail
    set_frame(operation, 'ios_map_point_focus')
    operation.tp_name = '报刊亭'
    assert operation.choose_point().is_fail
    set_frame(operation, 'ios_map_confirm')
    operation.last_screenshot[595:660, 970:1255] = 0
    assert not operation.confirm_teleport().is_success
    operation.ctx.controller.btn_tap.assert_not_called()


def test_map_can_return_from_other_regions_point_layer(
    operation: GamepadTransport,
) -> None:
    """底部保留上次焦点时只按一次 B 返回区域层。"""
    set_frame(operation, 'ios_map_point_focus')
    operation.area_name = '六分街'
    assert not operation.choose_area().is_success
    assert not operation.choose_area().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('east')
