"""真实编队截图回放，不创建手柄或操作游戏。"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.predefined_team import GamepadChoosePredefinedTeam

SCREENS = Path(__file__).resolve().parents[3] / 'screens' / '预备编队'


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> Iterator[GamepadChoosePredefinedTeam]:
    """原模板和本地 OCR，输入与证据写盘替换为假对象。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    ctx = SimpleNamespace(
        ocr=ocr, screen_loader=loader, template_loader=TemplateLoader(),
        controller=Mock(spec=['btn_tap']), run_context=Mock(),
        team_config=SimpleNamespace(get_team_by_idx=lambda idx: SimpleNamespace(
            agent_id_list=['yeshunguang', 'zhao', 'sunna'],
        )),
    )
    op = GamepadChoosePredefinedTeam(ctx, 0)
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock(return_value='team_evidence'))
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'macos_teams_list_1792983731975.webp'))
    yield op
    ocr.cleanup()


def test_selected_team_confirms_without_toggling_a(operation: GamepadChoosePredefinedTeam) -> None:
    """识别原头像与 SELECTED 后仅按 Start，避免 A 把已有选择取消。"""
    assert operation.choose().is_success
    assert operation._verified_members == ['yeshunguang', 'zhao', 'sunna']
    operation.ctx.controller.btn_tap.assert_called_once_with('start')


def test_changed_team_members_block_confirmation(operation: GamepadChoosePredefinedTeam) -> None:
    """游戏已换队但 GUI 仍是旧成员时不误选。"""
    operation.ctx.team_config.get_team_by_idx = lambda idx: SimpleNamespace(agent_id_list=['unknown'] * 3)
    assert operation.choose().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()
