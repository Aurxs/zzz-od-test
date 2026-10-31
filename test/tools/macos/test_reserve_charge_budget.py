"""储蓄电量的日期、最小差额及不明结果保护；不连接设备或账户。"""

from datetime import UTC, date, datetime

import pytest

from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.reserve_charge import (
    ChargeResourceSnapshot,
    ReserveChargeBudget,
    remaining_plan_energy,
)

NOW = datetime(2026, 11, 1, 4, tzinfo=UTC)


def budget(maximum: int = 320) -> ReserveChargeBudget:
    return ReserveChargeBudget(date(2026, 11, 1), maximum, '使用储蓄电量')


def snapshot(energy: int = 43, reserve: int = 1000) -> ChargeResourceSnapshot:
    return ChargeResourceSnapshot(energy, reserve, 6, 100)


def test_ordered_plan_budget_counts_real_completed_runs_without_skipping() -> None:
    plans = [
        ChargePlanItem(mission_name='赏金专项', card_num='5', plan_times=2),
        ChargePlanItem(category_name='区域巡防', mission_type_name='怪兽二重奏', plan_times=2),
    ]
    assert remaining_plan_energy(plans) == 320
    plans[0].run_times = 1
    plans[0].skipped = True
    assert remaining_plan_energy(plans) == 220
    plans[0].run_times = 2
    plans[1].run_times = 1
    assert remaining_plan_energy(plans) == 60


@pytest.mark.parametrize('setting', ['不使用', '使用以太电池', '同时使用储蓄电量和以太电池', '菲林', ''])
def test_other_sources_cannot_create_reserve_budget(setting: str) -> None:
    with pytest.raises(ValueError, match='仅允许'):
        ReserveChargeBudget(date(2026, 11, 1), 320, setting)


@pytest.mark.parametrize('now', [
    datetime(2026, 10, 31, 15, 59, 59, tzinfo=UTC),
    datetime(2026, 11, 1, 16, tzinfo=UTC),
    datetime(2026, 11, 1, 18, tzinfo=UTC),
    datetime(2026, 11, 1, 12),
])
def test_calendar_guard_is_not_extended_until_game_reset(now: datetime) -> None:
    with pytest.raises(ValueError):
        budget().prepare(snapshot(), 100, 320, 1, 240, now)


def test_minimum_next_battle_shortfall_and_exact_resource_reconciliation() -> None:
    session = budget()
    transfer = session.prepare(snapshot(), 100, 320, 1, 240, NOW)
    assert transfer.amount == 57  # 不把全部储蓄或整份320计划一次领出。
    session.check_confirmation('储蓄电量', 57, snapshot(), NOW)
    assert session.record_result(ChargeResourceSnapshot(100, 943, 6, 100)) == 57
    assert session.restored == 57
    with pytest.raises(ValueError, match='重复记账'):
        session.record_result(ChargeResourceSnapshot(100, 943, 6, 100))


@pytest.mark.parametrize(('before', 'required', 'remaining', 'step', 'maximum', 'expected'), [
    (snapshot(100), 100, 320, 1, 240, None),
    (snapshot(43), 100, 320, 10, 240, 60),
    (snapshot(43), 60, 60, 10, 240, None),  # 凑整会超过最后一场总差额。
    (snapshot(43, 56), 100, 320, 1, 240, None),
    (snapshot(43), 100, 320, 1, 56, None),
])
def test_balance_granularity_and_ui_limit_are_all_enforced(
    before: ChargeResourceSnapshot, required: int, remaining: int,
    step: int, maximum: int, expected: int | None,
) -> None:
    transfer = budget().prepare(before, required, remaining, step, maximum, NOW)
    assert (transfer.amount if transfer else None) == expected


@pytest.mark.parametrize(('source', 'amount', 'current', 'now'), [
    ('以太电池', 57, snapshot(), NOW),
    ('储蓄电量', 60, snapshot(), NOW),
    ('储蓄电量', 57, snapshot(44), NOW),
    ('储蓄电量', 57, snapshot(), datetime(2026, 11, 1, 16, tzinfo=UTC)),
])
def test_confirmation_rechecks_source_amount_balance_and_midnight(
    source: str, amount: int, current: ChargeResourceSnapshot, now: datetime,
) -> None:
    session = budget()
    session.prepare(snapshot(), 100, 320, 1, 240, NOW)
    with pytest.raises(ValueError):
        session.check_confirmation(source, amount, current, now)


@pytest.mark.parametrize('after', [
    ChargeResourceSnapshot(100, 944, 6, 100),
    ChargeResourceSnapshot(101, 943, 6, 100),
    ChargeResourceSnapshot(100, 943, 5, 100),
    ChargeResourceSnapshot(100, 943, 6, 99),
])
def test_unknown_outcome_is_not_retried_or_counted(after: ChargeResourceSnapshot) -> None:
    session = budget()
    session.prepare(snapshot(), 100, 320, 1, 240, NOW)
    session.check_confirmation('储蓄电量', 57, snapshot(), NOW)
    with pytest.raises(ValueError, match='未能对账'):
        session.record_result(after)
    assert session.restored == 0 and session.pending is not None
    with pytest.raises(ValueError, match='禁止再次领取'):
        session.prepare(after, 100, 320, 1, 240, NOW)


def test_total_allowance_cannot_be_reused_after_verified_transfer() -> None:
    session = budget(60)
    session.prepare(snapshot(), 100, 320, 1, 240, NOW)
    session.check_confirmation('储蓄电量', 57, snapshot(), NOW)
    session.record_result(ChargeResourceSnapshot(100, 943, 6, 100))
    assert session.prepare(ChargeResourceSnapshot(0, 943, 6, 100), 100, 220, 1, 240, NOW) is None


def test_confirmation_permission_is_single_use_until_reconciled() -> None:
    session = budget()
    session.prepare(snapshot(), 100, 320, 1, 240, NOW)
    with pytest.raises(ValueError, match='尚未核对'):
        session.record_result(ChargeResourceSnapshot(100, 943, 6, 100))
    session.check_confirmation('储蓄电量', 57, snapshot(), NOW)
    with pytest.raises(ValueError, match='禁止重发'):
        session.check_confirmation('储蓄电量', 57, snapshot(), NOW)


@pytest.mark.parametrize('plan', [
    ChargePlanItem(card_num='默认数量'),
    ChargePlanItem(category_name='合成电池'),
    ChargePlanItem(category_name='区域巡防', mission_type_name='代理人方案培养'),
    ChargePlanItem(run_times=2, plan_times=1),
])
def test_ambiguous_or_invalid_plans_cannot_request_reserve(plan: ChargePlanItem) -> None:
    with pytest.raises(ValueError):
        remaining_plan_energy([plan])


@pytest.mark.parametrize('value', [-1, None, True, '43'])
def test_unknown_or_invalid_ocr_values_do_not_become_zero(value: object) -> None:
    with pytest.raises(ValueError, match='已核实'):
        ChargeResourceSnapshot(value, 1000, 6, 100)
