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

from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.reserve_charge import ChargeResourceSnapshot
from zzz_od.operation.gamepad.restore_reserve_charge import (
    GamepadRestoreReserveCharge,
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
    op = GamepadRestoreReserveCharge(
        SimpleNamespace(
            controller=Mock(spec=['btn_tap', 'click']),
            current_instance_idx=2,
            run_context=Mock(),
        ),
        config(),
    )
    op._after_round_wait = Mock()
    return op


@pytest.mark.parametrize(
    'change', ['no_date', 'expired', 'unlimited', 'batteries', 'unfinished_first']
)
def test_invalid_permission_or_unfinished_first_stage_stays_blocked(
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
    else:
        c.plan_list[0].run_times = 1
    with pytest.raises(ValueError):
        reserve_budget(c)


def test_resource_snapshot_requires_all_three_balances_and_reserve_focus(
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
    assert op._snapshot(17) == ChargeResourceSnapshot(17, 1406, 5, 948)
    frames.return_value = [SimpleNamespace(center=SimpleNamespace(x=220))]
    assert op._snapshot(17) is None
    frames.return_value = [SimpleNamespace(center=SimpleNamespace(x=80))]
    del words['948']
    assert op._snapshot(17) is None


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
        '手柄-兑换确认': {'确认'},
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
    assert op.confirm_quantity().is_success
    assert op.confirm_quantity().is_success
    assert events == ['confirmation_issued', 'south']


def test_pending_journal_blocks_new_process_before_any_input(tmp_path: Path) -> None:
    op = operation()
    op.journal = tmp_path / 'pending.json'
    op.journal.write_text(json.dumps({'state': 'confirmation_issued'}))
    assert op.open_source().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


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
