"""原录像店应用从已打开的账本恢复，只验证当前新增路径。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.ocr_service import OcrService
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.application.random_play import random_play_app
from zzz_od.application.random_play.random_play_app import RandomPlayApp
from zzz_od.application.random_play.random_play_config import RandomPlayTransportPoint
from zzz_od.operation.gamepad import shop, transport

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '影像店营业'


def test_real_ledger_resumes_without_transport_and_returns_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实局部 OCR 识别账本与返回提示，B 只发一次，不触碰营业确认。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('本地缺少 ppocrv6，无法验证账本真实裁剪 OCR')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    app = RandomPlayApp.__new__(RandomPlayApp)
    app.ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap', 'interact']), screen_loader=loader,
        ocr=ocr, ocr_service=OcrService(ocr),
    )
    app.config = SimpleNamespace(
        transport_point=RandomPlayTransportPoint.POINT_1.value.value,
        agent_name_1='随机', agent_name_2='随机',
    )
    app.handle_init()
    app.turn_compensator = Mock()
    app._previous_node = None
    app._previous_round_result = None
    app._macos_ledger_close_sent = False
    app.node_clicked = False
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_yesterday_ledger.webp'))
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(app, 'screenshot', Mock())
    monkeypatch.setattr(random_play_app, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(random_play_app, 'save_shop_frame', Mock(return_value='memory.png'))
    monkeypatch.setattr(shop, 'save_shop_frame', Mock(return_value='memory.png'))
    factory = Mock()
    monkeypatch.setattr(transport, 'GamepadTransport', factory)
    assert app.transport().status == RandomPlayApp.STATUS_MACOS_SHOP_OPEN
    factory.assert_not_called()
    app.turn_compensator.clear_pending_sample.assert_not_called()
    assert not app.wait_run().is_success
    assert not app.wait_run().is_success
    app.ctx.controller.btn_tap.assert_called_once_with('east')
    app.ctx.controller.interact.assert_not_called()
    assert app.config.transport_point == RandomPlayTransportPoint.POINT_1.value.value

    # 主界面按实际黄框进宣传员，默认随机只确认当前合法人物。
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_business_empty.webp'))
    assert app._macos_business_visible()
    assert shop.focused_business_card(app) == 0
    assert app.click_promoter_entry().is_success
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_promoter_list.webp'))
    assert not app.choose_promoter().is_success
    assert app._macos_selected_promoter == '席德'
    assert app.ctx.controller.btn_tap.call_args_list[-1].args == ('south',)
    assert (app.config.agent_name_1, app.config.agent_name_2) == ('随机', '随机')

    # 推荐后确有三片和蓝色完成主题，但宣传员仍空，不能营业也不能误按 B 退出。
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_business_recommended.webp'))
    assert shop.focused_business_card(app) == 1
    assert shop.business_card_titles(app) == [None, '吾本如斯', '黑色唱机', '最后一次飞行']
    assert shop.business_themes_complete(app)
    count = app.ctx.controller.btn_tap.call_count
    assert app.back().is_fail
    assert app.start().is_fail
    assert app.ctx.controller.btn_tap.call_count == count

    # 指定人物不会借随机入口改成席德，所选人物与配置均保留。
    app._macos_promoter_confirm_sent = False
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_promoter_list.webp'))
    app.config.agent_name_1 = '安比'
    app.config.agent_name_2 = '妮可'
    app.run_record = SimpleNamespace(get_current_dt=lambda: '20261024')
    assert app.choose_promoter().is_fail
    assert (app.config.agent_name_1, app.config.agent_name_2) == ('安比', '妮可')
    assert app.ctx.controller.btn_tap.call_count == count


@pytest.mark.parametrize('filename,message,status', [
    ('ios_start_confirm', '是否准备营业', RandomPlayApp.STATUS_MACOS_CONFIRM),
    ('ios_started_confirm', '诚信经营，丁尼为本', RandomPlayApp.STATUS_MACOS_STARTED),
])
def test_real_business_confirmation_requires_correct_message(
    monkeypatch: pytest.MonkeyPatch, filename: str, message: str, status: str,
) -> None:
    """真实弹窗必须有对应提示和黄色确认；恢复时不重传送或再发营业。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('缺少 OCR 模型')
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    app = RandomPlayApp.__new__(RandomPlayApp)
    app.ctx = SimpleNamespace(screen_loader=loader, ocr=ocr, ocr_service=OcrService(ocr))
    app._previous_node = None
    app._previous_round_result = None
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{filename}.webp'))
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(random_play_app, 'sys', SimpleNamespace(platform='darwin'))
    assert app._macos_confirm_visible(message)
    assert not app._macos_confirm_visible('无关确认')
    assert app.transport().status == status


@pytest.mark.parametrize('frame,accepted', [('ios_started_confirm', True), ('ios_started_alternate', True), ('ios_start_confirm', False)])
def test_single_confirmation_uses_layout_not_greeting(monkeypatch: pytest.MonkeyPatch, frame: str, accepted: bool) -> None:
    """两种单按钮营业祝词都匹配，双按钮营业询问不误按 A。"""
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.template_loader import TemplateLoader
    from zzz_od.operation.gamepad.confirmation import confirm_expected_single_dialog
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    app = RandomPlayApp.__new__(RandomPlayApp)
    app.ctx = SimpleNamespace(screen_loader=loader, tm=TemplateMatcher(TemplateLoader()), controller=Mock())
    app.node_clicked = False
    app.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{frame}.webp'))
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(app, 'save_screenshot', Mock())
    assert confirm_expected_single_dialog(app).is_success is accepted
    confirm_expected_single_dialog(app)
    assert app.ctx.controller.btn_tap.call_count == int(accepted)
