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


@pytest.mark.parametrize(('target', 'old_focus', 'old_row', 'first', 'direction', 'expected_row'), [(6, 4, 2, 2, 'dpad_down', 3), (18, 0, 0, 14, 'dpad_up', 9)])
def test_focus_paging_counts_only_confirmed_overlap(operation: GamepadChoosePredefinedTeam, monkeypatch: pytest.MonkeyPatch, target: int, old_focus: int, old_row: int, first: int, direction: str, expected_row: int) -> None:
    """翻页保留四张重叠卡才累计行号，无反馈不假定已到目标。"""
    from zzz_od.operation.gamepad import predefined_team as module

    op = module.GamepadFocusPredefinedTeam(operation.ctx, target)
    op.last_screenshot = operation.last_screenshot
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock(return_value='focus'))
    areas = [op.ctx.screen_loader.get_area('编队选择', f'编队槽位{i}') for i in range(6)]
    old_names = tuple(f'队{i}' for i in range(6))
    names = tuple(f'队{i}' for i in range(first, first + 6))
    op._at_top = True
    op._row = old_row
    op._previous = (old_focus, old_names)
    op._pending = direction
    monkeypatch.setattr(module, 'find_yellow_focus_frames', lambda *args: [areas[4]])
    monkeypatch.setattr(module, 'find_team_name', lambda words, rect: names[next(i for i, a in enumerate(areas) if a.rect == rect)])
    op.ctx.ocr = SimpleNamespace(run_ocr=lambda screen: {'预备出战': []})
    result = op.focus_team()
    assert result.is_success
    assert result.data['visible_slot'] == 4
    assert op._row == expected_row
    op.ctx.controller.btn_tap.assert_not_called()


def test_focus_unchanged_page_does_not_advance(operation: GamepadChoosePredefinedTeam, monkeypatch: pytest.MonkeyPatch) -> None:
    """丢失方向键反馈时既不累加行号，也不确认选队。"""
    from zzz_od.operation.gamepad import predefined_team as module

    op = module.GamepadFocusPredefinedTeam(operation.ctx, 6)
    op.last_screenshot = operation.last_screenshot
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    areas = [op.ctx.screen_loader.get_area('编队选择', f'编队槽位{i}') for i in range(6)]
    names = tuple(f'队{i}' for i in range(6))
    op._at_top = True
    op._row = 2
    op._previous = (4, names)
    op._pending = 'dpad_down'
    monkeypatch.setattr(module, 'find_yellow_focus_frames', lambda *args: [areas[4]])
    monkeypatch.setattr(module, 'find_team_name', lambda words, rect: names[next(i for i, a in enumerate(areas) if a.rect == rect)])
    op.ctx.ocr = SimpleNamespace(run_ocr=lambda screen: {'预备出战': []})
    assert not op.focus_team().is_success
    assert op._row == 2
    op.ctx.controller.btn_tap.assert_not_called()

    for _ in range(5):
        result = op.focus_team()
    assert result.is_fail
    assert op._row == 2


def test_seventh_team_uses_located_slot(operation: GamepadChoosePredefinedTeam) -> None:
    """第七队位于翻页后左上槽位，核对其成员而非第一队。"""
    operation.target_team_idx = 6
    operation._visible_slot = 0
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / 'macos_page_team_seven.webp'))
    operation.ctx.team_config.get_team_by_idx = lambda idx: SimpleNamespace(agent_id_list=['hoshimi_miyabi', 'nangongyu', 'yuzuha'])
    assert operation.choose().is_success
    assert operation._verified_members == ['hoshimi_miyabi', 'nangongyu', 'yuzuha']
    operation.ctx.controller.btn_tap.assert_called_once_with('start')
