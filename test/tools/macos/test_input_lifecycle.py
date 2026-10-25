"""验证上层暂停会先关闭输入，恢复失败不会继续任务。"""

from types import SimpleNamespace
from unittest.mock import Mock

from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunContext,
    ApplicationRunContextStateEnum,
)
from one_dragon.base.operation.operation import Operation


def make_run_context(controller: object) -> ApplicationRunContext:
    """只创建生命周期测试需要的状态，不创建执行线程。"""
    context = ApplicationRunContext.__new__(ApplicationRunContext)
    context.ctx = SimpleNamespace(controller=controller)
    context._run_state = ApplicationRunContextStateEnum.RUNNING
    context.event_bus = Mock()
    return context


def test_pause_closes_input_before_event_and_resume_failure_stays_paused() -> None:
    """异步暂停通知发出前先禁止输入，恢复失败不得宣布运行。"""
    calls: list[str] = []
    controller = SimpleNamespace(
        pause_input=lambda: calls.append('suspended'),
        resume_input=Mock(side_effect=RuntimeError('连接已断开')),
    )
    context = make_run_context(controller)
    context.event_bus.dispatch_event.side_effect = lambda *_: calls.append('event')

    context.switch_context_pause_and_run()
    assert calls == ['suspended', 'event']
    assert context.is_context_pause
    context.switch_context_pause_and_run()
    assert context.is_context_pause
    assert calls == ['suspended', 'event']


def test_existing_controller_without_new_hooks_keeps_lifecycle() -> None:
    """既有控制器不实现新接口时，原暂停恢复仍正常。"""
    context = make_run_context(object())
    context.switch_context_pause_and_run()
    assert context.is_context_pause
    context.switch_context_pause_and_run()
    assert context.is_context_running


def test_missing_macos_window_reports_failure_without_pc_window() -> None:
    """窗口缺失是正常失败，不访问不存在的 PcGameWindow。"""
    operation = Operation.__new__(Operation)
    operation.ctx = SimpleNamespace(
        is_game_window_ready=False,
        controller=SimpleNamespace(game_window_description='PlayCover 绝区零'),
    )
    result = operation.check_game_window()
    assert result.is_fail
    assert result.status == '未打开游戏窗口 PlayCover 绝区零'
