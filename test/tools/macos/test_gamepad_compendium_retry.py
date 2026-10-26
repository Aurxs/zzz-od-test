"""手册首次输入未响应时，只在连续大世界证据下有限重试。"""
from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.transport_by_compendium import GamepadTransportByCompendium


def test_handbook_retry_stays_bounded(monkeypatch) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    op = GamepadTransportByCompendium(ctx, '训练', '实战模拟室', '基础材料')
    op.last_screenshot = object()
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, '_selected', Mock(return_value=None))
    world = SimpleNamespace(is_success=True)
    monkeypatch.setattr(op, 'round_by_find_area', Mock(return_value=world))
    op.open_compendium()
    assert ctx.controller.click.call_count == 1
    world.is_success = False
    for _ in range(3):
        op.open_compendium()
    assert ctx.controller.click.call_count == 1
    world.is_success = True
    for _ in range(8):
        op.open_compendium()
    assert ctx.controller.click.call_count == 2
    op.handle_init()
    op.open_compendium()
    assert ctx.controller.click.call_count == 3
