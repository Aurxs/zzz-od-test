"""验证原应用的平台入口和批次完成语义。"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.application_run_record import AppRunRecord
from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.hollow_zero.hollow_eval_speed.hollow_eval_speed_app import (
    HollowEvalSpeedApp,
)
from zzz_od.application.hollow_zero.withered_domain.withered_domain_app import (
    WitheredDomainApp,
)
from zzz_od.operation.gamepad import hollow_eval_board, hollow_eval_run


def test_original_app_uses_mac_child_and_preserves_windows_route(monkeypatch: pytest.MonkeyPatch) -> None:
    app = object.__new__(HollowEvalSpeedApp)
    app.ctx = SimpleNamespace(run_context=SimpleNamespace(is_context_running=True))
    app._after_round_wait = Mock()
    app.run_record = SimpleNamespace(run_status_under_now=AppRunRecord.STATUS_WAIT, update_status=Mock())
    legacy = Mock(return_value='Windows')
    child = Mock(return_value=SimpleNamespace(
        execute=lambda: OperationResult(False, '最终回执未确认'),
    ))
    monkeypatch.setattr(WitheredDomainApp, 'check_first_screen', legacy)
    monkeypatch.setattr(hollow_eval_run, 'GamepadHollowEvalRun', child)
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert app.check_first_screen() == 'Windows'
    child.assert_not_called()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    assert app.check_first_screen().is_fail
    child.assert_called_once_with(app.ctx)
    app._update_record_after_stop(OperationResult(False, '最终回执未确认'))
    app.run_record.update_status.assert_not_called()


def test_continuing_batch_keeps_same_exploration_instead_of_reporting_success(monkeypatch: pytest.MonkeyPatch) -> None:
    op = hollow_eval_board.GamepadHollowEvalExplore(SimpleNamespace(), max_steps=1, continue_batches=True)
    op._after_round_wait = Mock()
    op.event.identify_entry = Mock(return_value=None)
    op.event.try_respond = Mock(return_value=None)
    op.step.move = Mock(return_value=SimpleNamespace(is_fail=False, is_success=True, status='核对了一格'))
    monkeypatch.setattr(hollow_eval_board, 'is_native_battle', Mock(return_value=False))
    for expected in (1, 2):
        result = op.explore()
        assert not result.is_success
        assert result.status == f'已核对{expected}格，继续本局'
        assert op.completed == expected


def test_stop_observation_is_handed_to_verified_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    run = hollow_eval_run.GamepadHollowEvalRun(SimpleNamespace())
    run._after_round_wait = Mock()
    evidence = {'floor': 3, 'empty_merit_tile': True}
    child = Mock(return_value=SimpleNamespace(execute=lambda: OperationResult(
        True, hollow_eval_board.GamepadHollowEvalStep.STATUS_READY_TO_LEAVE, evidence,
    )))
    monkeypatch.setattr(hollow_eval_run, 'GamepadHollowEvalExplore', child)
    finish = Mock(return_value=SimpleNamespace(execute=lambda: OperationResult(False, '退出尚未核实', evidence)))
    monkeypatch.setattr(hollow_eval_run, 'GamepadHollowEvalFinish', finish)
    result = run.explore()
    assert result.is_fail
    assert result.data == evidence
    child.assert_called_once_with(run.ctx, continue_batches=True)
    finish.assert_called_once_with(run.ctx, evidence)


def test_verified_return_counts_one_entry_without_recording_merit(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad.hollow_eval_exit import GamepadHollowEvalFinish

    app = object.__new__(HollowEvalSpeedApp)
    app.ctx = SimpleNamespace(run_context=SimpleNamespace(is_context_running=True))
    app._after_round_wait = Mock()
    app.run_record = SimpleNamespace(
        run_status_under_now=AppRunRecord.STATUS_WAIT, daily_run_times=1, update=Mock(),
        update_status=Mock(), check_and_update_status=Mock(),
    )
    child = Mock(return_value=SimpleNamespace(execute=lambda: OperationResult(
        True, GamepadHollowEvalFinish.STATUS_RETURNED,
        {'merit_increase': None, 'weekly_cap_confirmed': False},
    )))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(hollow_eval_run, 'GamepadHollowEvalRun', child)
    assert app.check_first_screen().is_fail
    child.assert_called_once_with(app.ctx)
    app.run_record.update.assert_called_once_with('daily_run_times', 2, save=False)
    app.run_record.update_status.assert_called_once_with(AppRunRecord.STATUS_FAIL)


def test_post_settlement_backs_out_each_verified_entrance_once() -> None:
    from zzz_od.operation.gamepad.hollow_eval_exit import GamepadHollowEvalFinish

    op = GamepadHollowEvalFinish(SimpleNamespace(controller=Mock()), {
        'floor': 3, 'empty_merit_tile': False, 'screenshot': 'stop',
    })
    op._after_round_wait = Mock()
    op._entrance._has_labels = Mock(return_value=True)
    op._entrance.transport._at_hollow_hub = Mock(return_value=True)
    for _ in range(2):
        assert '枯萎区域选择' in op._leave_entrances().status
    op._entrance._has_labels.return_value = False
    for _ in range(2):
        assert '零号空洞公共入口' in op._leave_entrances().status
    assert [item.args[0] for item in op.ctx.controller.btn_tap.call_args_list] == ['east', 'east']
