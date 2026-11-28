"""核对原手册与仓库的独立余额读数。"""

from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.charge_balance import GamepadReadChargeBalances
from zzz_od.operation.gamepad.reserve_charge import ChargeResourceSnapshot


def operation() -> GamepadReadChargeBalances:
    op = GamepadReadChargeBalances(SimpleNamespace(controller=Mock(), run_context=Mock()))
    op._after_round_wait = Mock()
    return op


def test_read_handbook_requires_tab_and_all_known_resource_counts() -> None:
    op = operation()
    fields = {'手册-当前电量': '027/240', '手册-储蓄电量': '1573', '手册-以太电池': '16'}
    op._text = fields.get
    op._daily_visible = Mock(return_value=False)
    assert op._read_handbook() is None
    op._daily_visible.return_value = True
    assert op._read_handbook() == (27, 1573, 16)
    fields['手册-以太电池'] = ''
    assert op._read_handbook() is None


def test_read_film_requires_complete_balanced_storage_bar() -> None:
    op = operation()
    fields = {'仓库-标题': '驱动仓库[687/3000]', '仓库-当前电量': '028/240', '仓库-菲林': '00005463'}
    op._text = fields.get
    op._film_icon_visible = Mock(return_value=False)
    op._save_evidence = Mock(return_value='saved')
    op._handbook = (27, 1500, 16)
    assert not op.read_storage().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    op._film_icon_visible.return_value = True
    assert op.read_storage().is_success
    assert op._balances == ChargeResourceSnapshot(27, 1500, 16, 5463)
    op.ctx.controller.btn_tap.assert_called_once_with('east')
    op.ctx.controller.btn_tap.reset_mock()
    fields['仓库-当前电量'] = '025/240'
    assert op.read_storage().is_fail
    fields['仓库-菲林'] = '0005463'
    assert op._read_storage() is None
    op.ctx.controller.btn_tap.assert_not_called()
