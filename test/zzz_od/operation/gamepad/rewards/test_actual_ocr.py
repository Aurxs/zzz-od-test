"""核对实际裁图 OCR，防止全屏文字框回放掩盖小裁图识别失败。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.rewards import GamepadEngagementReward


def test_profile_crops_recognize_daily_claim_and_common_reward() -> None:
    """直接读取平台区域并运行本地模型，两个真实画面不能互相误判。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('仅使用已存在的本地 OCR 模型，不在快速验证中下载')
    assert ocr.init_model()
    try:
        loader = ProfileScreenContext()
        loader.reload()
        operation = GamepadEngagementReward(SimpleNamespace(
            controller=Mock(spec=['click', 'btn_tap']), screen_loader=loader,
            ocr=ocr, run_context=Mock(), current_instance_idx=2,
        ))
        screens = Path(__file__).resolve().parents[5] / 'screens'
        operation.last_screenshot = cv2_utils.read_image(str(screens / '快捷手册/ios_daily.webp'))
        assert operation.last_screenshot is not None
        assert operation.claim_available()
        assert not operation._known_reward_visible()
        operation.last_screenshot = cv2_utils.read_image(str(screens / '卦象集录/ios_reward.webp'))
        assert operation.last_screenshot is not None
        assert not operation.claim_available()
        assert operation._known_reward_visible()
        assert operation.reward_confirmation_key() is None
        operation._claim_sent = True
        assert operation.reward_confirmation_key() == 'south'
        operation.ctx.controller.btn_tap.assert_not_called()
    finally:
        ocr.cleanup()


def test_completion_animation_waits_for_stable_real_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实首次领取的光效不能判未满，后续完成勾仍复用原模板。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('仅使用已存在的本地 OCR 模型，不在快速验证中下载')
    assert ocr.init_model()
    try:
        loader = ProfileScreenContext()
        loader.reload()
        operation = GamepadEngagementReward(SimpleNamespace(
            controller=Mock(spec=['click', 'btn_tap']), screen_loader=loader,
            ocr=ocr, tm=TemplateMatcher(TemplateLoader()),
            run_context=Mock(), current_instance_idx=2,
        ))
        monkeypatch.setattr(operation, '_after_round_wait', Mock())
        monkeypatch.setattr(operation, 'save_screenshot', Mock(side_effect=lambda prefix: prefix))
        screens = Path(__file__).resolve().parents[5] / 'screens' / '快捷手册'
        operation.last_screenshot = cv2_utils.read_image(str(screens / 'ios_daily_full_unclaimed.webp'))
        assert operation.claim_available()
        assert not operation._reward_complete()
        operation._claim_sent = True
        operation._confirmation_sent = True
        operation.last_screenshot = cv2_utils.read_image(str(screens / 'ios_daily_claim_animation.webp'))
        assert operation.confirm_reward().status == '等待活跃度完成标记稳定'
        operation.last_screenshot = cv2_utils.read_image(str(screens / 'ios_daily_claimed.webp'))
        assert operation._reward_complete()
        assert not operation.claim_available()
        assert operation.confirm_reward().is_success
        assert operation._full_engagement
        operation.ctx.controller.btn_tap.assert_not_called()
    finally:
        ocr.cleanup()
