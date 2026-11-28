"""补电来源、单次确认和跨进程待核账保护，不连接游戏。"""

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
)
from zzz_od.operation.gamepad.area_patrol import GamepadAreaPatrol
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation
from zzz_od.operation.gamepad.reserve_charge import ChargeResourceSnapshot
from zzz_od.operation.gamepad.restore_reserve_charge import (
    GamepadRestoreReserveCharge,
    charge_restore_budget,
    reserve_budget,
)


def config() -> SimpleNamespace:
    fields = {
        'macos_reserve_date': datetime.now(ZoneInfo('Asia/Shanghai'))
        .date()
        .isoformat(),
        'macos_reserve_limit': 44,
    }
    return SimpleNamespace(
        get=lambda key, default=None: fields.get(key, default),
        fields=fields,
        restore_charge='使用储蓄电量',
        loop=False,
        double_reward=False,
        plan_list=[
            ChargePlanItem(
                mission_name='赏金专项', card_num='5', plan_times=2, run_times=2
            ),
            ChargePlanItem(
                category_name='区域巡防',
                mission_type_name='怪兽二重奏',
                mission_name=None,
                plan_times=2,
                run_times=1,
            ),
        ],
    )


def operation() -> GamepadRestoreReserveCharge:
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap', 'click']),
        current_instance_idx=2,
        run_context=Mock(),
    )
    cfg = config()
    challenge = GamepadAreaPatrol(ctx, cfg.plan_list[1], config=cfg)
    op = GamepadRestoreReserveCharge(ctx, cfg, challenge)
    op._after_round_wait = Mock()
    return op


def test_date_and_cap_are_saved_together_without_changing_restore_mode() -> None:
    cfg = object.__new__(ChargePlanConfig)
    cfg.data = {'restore_charge': '不使用'}
    cfg.save = Mock()
    day = date(2026, 11, 28)
    cfg.set_macos_reserve_limit(day, 127)
    cfg.save.assert_called_once_with()
    assert cfg.data == {'restore_charge': '不使用', 'macos_reserve_date': day.isoformat(), 'macos_reserve_limit': 127}
    assert cfg.get_macos_reserve_limit(day) == 127
    assert cfg.get_macos_reserve_limit(day + timedelta(days=1)) == 0
    cfg.set_macos_reserve_limit(day, 0)
    assert cfg.get_macos_reserve_limit(day) == 0


def test_only_ether_battery_mode_is_independent_of_the_reserve_allowance() -> None:
    cfg = config()
    cfg.fields.clear()
    cfg.restore_charge = '使用以太电池'
    assert charge_restore_budget(cfg).maximum_reserve == 0
    cfg.restore_charge = '同时使用储蓄电量和以太电池'
    with pytest.raises(ValueError):
        charge_restore_budget(cfg)


@pytest.mark.parametrize(
    'change', ['no_date', 'expired', 'unlimited', 'batteries']
)
def test_invalid_permission_stays_blocked(
    change: str,
) -> None:
    c = config()
    if change == 'no_date':
        c.fields['macos_reserve_date'] = ''
    elif change == 'expired':
        c.fields['macos_reserve_date'] = (
            date.fromisoformat(c.fields['macos_reserve_date']) - timedelta(days=1)
        ).isoformat()
    elif change == 'unlimited':
        c.fields['macos_reserve_limit'] = 0
    elif change == 'batteries':
        c.restore_charge = '使用以太电池'
    with pytest.raises(ValueError):
        reserve_budget(c)


def test_resource_snapshot_requires_all_three_balances_and_unique_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = operation()

    def match(x: int) -> SimpleNamespace:
        return SimpleNamespace(max=SimpleNamespace(center=SimpleNamespace(x=x)))

    words = {
        text: match(x)
        for text, x in [
            ('储蓄电量', 80),
            ('以太电池', 220),
            ('菲林', 360),
            ('1406', 80),
            ('5', 220),
            ('948', 360),
        ]
    }
    monkeypatch.setattr(
        op, '_area', lambda name: (np.zeros((210, 440, 3), dtype=np.uint8), words)
    )
    frames = Mock(return_value=[SimpleNamespace(center=SimpleNamespace(x=80))])
    monkeypatch.setattr(
        'zzz_od.operation.gamepad.restore_reserve_charge.find_yellow_focus_frames',
        frames,
    )
    balances = ChargeResourceSnapshot(17, 1406, 5, 948)
    assert op._source_data(17) == (balances, '储蓄电量')
    frames.return_value = [SimpleNamespace(center=SimpleNamespace(x=220))]
    assert op._source_data(17) == (balances, '以太电池')
    frames.return_value = [SimpleNamespace(center=SimpleNamespace(x=170))]
    assert op._source_data(17) is None
    frames.return_value = [SimpleNamespace(center=SimpleNamespace(x=80))]
    del words['948']
    assert op._source_data(17) is None


def test_quantity_confirmation_is_exact_once_and_saved_before_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = operation()
    op._before = ChargeResourceSnapshot(17, 1406, 5, 948)
    op._amount = 43
    op.budget.prepare(
        op._before, 60, 60, 1, 240, datetime.now(ZoneInfo('Asia/Shanghai'))
    )
    op._regen_deadline = time.monotonic() + 60
    values = {
        '手柄-快捷来源': {'储蓄电量×1406'},
        '手柄-快捷标题': {'快捷使用'},
        '手柄-兑换数值': {'43'},
        '手柄-兑换最小': {'1'},
        '手柄-兑换最大': {'240'},
        '手柄-兑换确认': {'A', '确认'},
    }
    monkeypatch.setattr(op, '_texts', lambda name: values.get(name, set()))
    monkeypatch.setattr(op, '_save_evidence', Mock())
    events = []
    monkeypatch.setattr(op, '_save_journal', lambda state: events.append(state))
    op.ctx.controller.btn_tap.side_effect = lambda key: events.append(key)
    values['手柄-兑换数值'] = {'44'}
    assert not op.confirm_quantity().is_success
    assert events == []
    values['手柄-兑换数值'] = {'43'}
    values['手柄-兑换最小'] = set()
    assert not op.confirm_quantity().is_success
    assert events == []
    values['手柄-兑换最小'] = {'1'}
    values['手柄-兑换确认'] = {'确认'}
    assert not op.confirm_quantity().is_success
    assert events == []
    values['手柄-兑换确认'] = {'A确认'}
    assert op.confirm_quantity().is_success
    assert op.confirm_quantity().is_success
    assert events == ['confirmation_issued', 'south']


@pytest.mark.parametrize('filename', ['pending.json', 'reserve_2_2000-01-01.json'])
def test_pending_journal_blocks_new_process_before_any_input(tmp_path: Path, filename: str) -> None:
    op = operation()
    op.journal = tmp_path / 'pending.json'
    (tmp_path / filename).write_text(json.dumps({'state': 'confirmation_issued'}))
    assert op.open_source().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_cannot_save_new_intent_after_another_process_wrote_receipt(tmp_path: Path) -> None:
    first, concurrent = operation(), operation()
    first.journal = concurrent.journal = tmp_path / 'reserve_2_today.json'
    first._save_journal('confirmation_issued')
    with pytest.raises(ValueError, match='禁止重领'):
        concurrent._save_journal('confirmation_issued')
    assert json.loads(first.journal.read_text())['state'] == 'confirmation_issued'


def test_exhausted_allowance_closes_source_without_confirming(monkeypatch: pytest.MonkeyPatch) -> None:
    op = operation()
    op._initial_energy = 10
    monkeypatch.setattr(op, '_main', Mock(return_value=True))
    monkeypatch.setattr(op, '_texts', Mock(return_value={'取出等量储备电量', '电量恢复2分00秒'}))
    monkeypatch.setattr(op, '_source_confirm_focused', Mock(return_value=True))
    monkeypatch.setattr(op, '_source_data', Mock(return_value=(ChargeResourceSnapshot(10, 1500, 16, 5463), '储蓄电量')))
    assert op.choose_source().status == op.STATUS_SHORTAGE
    assert op.budget.pending is None
    op.ctx.controller.btn_tap.assert_called_once_with('east')


def test_unfinished_five_card_plan_reconciles_using_independent_balances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = SimpleNamespace(controller=Mock(), current_instance_idx=2, run_context=Mock())
    plan = ChargePlanItem(mission_name='赏金专项', card_num='默认数量')
    cfg = config()
    cfg.plan_list = [plan]
    challenge = GamepadCombatSimulation(ctx, plan, config=cfg)
    assert challenge.bind_prepared_charge(100)
    op = GamepadRestoreReserveCharge(ctx, cfg, challenge)
    op._after_round_wait = Mock()
    op.journal = tmp_path / 'reserve_2_today.json'
    assert op._plan_matches()
    op._before = ChargeResourceSnapshot(57, 1500, 16, 5463)
    op._amount = 43
    op._after_energy = 100
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    op.budget.prepare(op._before, 100, 100, 1, 240, now)
    op.budget.check_confirmation('储蓄电量', 43, op._before, now)
    op._save_journal('confirmation_issued')
    back = Mock(return_value=Mock(execute=lambda: OperationResult(True)))
    wallet = Mock(return_value=Mock(execute=lambda: OperationResult(True, data={
        'balances': {'energy': 101, 'reserve': 1457, 'ether_batteries': 16, 'premium_currency': 5463},
        'evidence_paths': {'handbook': 'handbook.png', 'storage': 'storage.png'},
    })))
    monkeypatch.setattr('zzz_od.operation.gamepad.restore_reserve_charge.GamepadChargeBackToWorld', back)
    monkeypatch.setattr('zzz_od.operation.gamepad.restore_reserve_charge.GamepadReadChargeBalances', wallet)
    assert op.verify_resources().is_success
    back.assert_called_once_with(ctx, '实战模拟室')
    wallet.assert_called_once_with(ctx)
    assert json.loads(op.journal.read_text())['restored_total'] == 43
    assert plan.run_times == 0
    ctx.controller.btn_tap.assert_not_called()


def test_mixed_sources_prefer_authorized_reserve_and_use_minimum_whole_batteries() -> None:
    op = operation()
    op._mode = '同时使用储蓄电量和以太电池'
    balances = ChargeResourceSnapshot(20, 1500, 16, 5463)
    assert op._select_source(balances, 60) == ('储蓄电量', 40)
    op.budget.restored = 30
    assert op._select_source(balances, 60) == ('以太电池', 1)
    assert op._select_source(balances, 100) == ('以太电池', 2)
    op._mode = '使用以太电池'
    assert op._select_source(balances, 40) == ('以太电池', 1)
    assert op._select_source(ChargeResourceSnapshot(20, 1500, 0, 5463), 40) is None


def test_source_focus_only_selects_the_requested_card_and_never_films() -> None:
    op = operation()
    assert not op._focus_source('以太电池', '储蓄电量', '储蓄电量', True)
    assert not op._focus_source('以太电池', '储蓄电量', '储蓄电量', False)
    assert not op._focus_source('以太电池', '菲林', '储蓄电量', False)
    assert not op._focus_source('以太电池', '以太电池', '储蓄电量', False)
    assert not op._focus_source('以太电池', '以太电池', '储蓄电量', False)
    assert not op._focus_source('以太电池', '以太电池', '以太电池', False)
    assert op._focus_source('以太电池', '以太电池', '以太电池', True)
    assert [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list] == [
        'dpad_up', 'dpad_right', 'dpad_left', 'south', 'dpad_down',
    ]


def test_ether_reconciliation_refuses_a_premium_or_reserve_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    op = operation()
    op._source = '以太电池'
    op._before = ChargeResourceSnapshot(19, 1500, 16, 5463)
    op._amount = 1
    op._after_energy = 79
    op.journal = tmp_path / 'reserve_2_today.json'
    op._save_journal('confirmation_issued')
    balances = {'energy': 79, 'reserve': 1500, 'ether_batteries': 15, 'premium_currency': 5462}
    back = Mock(return_value=Mock(execute=lambda: OperationResult(True)))
    wallet = Mock(return_value=Mock(execute=lambda: OperationResult(True, data={
        'balances': balances, 'evidence_paths': {},
    })))
    monkeypatch.setattr('zzz_od.operation.gamepad.restore_reserve_charge.GamepadChargeBackToWorld', back)
    monkeypatch.setattr('zzz_od.operation.gamepad.restore_reserve_charge.GamepadReadChargeBalances', wallet)
    assert op.verify_resources().is_fail
    balances['premium_currency'] = 5463
    balances['reserve'] = 1499
    assert op.verify_resources().is_fail
    assert json.loads(op.journal.read_text())['state'] == 'confirmation_issued'
    balances['reserve'] = 1500
    assert op.verify_resources().is_success
    assert json.loads(op.journal.read_text())['restored_total'] == 0


@pytest.mark.parametrize(
    ('setting', 'status'),
    [
        ('不使用', '电量不足'),
        ('使用储蓄电量', '执行最小储蓄补电'),
    ],
)
def test_original_scheduler_routes_shortage_only_for_opted_in_reserve(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    status: str,
) -> None:
    """原调度的自然不足路径保留，储蓄路径进入对账而非直接战斗。"""
    from zzz_od.operation.gamepad.charge_plan import GamepadChargePlan

    c = config()
    c.restore_charge = setting
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2)
    op = GamepadChargePlan(ctx, c, Mock())
    op._after_round_wait = Mock()
    op._simulation = Mock(expected_charge=60)
    op._simulation._preset_selected.return_value = True
    op._simulation.read_charge.return_value = (19, 60)
    op.current_plan = c.plan_list[1]
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(op, '_found', Mock(return_value=True))
    assert op.check_charge().status == status
    ctx.controller.btn_tap.assert_not_called()
