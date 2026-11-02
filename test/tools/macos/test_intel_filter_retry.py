"""筛选后移开焦点确认，不对未知或未聚焦目标重复确认。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.operation.gamepad.intel_board import GamepadIntelBoardFilter


def test_filter_verifies_unfocused_blue_before_next_action(monkeypatch):
    from zzz_od.operation.gamepad import intel_board

    clock = [100.0]
    blue = [False]
    monkeypatch.setattr(intel_board.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: blue[0])
    monkeypatch.setattr(intel_board, 'highlight_mask', lambda *args: Mock())
    monkeypatch.setattr(intel_board.cv2, 'findContours', lambda *args: (['box'], None))
    monkeypatch.setattr(intel_board.cv2, 'boundingRect', lambda *args: (20, 20, 220, 40))
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = GamepadIntelBoardFilter(ctx)
    op._after_round_wait = Mock()
    op._reset_sent = True
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._read_area = Mock(return_value=(Mock(), {}))
    op._text_rect = Mock(return_value=Rect(50, 25, 150, 55))
    op.filter_commissions()
    clock[0] += 1
    op.filter_commissions()
    assert ctx.controller.btn_tap.call_args_list == [call('south'), call('dpad_right')]
    blue[0] = True
    op.filter_commissions()
    assert op._type_index == 1
    assert ctx.controller.btn_tap.call_count == 2


def test_unknown_focus_never_retries_confirmation(monkeypatch):
    from zzz_od.operation.gamepad import intel_board

    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: False)
    monkeypatch.setattr(intel_board, 'highlight_mask', lambda *args: Mock())
    monkeypatch.setattr(intel_board.cv2, 'findContours', lambda *args: ([], None))
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = GamepadIntelBoardFilter(ctx)
    op._after_round_wait = Mock()
    op._reset_sent = True
    op._toggle_sent = True
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._read_area = Mock(return_value=(Mock(), {}))
    op._text_rect = Mock(return_value=Rect(50, 25, 150, 55))
    op.filter_commissions()
    ctx.controller.btn_tap.assert_not_called()


def test_fallback_requires_first_type_proven_blue(monkeypatch):
    from zzz_od.operation.gamepad import intel_board

    monkeypatch.setattr(intel_board.time, 'monotonic', lambda: 100.0)
    monkeypatch.setattr(intel_board, 'highlight_mask', lambda *args: Mock())
    monkeypatch.setattr(intel_board.cv2, 'findContours', lambda *args: (['box'], None))
    monkeypatch.setattr(intel_board.cv2, 'boundingRect', lambda *args: (300, 20, 220, 40))
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda image, rect, color: rect.x1 == 50)
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = GamepadIntelBoardFilter(ctx)
    op._after_round_wait = Mock()
    op._reset_sent = True
    op._type_index = 1
    op._toggle_sent = True
    op._toggle_attempts = 2
    op._verify_shifted = True
    op._save_evidence = Mock()
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._read_area = Mock(return_value=(Mock(), {}))
    op._text_rect = Mock(side_effect=lambda words, name: Rect(50, 25, 150, 55) if name == '恶名狩猎' else Rect(330, 25, 450, 55))
    result = op.filter_commissions()
    assert not result.is_fail and op._closed
    ctx.controller.btn_tap.assert_called_once_with('east')
    op._closed = False
    ctx.controller.btn_tap.reset_mock()
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: False)
    assert op.filter_commissions().is_fail
    ctx.controller.btn_tap.assert_not_called()
