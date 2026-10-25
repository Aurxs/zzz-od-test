"""对话选项使用实拍与真实裁剪 OCR 快照，不创建游戏输入。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.dialog import GamepadChooseDialogOption

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '对话'


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadChooseDialogOption:
    """只回放已经在原 PNG 验证的局部文字，焦点仍由真实图像计算。"""
    results: dict[str, MatchResultList] = {}
    for item in json.loads((SCREENS / 'ios_dialog_crop_ocr.json').read_text())['ios_random_play_options']:
        matches = results.setdefault(item['text'], MatchResultList())
        matches.append(MatchResult(1, item['x'], item['y'], item['width'], item['height']))
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap']), run_context=Mock(), ocr=Mock(),
        screen_loader=SimpleNamespace(get_area=lambda screen, name: SimpleNamespace(
            rect=Rect(1340, 490, 1920, 815),
        )),
    )
    ctx.ocr.crop_and_run_ocr.return_value = results
    op = GamepadChooseDialogOption(ctx, '查看经营状况')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, '_save', Mock(return_value=True))
    monkeypatch.setattr(op, 'screenshot', Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_random_play_options.webp'))
    op.last_screenshot_time = 1
    return op


def test_highlighted_target_confirms_once_without_claiming_destination(
    operation: GamepadChooseDialogOption,
) -> None:
    """当前目标及同排 A 同时成立才确认，结果只表示选项输入已发出。"""
    assert not operation.choose_option().is_success
    operation.ctx.ocr.crop_and_run_ocr.return_value = {}
    assert operation.choose_option().status == '已选择查看经营状况'
    operation.last_screenshot = None
    assert operation.choose_option().status == '已选择查看经营状况'
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    operation.screenshot.assert_called_once_with()


def test_unselected_visible_target_moves_only_once_per_frame(
    operation: GamepadChooseDialogOption,
) -> None:
    """方向根据实际高亮行决定，相同帧不重复移焦。"""
    operation.option = '暂时不用'
    assert not operation.choose_option().is_success
    assert not operation.choose_option().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('dpad_down')


@pytest.mark.parametrize('missing', ['target', 'focus', 'prompt'])
def test_unknown_target_focus_or_a_prompt_never_confirms(
    operation: GamepadChooseDialogOption, missing: str,
) -> None:
    """目标、唯一焦点或 A 提示任一缺失，都保留现场并停止。"""
    if missing == 'target':
        operation.option = '不存在的选项'
    elif missing == 'focus':
        operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    else:
        operation.ctx.ocr.crop_and_run_ocr.return_value.pop('A')
    assert operation.choose_option().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()


def test_failed_confirmation_evidence_cannot_repeat_daily_choice(
    operation: GamepadChooseDialogOption,
) -> None:
    """输入之后留图失败时也不能重发可能已消费的对话确认。"""
    operation._save.side_effect = [True, False, True]
    assert operation.choose_option().is_fail
    assert operation.choose_option().is_fail
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


@pytest.mark.parametrize('coffee', [False, True])
def test_real_profile_crop_reads_options_and_a_prompt(
    operation: GamepadChooseDialogOption, coffee: bool,
) -> None:
    """真实 ppocrv6 直接识别平台区域，不能只依赖全屏文字框回放。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('本地缺少 ppocrv6，无法验证真实对话裁剪 OCR')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    assert loader.get_area('大世界', '手柄-对话选项带') is not None
    operation.ctx.screen_loader = loader
    operation.ctx.ocr = ocr
    if coffee:
        operation.last_screenshot = cv2_utils.read_image(str(
            SCREENS.parent / '咖啡店' / 'ios_tinmaster_dialog.webp'
        ))
        results = ocr.crop_and_run_ocr(
            operation.last_screenshot, loader.get_area('大世界', '手柄-对话选项带').rect,
        )
        operation.option = next(text for text in results if '汀曼特调' in text)
    assert operation.choose_option().status == '等待对话选项关闭'
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


def test_same_dialog_retries_bounded_confirmation(operation: GamepadChooseDialogOption) -> None:
    """台词动画吞掉首次确认时，只在相同选项及焦点仍完整可见时重试。"""
    for _ in range(3):
        assert not operation.choose_option().is_success
    assert operation.choose_option().is_fail
    assert operation.ctx.controller.btn_tap.call_count == 3
