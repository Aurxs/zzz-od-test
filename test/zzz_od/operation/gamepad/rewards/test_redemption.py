"""离线验证 Mac 单码兑换，不启动游戏或读取实际剪贴板。"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from zzz_od.operation.gamepad import redemption


@pytest.fixture
def op(monkeypatch: pytest.MonkeyPatch) -> redemption.GamepadRedeemCode:
    record = Mock()
    record.macos_code_attempted.return_value = False
    record.begin_macos_attempt.return_value = True
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    operation = redemption.GamepadRedeemCode(ctx, 'DEMO12345', record)
    for name, value in {
        '_dialog_visible': True,
        '_known_receipt': None,
        '_field_is': True,
        '_field_focused': True,
        '_redeem_focused': False,
        '_exact_text': True,
        '_after_round_wait': None,
        '_save_evidence': 'before.png',
    }.items():
        monkeypatch.setattr(operation, name, Mock(return_value=value))
    monkeypatch.setattr(redemption, 'temporary_redemption_pasteboard', Mock(return_value=nullcontext()))
    monkeypatch.setattr(redemption.time, 'sleep', Mock())
    operation.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    operation.last_screenshot_time = 123.0
    return operation


def test_exact_lifecycle_records_before_submit(op: redemption.GamepadRedeemCode) -> None:
    bus = Mock()
    bus.attach_mock(op.record.begin_macos_attempt, 'attempt')
    bus.attach_mock(op.ctx.controller.btn_tap, 'tap')
    op.redeem_once()
    op.redeem_once()
    op.redeem_once()
    op._field_focused.return_value = False
    op._redeem_focused.return_value = True
    assert op.redeem_once().is_success  # 转为只读等待，不表示兑换成功。
    assert op.redeem_once().is_fail
    op._known_receipt.return_value = '兑换成功'
    assert not op.wait_for_receipt().is_success  # 提交前的帧即使命中结果字样也不算。
    op.last_screenshot_time += 1.0
    assert op.wait_for_receipt().is_success
    assert bus.mock_calls == [call.tap('north'), call.tap('dpad_down'),
                              call.attempt('DEMO12345'), call.tap('south')]
    op.record.add_used_code.assert_called_once_with('DEMO12345')


@pytest.mark.parametrize('signal', ['_dialog_visible', '_field_is', '_field_focused', '_exact_text'])
def test_unknown_empty_form_never_pastes(op: redemption.GamepadRedeemCode, signal: str) -> None:
    getattr(op, signal).return_value = False
    assert not op.redeem_once().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_wrong_code_twice_or_ambiguous_focus_never_confirms(op: redemption.GamepadRedeemCode) -> None:
    op._paste_sent = True
    op._redeem_focused.return_value = True
    op.redeem_once()
    op._field_focused.return_value = False
    op._field_is.return_value = False
    op.redeem_once()
    op.redeem_once()
    op.ctx.controller.btn_tap.assert_not_called()
    op.record.begin_macos_attempt.assert_not_called()


@pytest.mark.parametrize('reason', ['attempt', 'evidence', 'race'])
def test_duplicate_or_no_evidence_never_confirms(op: redemption.GamepadRedeemCode, reason: str) -> None:
    op._paste_sent = True
    op._field_focused.return_value = False
    op._redeem_focused.return_value = True
    if reason == 'attempt':
        op.record.macos_code_attempted.return_value = True
    elif reason == 'evidence':
        op._save_evidence.return_value = ''
    else:
        op.record.begin_macos_attempt.return_value = False
    assert op.redeem_once().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('status', ['兑换码已使用', '兑换码无效', '兑换码已过期', None])
def test_known_negative_or_unknown_receipt_never_submits_again(
    op: redemption.GamepadRedeemCode, status: str | None,
) -> None:
    op._submit_sent = True
    op._known_receipt.return_value = status
    op._receipt_deadline = 0
    assert op.wait_for_receipt().is_fail
    op.ctx.controller.btn_tap.assert_not_called()
    assert op.record.add_used_code.call_count == int(status == '兑换码已使用')


def test_paste_restore_failure_is_not_ignored(op: redemption.GamepadRedeemCode) -> None:
    redemption.temporary_redemption_pasteboard.side_effect = RuntimeError('失去系统剪贴板')
    result = op.redeem_once()
    assert result.is_fail and '剪贴板' in result.status
    op.redeem_once()  # 即使下一轮得到同一表单也不会再触发剪贴板。
    redemption.temporary_redemption_pasteboard.assert_called_once()
    op.ctx.controller.btn_tap.assert_not_called()



@pytest.mark.parametrize(('header', 'panel', 'expected'), [
    (['兑换成功！'], ['兑换码', '兑换'], '兑换成功'),
    (['兑换不成功'], ['兑换', '兑换码'], None),
    (['兑换成功'], ['兑换码无效'], None),
    ([], ['兑换', 'DEMO12345', '清除'], None),
    ([], ['该兑换码已使用'], '兑换码已使用'),
])
def test_known_receipts_require_exact_unambiguous_text(
    op: redemption.GamepadRedeemCode, monkeypatch: pytest.MonkeyPatch,
    header: list[str], panel: list[str], expected: str | None,
) -> None:
    monkeypatch.setattr(op, '_read_area', Mock(side_effect=[(None, header), (None, panel)]))
    assert redemption.GamepadRedeemCode._known_receipt(op) == expected
