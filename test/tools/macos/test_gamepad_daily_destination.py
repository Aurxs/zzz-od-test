"""验证三处日常地点复用地图选择，未知地点保持拦截。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from zzz_od.operation.gamepad.transport import GamepadTransport


@pytest.mark.parametrize(('area', 'target'), [
    ('六分街', '报刊亭'),
    ('六分街', '咖啡店'),
    ('录像店', '柜台'),
])
def test_daily_target_requires_its_exact_label(monkeypatch: pytest.MonkeyPatch, area: str, target: str) -> None:
    """把同一区域内其他传送点的当前焦点与目标区分开。"""
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = GamepadTransport(ctx, area, target)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    assert operation.check_target().is_success

    matches = MatchResultList()
    matches.append(MatchResult(1, 30, 40, 60, 25))
    ocr = {target + '附近': matches}
    focus = Rect(0, 0, 280, 120)
    monkeypatch.setattr(operation, '_focus', lambda _: (focus, ocr))
    monkeypatch.setattr(operation, '_teleport_dialog', lambda: False)
    assert operation.choose_point().is_fail
    assert not operation.request_teleport().is_success
    ctx.controller.btn_tap.assert_not_called()

    ocr[target] = matches
    assert operation.choose_point().is_success
    operation.request_teleport()
    operation.request_teleport()
    ctx.controller.btn_tap.assert_called_once_with('south')


def test_daily_function_option_leaves_room_for_map_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """选配直接进入功能页时，确认按钮下移，仍只发送一次 A。"""
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    title = Rect(830, 478, 1070, 512)
    confirm = Rect(1100, 647, 1164, 674)

    def ocr(_: np.ndarray, rect: Rect) -> dict[str, MatchResultList]:
        words: dict[str, MatchResultList] = {}
        for name, line in (('是否传送至该地点？', title), ('确认', confirm)):
            if rect.x1 <= line.x1 < line.x2 <= rect.x2 and rect.y1 <= line.y1 < line.y2 <= rect.y2:
                matches = MatchResultList()
                matches.append(MatchResult(1, line.x1 - rect.x1, line.y1 - rect.y1, line.width, line.height))
                words[name] = matches
        return words

    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), screen_loader=loader,
                          ocr=SimpleNamespace(crop_and_run_ocr=ocr))
    operation = GamepadTransport(ctx, '六分街', '报刊亭')
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.last_screenshot[626:690, 974:1253] = (160, 193, 55)
    assert operation.confirm_teleport().is_success
    assert operation.confirm_teleport().is_success
    ctx.controller.btn_tap.assert_called_once_with('south')
