"""局内会谈的原始 A 图标与目标行约束。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from cv2.typing import MatLike
    from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.dialog import GamepadChooseDialogOption


@pytest.mark.parametrize('option', ['我没有遇见过师父', '好'])
def test_local_prompt_threshold_keeps_highlight_and_same_row_required(option: str) -> None:
    path = Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-大世界' / 'ios_talk_option_a.webp'
    frame = cv2_utils.read_image(str(path))
    target = MatchResultList()
    target.append(MatchResult(1, 140, 162, 181, 28))
    other = MatchResultList()
    other.append(MatchResult(1, 140, 242, 182, 27))
    ctx = SimpleNamespace(
        screen_loader=SimpleNamespace(get_area=Mock(return_value=SimpleNamespace(rect=Rect(1340, 490, 1920, 815)))),
        tm=TemplateMatcher(TemplateLoader()),
        ocr=SimpleNamespace(crop_and_run_ocr=Mock(return_value={option: target, '绝口不提师父行踪': other})),
        controller=Mock(),
    )
    operation = GamepadChooseDialogOption(ctx, option, prompt_threshold=0.8)
    operation.last_screenshot = frame
    operation.screenshot = Mock()
    operation._save = Mock(return_value=True)
    operation._after_round_wait = Mock()
    assert operation.choose_option().status == '等待对话选项关闭'
    ctx.controller.btn_tap.assert_called_once_with('south')
    # 保留其他任务的原阈值；同一行图标消失时不能仅靠高亮继续。
    assert GamepadChooseDialogOption(ctx, '其他任务').prompt_threshold == 0.85
    ctx.controller.reset_mock()
    operation._confirm_attempts = 0
    operation.last_screenshot = frame.copy()
    operation.last_screenshot[635:700, 1370:1425] = 0
    assert operation.choose_option().is_fail
    ctx.controller.btn_tap.assert_not_called()


def _short_dialog_operation(text: str) -> tuple["GamepadLostVoidRunLevel", "MatLike"]:
    """实拍面板和A图标，台词可任意替换或OCR漏读。"""
    from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel
    frame = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-大世界' / 'ios_dialog_short.webp'))
    words = MatchResultList()
    words.append(MatchResult(1, 530, 130, 90, 30))
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(
        controller=Mock(), lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)),
        screen_loader=SimpleNamespace(get_area=lambda screen, name: SimpleNamespace(rect=Rect(390, 780, 1530, 1040)) if name == '手柄-对话框' else None),
        ocr=SimpleNamespace(crop_and_run_ocr=Mock(return_value={text: words} if text else {})),
    )
    matcher = TemplateMatcher(TemplateLoader())
    operation.round_by_find_area = lambda image, *args: SimpleNamespace(is_success=matcher.match_template(
        image[971:1027, 1455:1511], 'ios_gamepad', 'lost_void_dialog_a', threshold=0.85,
    ).max is not None)
    operation.round_wait = lambda status, **kwargs: status
    operation.round_fail = lambda status: status
    operation.save_screenshot = Mock()
    operation.last_screenshot_time = 100
    operation._dialog_frame_time = -1
    operation._dialog_sent_at = 0
    operation._dialog_text = None
    operation._dialog_repeats = 0
    return operation, frame


def test_dialogue_structure_accepts_short_punctuation_and_missing_ocr() -> None:
    for text in ('绳匠。', '嗯', '……', '', '任意陌生角色的长台词'):
        operation, frame = _short_dialog_operation(text)
        assert '推进局内对话' in operation.try_talk(frame)
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
        assert operation.try_talk(frame) == '等待对话推进后的新帧'
        operation.ctx.controller.btn_tap.assert_called_once()


def test_dialogue_needs_panel_and_prompt_and_stops_unchanged_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_run_level as module
    operation, frame = _short_dialog_operation('绳匠。')
    no_prompt = frame.copy()
    no_prompt[971:1027, 1455:1511] = 0
    assert operation.try_talk(no_prompt) is None
    no_panel = frame.copy()
    no_panel[840:1020, 410:1440] = 255
    assert operation.try_talk(no_panel) is None
    operation.ctx.controller.btn_tap.assert_not_called()
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    for _ in range(3):
        assert '推进局内对话' in operation.try_talk(frame)
        now[0] += 2
        operation.last_screenshot_time += 2
    assert operation.try_talk(frame) == '对话推进未取得进展，已停止'
    assert operation.ctx.controller.btn_tap.call_count == 3


@pytest.mark.parametrize('is_dialog', [False, True])
def test_card_quantity_is_not_dialog_option(monkeypatch: pytest.MonkeyPatch, is_dialog: bool) -> None:
    """实拍黄色数量不能抢占鸣徽流程，带同行A的真实对话仍能进入选择。"""
    from zzz_od.operation.gamepad import dialog

    operation, _ = _short_dialog_operation('')
    screens = Path(__file__).resolve().parents[3] / 'screens'
    path = screens / ('迷失之地-大世界/ios_talk_option_a.webp' if is_dialog
                      else '迷失之地-通用选择/ios_quantity_not_dialog.webp')
    frame = cv2_utils.read_image(str(path))
    rect = Rect(1340, 490, 1920, 815)
    matches = MatchResultList()
    matches.append(MatchResult(1, 140, 162, 181, 28) if is_dialog
                   else MatchResult(1, 107, 205, 62, 45))
    operation.ctx.screen_loader.get_area = lambda screen, name: SimpleNamespace(
        rect=rect if name == '手柄-对话选项带' else Rect(390, 780, 1530, 1040),
    )
    operation.ctx.ocr.crop_and_run_ocr = lambda image, area: (
        {'好' if is_dialog else '01': matches} if area is rect else {}
    )
    operation.ctx.tm = TemplateMatcher(TemplateLoader())
    operation.talk_opt_idx = 0
    component = Mock()
    component.execute.return_value = SimpleNamespace(success=True)
    factory = Mock(return_value=component)
    monkeypatch.setattr(dialog, 'GamepadChooseDialogOption', factory)
    result = operation.try_talk(frame)
    assert (result is not None) == is_dialog
    assert factory.call_count == int(is_dialog)
    operation.ctx.controller.btn_tap.assert_not_called()
