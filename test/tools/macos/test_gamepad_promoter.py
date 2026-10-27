"""指定宣传员只检查定位、候选顺序和不随意确认。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.operation.gamepad import promoter


def operation(monkeypatch: pytest.MonkeyPatch, candidates: list[str], names: dict[str, Rect]) -> promoter.GamepadFocusPromoter:
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = promoter.GamepadFocusPromoter(ctx, candidates)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock()
    op.last_screenshot_time = 1
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    monkeypatch.setattr(promoter, 'read_shop_area', lambda *args: (None, {name: SimpleNamespace(max=SimpleNamespace(rect=rect)) for name, rect in names.items()}))
    monkeypatch.setattr(promoter, 'focused_promoter_name', Mock(return_value='席德'))
    return op


def test_target_moves_and_returns_name_without_confirming(monkeypatch: pytest.MonkeyPatch) -> None:
    op = operation(monkeypatch, ['仪玄'], {'席德': Rect(80,270,140,310), '仪玄': Rect(740,270,810,310)})
    op.focus()
    op.ctx.controller.btn_tap.assert_called_once_with('dpad_right')
    promoter.focused_promoter_name.return_value = '仪玄'
    op.last_screenshot_time = 2
    result = op.focus()
    assert result.is_success and result.data['agent_name'] == '仪玄'
    assert op.ctx.controller.btn_tap.call_count == 1


def test_candidate_fallback_after_both_scan_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    op = operation(monkeypatch, ['仪玄', '席德'], {'席德': Rect(80,270,140,310)})
    for frame in range(1,15):
        op.last_screenshot_time = frame
        result = op.focus()
        if result.is_success:
            break
    assert result.is_success and result.data['agent_name'] == '席德'
    keys = [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list]
    assert 'dpad_up' in keys and 'dpad_down' in keys and 'south' not in keys


def test_invalid_config_never_substitutes_a_character(monkeypatch: pytest.MonkeyPatch) -> None:
    op = operation(monkeypatch, ['不存在的人物'], {})
    assert op.focus().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_real_card_focus_can_use_large_detail_name() -> None:
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.utils import cv2_utils
    from zzz_od.operation.gamepad.shop import focused_promoter_name, promoter_name

    loader=ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    ctx=SimpleNamespace(screen_loader=loader,ocr=Mock())
    ctx.ocr.crop_and_run_ocr.side_effect=lambda image,rect: {} if rect.x1==510 else {'「席德」': []}
    path=Path(__file__).resolve().parents[3]/'screens'/'影像店营业'/'ios_promoter_list.webp'
    op=SimpleNamespace(ctx=ctx,last_screenshot=cv2_utils.read_image(str(path)))
    assert focused_promoter_name(op,{'席德'})=='席德'
    assert promoter_name('「柚叶」') == '浮波柚叶'


def test_original_date_priority_and_confirmation_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.application.random_play import random_play_app

    app=object.__new__(random_play_app.RandomPlayApp)
    app.ctx=Mock()
    app.last_screenshot=Mock()
    app.ctx.controller.screenshot.return_value=(2,Mock())
    app.config=SimpleNamespace(agent_name_1='雅',agent_name_2='仪玄')
    app.run_record=Mock()
    app.run_record.get_current_dt.return_value='20261027'
    app._macos_business_visible=Mock(return_value=False)
    app._macos_promoter_confirm_sent=False
    app.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=True))
    app.round_retry=Mock()
    app.round_by_op_result = Mock()
    monkeypatch.setattr(random_play_app,'focused_promoter_name',Mock(side_effect=['席德','仪玄']))
    monkeypatch.setattr(random_play_app,'press_shop_action',Mock(return_value=SimpleNamespace(is_success=True)))
    chooser=Mock()
    chooser.return_value.execute.return_value=SimpleNamespace(success=True,data={'agent_name':'仪玄'})
    monkeypatch.setattr(promoter,'GamepadFocusPromoter',chooser)
    confirm = Mock()
    confirm.return_value.execute.return_value = SimpleNamespace(success=True)
    monkeypatch.setattr(promoter, 'GamepadConfirmPromoter', confirm)
    app._macos_choose_promoter()
    assert chooser.call_args.args[1]==['仪玄','雅']
    assert app._macos_selected_promoter=='仪玄' and app._macos_promoter_confirm_sent
    confirm.assert_called_once_with(app.ctx, '仪玄')


def test_existing_other_person_reopens_original_list_for_configured_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.application.random_play import random_play_app

    app = object.__new__(random_play_app.RandomPlayApp)
    app.ctx = Mock()
    app.config = SimpleNamespace(agent_name_1='仪玄', agent_name_2='雅')
    app.run_record = Mock()
    app.run_record.get_current_dt.return_value = '20261028'
    app._macos_selected_promoter = None
    app._macos_business_visible = Mock(return_value=True)
    app._macos_open_card = Mock()
    monkeypatch.setattr(random_play_app, 'business_card_titles', Mock(return_value=['席德', '', '', '']))
    app._macos_choose_promoter()
    app._macos_open_card.assert_called_once_with(0, '宣传员入口')


def test_running_shop_never_moves_or_replaces_promoter(monkeypatch: pytest.MonkeyPatch) -> None:
    op = operation(monkeypatch, ['仪玄'], {'席德': Rect(80,270,140,310)})
    monkeypatch.setattr(promoter, 'read_shop_area', lambda *args: (None, {'正在营业': []}))
    assert op.focus().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_confirmation_rejects_wrong_focus_and_wrong_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.application.random_play import random_play_app

    original = Mock()
    monkeypatch.setattr(random_play_app, 'RandomPlayApp', Mock(return_value=original))
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = promoter.GamepadConfirmPromoter(ctx, '仪玄')
    op._after_round_wait = Mock()
    op.last_screenshot = Mock()
    monkeypatch.setattr(promoter, 'read_shop_area', Mock(return_value=(None, {'确定': []})))
    monkeypatch.setattr(promoter, 'focused_promoter_name', Mock(return_value='席德'))
    assert op.confirm().is_fail
    ctx.controller.btn_tap.assert_not_called()
    op._sent = True
    original._macos_business_visible.return_value = True
    monkeypatch.setattr(promoter, 'business_card_titles', Mock(return_value=['席德', '', '', '']))
    assert op.confirm().is_fail
    ctx.controller.btn_tap.assert_not_called()
