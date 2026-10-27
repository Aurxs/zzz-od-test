"""无窗口入口仅验证调度、结果和退出，不连接真实设备。"""

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunResult,
    RunFinishReason,
)
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.context import zzz_context
from zzz_od.macos import cli


def make_context() -> SimpleNamespace:
    """当前账户含一个启用任务和一个禁用任务。"""
    group = SimpleNamespace(app_list=[
        SimpleNamespace(app_id='coffee', enabled=True),
        SimpleNamespace(app_id='charge_plan', enabled=False),
    ])
    run_context = SimpleNamespace(
        is_app_registered=Mock(return_value=True),
        is_app_standalone_available=Mock(return_value=False),
        default_group_apps=['coffee', 'charge_plan'],
        get_application_name=Mock(side_effect=lambda app_id: app_id),
        get_run_record=Mock(return_value=SimpleNamespace(run_status=1)),
        last_application_result=SimpleNamespace(status='全部结束'),
        stop_running=Mock(),
    )
    return SimpleNamespace(
        current_instance_idx=2,
        game_account_config=SimpleNamespace(platform='macos_playcover'),
        one_dragon_config=SimpleNamespace(instance_run='仅运行当前', after_done='无'),
        run_context=run_context,
        app_group_manager=SimpleNamespace(
            get_one_dragon_group_config=Mock(return_value=group), set_default_apps=Mock(),
        ),
        get_application_unavailable_reason=Mock(return_value=None),
        register_application_factory=Mock(), init=Mock(), after_app_shutdown=Mock(),
    )


def test_preview_uses_saved_enabled_tasks_without_initializing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """一条龙虽是内部入口仍可调用，预览不初始化控制器或模型。"""
    ctx = make_context()
    monkeypatch.setattr(zzz_context, 'ZContext', lambda: ctx)
    monkeypatch.setattr(cli.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(cli.sys, 'platform', 'darwin')
    assert cli.main(['--dry-run']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['instance_idx'] == 2
    assert [task['app_id'] for task in output['tasks']] == ['coffee']
    ctx.init.assert_not_called()
    ctx.run_context.get_run_record.assert_not_called()
    ctx.after_app_shutdown.assert_called_once()


def test_internal_or_unsupported_task_is_rejected() -> None:
    """禁止借命令行绕过固定入口和 Mac 能力限制。"""
    ctx = make_context()
    with pytest.raises(ValueError, match='不可独立'):
        cli.validate_request(ctx, 'internal')
    ctx.run_context.is_app_standalone_available.return_value = True
    ctx.get_application_unavailable_reason.return_value = 'Mac暂未适配'
    with pytest.raises(ValueError, match='Mac暂未适配'):
        cli.validate_request(ctx, 'email')


@pytest.mark.parametrize(('reason', 'record_status', 'expected'), [
    (RunFinishReason.COMPLETED, 1, 0),
    (RunFinishReason.COMPLETED, 2, 1),
    (RunFinishReason.FAILED, 1, 1),
    (RunFinishReason.STOPPED, 1, 1),
])
def test_exit_code_includes_child_failure(
    reason: RunFinishReason, record_status: int, expected: int,
) -> None:
    """组全部结束不能覆盖子任务失败，禁用任务不参与结果。"""
    ctx = make_context()
    ctx.run_context.get_run_record.return_value.run_status = record_status
    result = ApplicationRunResult(reason, 'one_dragon', 2, 'one_dragon')
    output, code = cli.summarize_result(ctx, result)
    assert code == expected
    assert output['success'] is (expected == 0)
    assert output['failed_apps'] == (['coffee'] if record_status == 2 else [])
    ctx.run_context.get_run_record.assert_called_once_with('coffee', 2)


def test_interrupt_keeps_pumping_until_worker_releases() -> None:
    """主线程持续处理事件，工作线程收到停止后完成清理再返回。"""
    ctx = make_context()
    interrupted = threading.Event()
    stopped = threading.Event()
    main_thread = threading.get_ident()
    result = ApplicationRunResult(RunFinishReason.STOPPED, 'coffee', 2, 'one_dragon')

    def run(app_id: str, instance_idx: int, group_id: str) -> ApplicationRunResult:
        assert threading.get_ident() != main_thread
        assert (app_id, instance_idx, group_id) == ('coffee', 2, 'one_dragon')
        assert stopped.wait(timeout=2)
        return result

    def pump() -> None:
        assert threading.get_ident() == main_thread
        interrupted.set()
        stopped.wait(timeout=0.001)

    ctx.run_context.run_application = run
    ctx.run_context.stop_running.side_effect = stopped.set
    assert cli.run_session(ctx, 'coffee', pump, interrupted) is result
    assert stopped.is_set()


def test_cleanup_without_controller_still_stops_detection() -> None:
    """预览和初始化失败时无需控制器，也必须停止检测。"""
    ctx = SimpleNamespace(
        ctx=SimpleNamespace(controller=None), dodge_context=SimpleNamespace(stop_context=Mock()),
        _release_keys=Mock(),
    )
    AutoBattleContext.stop_context(ctx)
    ctx.dodge_context.stop_context.assert_called_once()
    ctx._release_keys.assert_not_called()
