"""功能导览焦点缺失时不盲发输入。"""

from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.function_guide import GamepadOpenFunction


def test_animation_waits_are_bounded_without_input(monkeypatch):
    from zzz_od.operation.gamepad import function_guide

    ctx = SimpleNamespace(run_context=Mock(), controller=Mock())
    op = GamepadOpenFunction(ctx, '情报板')
    op._after_round_wait = Mock()
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._read_area = Mock(return_value=(Mock(), {}))
    op._text_rect = Mock(return_value=None)
    op._pending_evidence = Mock(return_value='failed')
    monkeypatch.setattr(function_guide, 'find_yellow_focus_frames', lambda *args, **kwargs: [])
    for _ in range(5):
        assert op.select_function() != 'failed'
    assert op.select_function() == 'failed'
    ctx.controller.btn_tap.assert_not_called()
