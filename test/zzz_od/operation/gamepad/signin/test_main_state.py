"""用真实局部 OCR、平台区域和模板重现签到主界面识别，不回放文字框。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.ocr_service import OcrService
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.signin import GamepadDailySignIn

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '卦象集录'


@pytest.fixture(scope='module')
def real_context() -> SimpleNamespace:
    """只加载本地 CPU OCR 与画面资源，不创建真实控制器或下载模型。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('本地缺少 ppocrv6，无法进行真实局部 OCR 验证')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    return SimpleNamespace(
        ocr=ocr, ocr_service=OcrService(ocr),
        screen_loader=loader, tm=TemplateMatcher(TemplateLoader()),
        run_context=Mock(), controller=Mock(spec=['btn_tap', 'btn_press', 'interact']),
    )


@pytest.mark.parametrize(
    ('state', 'expected'), [('ios_main', 'available'), ('ios_main_completed', 'completed')],
)
def test_real_crop_ocr_and_templates_distinguish_main_states(
    real_context: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    state: str, expected: str,
) -> None:
    """文字相同的开闭两态均应识别，窄小裁图造成的漏检不能用全屏快照替代。"""
    op = GamepadDailySignIn(real_context, 'trigrams_collection')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    assert op.round_by_find_area(op.last_screenshot, '卦象集录', '手柄-标题').is_success
    assert op.round_by_find_area(op.last_screenshot, '卦象集录', '手柄-占卜提示').is_success
    assert op._main_state() == expected


def test_real_completed_main_never_starts_divination_again(
    real_context: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已完成封面即使还写占卜也只允许返回，不重发 A。"""
    real_context.controller.reset_mock()
    op = GamepadDailySignIn(real_context, 'trigrams_collection', resume_from_reward=True)
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock(return_value='saved_main_completed'))
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_main_completed.webp'))
    assert op.check_entry().status == op.STATUS_AT_TRIGRAMS
    assert op.collect().is_success
    real_context.controller.btn_tap.assert_not_called()
    assert not op.return_to_world().is_success
    assert not op.return_to_world().is_success
    real_context.controller.btn_tap.assert_called_once_with('east')


def test_current_scale_main_uses_cover_when_divination_ocr_is_incomplete(
    real_context: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当前窗口的占卜提示漏读一字，标题与开封面仍足以确认主界面。"""
    op = GamepadDailySignIn(real_context, 'trigrams_collection')
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_main_current_scale.webp'))
    assert not op._found('手柄-占卜提示')
    assert op._main_state() == 'available'
