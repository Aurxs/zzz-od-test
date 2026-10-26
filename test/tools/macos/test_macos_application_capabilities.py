"""验证原客户端的 Mac 运行限制与会话缓存，不连接游戏。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.config.one_dragon_config import AfterDoneOpEnum, InstanceRun
from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.application_base import Application
from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application import zzz_application
from zzz_od.application.one_dragon_app import zzz_one_dragon_app
from zzz_od.macos import application_capabilities, game_session_preparation


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """只保留原任务列表与运行状态，不读写实际配置。"""
    for module in (application_capabilities, zzz_application, zzz_one_dragon_app):
        monkeypatch.setattr(module, 'sys', SimpleNamespace(platform='darwin'))
    group = SimpleNamespace(app_list=[
        SimpleNamespace(app_id='charge_plan', app_name='体力计划', enabled=True),
        SimpleNamespace(app_id='email', app_name='邮件', enabled=False),
    ])
    manager = Mock()
    manager.get_one_dragon_group_config.return_value = group
    return SimpleNamespace(
        current_instance_idx=2,
        controller=SimpleNamespace(run_generation=1),
        is_game_window_ready=True,
        one_dragon_config=SimpleNamespace(
            instance_run=InstanceRun.CURRENT.value.value,
            after_done=AfterDoneOpEnum.NONE.value.value,
            instance_list_in_od=[SimpleNamespace(idx=2)],
        ),
        app_group_manager=manager,
        run_context=SimpleNamespace(is_context_stop=False),
        macos_session_preparation=Mock(),
    )


def test_unsupported_enabled_tasks_fail_without_changing_config(context: SimpleNamespace) -> None:
    """保留任务顺序和开关，只有明确关闭未适配任务后才允许运行。"""
    group = context.app_group_manager.get_one_dragon_group_config.return_value
    assert application_capabilities.get_macos_one_dragon_unavailable_reason(context) is None
    group.app_list[1].enabled = True
    reason = application_capabilities.get_macos_one_dragon_unavailable_reason(context)
    assert '邮件' in reason
    assert [item.app_id for item in group.app_list] == ['charge_plan', 'email']
    assert all(item.enabled for item in group.app_list)
    context.app_group_manager.set_one_dragon_app_enable.assert_not_called()


def test_multi_account_and_system_actions_fail_before_preparation(context: SimpleNamespace) -> None:
    """跨实例与结束后系统操作均不给原 Windows 执行路径放行。"""
    config = context.one_dragon_config
    config.instance_run = InstanceRun.ALL.value.value
    config.instance_list_in_od.append(SimpleNamespace(idx=1))
    assert '多账号' in application_capabilities.get_macos_one_dragon_unavailable_reason(context)
    config.instance_run = InstanceRun.CURRENT.value.value
    config.after_done = AfterDoneOpEnum.SHUTDOWN.value.value
    assert '结束后' in application_capabilities.get_macos_one_dragon_unavailable_reason(context)
    context.macos_session_preparation.prepare.assert_not_called()


@pytest.mark.parametrize('app_id, supported', [('charge_plan', True), ('random_play', True), ('coffee', True),
    ('engagement_reward', True), ('city_fund', True), ('daily_signin', True),
    ('ridu_weekly', False), ('email', False)])
def test_application_checks_capability_and_prepares_even_with_ready_window(
    monkeypatch: pytest.MonkeyPatch, context: SimpleNamespace, app_id: str, supported: bool,
) -> None:
    """已连接窗口仍显式准备；未适配任务在任何准备或执行前停止。"""
    context.macos_session_preparation.prepare.return_value = OperationResult(True)
    framework = Mock(return_value=OperationResult(True))
    monkeypatch.setattr(Application, 'execute', framework)
    app = zzz_application.ZApplication.__new__(zzz_application.ZApplication)
    app.ctx = context
    app.app_id = app_id

    result = app.execute()

    assert result.success is supported
    assert context.macos_session_preparation.prepare.call_count == int(supported)
    assert framework.call_count == int(supported)


def test_preparation_cache_is_only_for_current_run_and_controller(
    monkeypatch: pytest.MonkeyPatch, context: SimpleNamespace,
) -> None:
    """同次子任务复用；停止、重连和更换控制器不会复用旧准备结果。"""
    factory = Mock()
    factory.return_value.execute.return_value = OperationResult(True, status='已确认手柄大世界')
    monkeypatch.setattr(game_session_preparation, 'create_game_session_entry', factory)
    service = game_session_preparation.MacGameSessionPreparation(context)
    assert service.prepare().success
    assert service.prepare().success
    assert factory.call_count == 1
    context.run_context.is_context_stop = True
    assert not service.prepare().success
    context.run_context.is_context_stop = False
    context.controller.run_generation += 1
    assert service.prepare().success
    context.controller = SimpleNamespace(run_generation=1)
    assert service.prepare().success
    assert factory.call_count == 3


def test_failed_preparation_never_runs_application(
    monkeypatch: pytest.MonkeyPatch, context: SimpleNamespace,
) -> None:
    """输入模式未确认时，不开始原体力计划。"""
    context.macos_session_preparation.prepare.return_value = OperationResult(False, status='未确认模式')
    framework = Mock()
    monkeypatch.setattr(Application, 'execute', framework)
    app = zzz_application.ZApplication.__new__(zzz_application.ZApplication)
    app.ctx = context
    app.app_id = 'charge_plan'
    assert app.execute().status == '未确认模式'
    framework.assert_not_called()


def test_macos_single_instance_finishes_without_rebuilding_controller(context: SimpleNamespace) -> None:
    """原一条龙的实例收尾节点不再无谓地切换到自身。"""
    app = zzz_one_dragon_app.ZOneDragonApp.__new__(zzz_one_dragon_app.ZOneDragonApp)
    app.ctx = context
    assert app.switch_instance().is_success
    assert context.controller.run_generation == 1


def test_windows_capabilities_leave_original_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 不读取 Mac 账户限制，也不改变任何原应用的可运行性。"""
    monkeypatch.setattr(application_capabilities, 'sys', SimpleNamespace(platform='win32'))
    assert application_capabilities.get_macos_app_unavailable_reason('email') is None
    assert application_capabilities.get_macos_one_dragon_unavailable_reason(SimpleNamespace()) is None
    assert application_const.ONE_DRAGON_APP_ID in application_capabilities.MACOS_SUPPORTED_APP_IDS


def test_windows_application_uses_original_execute_without_mac_preparation(
    monkeypatch: pytest.MonkeyPatch, context: SimpleNamespace,
) -> None:
    """原 Windows 应用执行不受 Mac 支持列表和准备服务影响。"""
    for module in (application_capabilities, zzz_application):
        monkeypatch.setattr(module, 'sys', SimpleNamespace(platform='win32'))
    framework = Mock(return_value=OperationResult(True))
    monkeypatch.setattr(Application, 'execute', framework)
    app = zzz_application.ZApplication.__new__(zzz_application.ZApplication)
    app.ctx = context
    app.app_id = 'email'
    assert app.execute().success
    framework.assert_called_once_with(app)
    context.macos_session_preparation.prepare.assert_not_called()
