"""用咖啡实拍验证奖励、已喝提示与对话图标。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.ocr.ocr_service import OcrService
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.application.coffee.coffee_app import CoffeeApp
from zzz_od.operation.gamepad.dialog import GamepadChooseDialogOption

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '咖啡店'


def test_coffee_actual_reward_and_already_drunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """电量弹窗与明天再来分别识别，不把普通对话当获得。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少 OCR 模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    ctx = SimpleNamespace(ocr=ocr, ocr_service=OcrService(ocr), screen_loader=loader,
                          tm=TemplateMatcher(TemplateLoader()), run_context=Mock(),
                          controller=Mock(spec=['btn_tap']))
    app = CoffeeApp.__new__(CoffeeApp)
    app.ctx = ctx
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_energy_reward.webp'))
    assert app._macos_energy_reward_visible()
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_already_drunk.webp'))
    assert not app._macos_energy_reward_visible()
    assert app.round_by_find_area(app.last_screenshot, '咖啡店', '手柄-今日已喝').is_success
    op = GamepadChooseDialogOption(ctx, '请来一杯汀曼特调!')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_tinmaster_a_ocr_missed.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, '_save', Mock(return_value=True))
    monkeypatch.setattr(op, 'screenshot', Mock())
    assert op.choose_option().status == '等待对话选项关闭'
    ctx.controller.btn_tap.assert_called_once_with('south')
