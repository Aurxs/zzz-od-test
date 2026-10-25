"""初始化失败不能进入可运行状态，也不能向界面报告已就绪。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunContext,
)
from one_dragon.base.operation.one_dragon_context import OneDragonContext
from zzz_od.context import zzz_context
from zzz_od.gui.app import CtxInitRunner


def test_late_initialization_failure_clears_readiness() -> None:
    """后续服务失败时撤销就绪状态，保留用户可以看到的错误。"""
    context = SimpleNamespace(
        _init_lock=threading.Lock(),
        _application_registered=True,
        custom_config=SimpleNamespace(ui_language='cn'),
        env_config=SimpleNamespace(is_debug=False, is_gh_proxy=False),
        screen_loader=SimpleNamespace(reload=Mock()),
        run_context=SimpleNamespace(check_and_update_all_run_record=Mock()),
        push_service=SimpleNamespace(init_push_channels=Mock(side_effect=RuntimeError('服务初始化失败'))),
        current_instance_idx=1,
        init_ocr=Mock(),
        _load_plugin_screens=Mock(),
        reload_instance_config=Mock(),
        init_controller=Mock(),
        init_for_application=Mock(),
    )

    OneDragonContext.init(context)

    assert context.ready_for_application is False
    assert context.initialization_error == '服务初始化失败'
    assert not context._init_lock.locked()


@pytest.mark.parametrize('ready', [False, True])
def test_gui_runner_only_announces_success_after_context_is_ready(ready: bool) -> None:
    """失败时通知错误，成功时才执行设置发现。"""
    context = SimpleNamespace(
        init=Mock(), ready_for_application=ready,
        initialization_error='请选择 macos_playcover', dispatch_event=Mock(),
    )
    window = Mock()
    runner = CtxInitRunner(context, window)

    runner.run()

    assert window.on_ctx_ready.call_count == int(ready)
    assert context.dispatch_event.call_count == int(not ready)
    if not ready:
        event = context.dispatch_event.call_args.args[1]
        assert event.content == '请选择 macos_playcover'


def test_failed_initialization_does_not_wait_for_run_timeout() -> None:
    """已知初始化失败时立即拒绝启动，不再等待一分钟。"""
    context = SimpleNamespace(ready_for_application=False, initialization_error='配置未完成')
    run_context = ApplicationRunContext.__new__(ApplicationRunContext)
    run_context.ctx = context
    run_context._create_run_result = Mock(return_value='not_started')

    assert run_context.run_application('test', 1, 'test') == 'not_started'


def test_macos_requires_platform_choice_before_model_download(monkeypatch: pytest.MonkeyPatch) -> None:
    """原 PC 实例不自动迁移，也不先触发不必要的模型下载。"""
    context = zzz_context.ZContext.__new__(zzz_context.ZContext)
    context.game_account_config = SimpleNamespace(platform='PC')
    initialize = Mock()
    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(OneDragonContext, 'init', initialize)

    context.init()

    initialize.assert_not_called()
    assert context.game_account_config.platform == 'PC'
    assert context.ready_for_application is False
    assert '账户管理' in context.initialization_error
