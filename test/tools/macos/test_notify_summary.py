"""Mac 结果通知复用本账户记录，构造假渠道，不向外部发送。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.application_base import Application
from one_dragon.base.operation.application_run_record import AppRunRecord
from zzz_od.application.notify.notify_app import NotifyApp
from zzz_od.macos.application_capabilities import get_macos_app_unavailable_reason


def test_report_status_and_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('sys.platform', 'darwin')
    assert get_macos_app_unavailable_reason('notify') is None
    ctx = Mock()
    ctx.current_instance_idx = 2
    app = NotifyApp(ctx)
    assert not app.need_check_game_win
    monkeypatch.setattr(Application, 'execute', lambda op: True)
    assert app.execute() is True
    ctx.macos_session_preparation.prepare.assert_not_called()
    app._after_round_wait = Mock()
    group = ctx.app_group_manager.get_one_dragon_group_config.return_value
    group.app_list = [
        SimpleNamespace(app_id='a', app_name='甲', enabled=True),
        SimpleNamespace(app_id='b', app_name='乙', enabled=True),
        SimpleNamespace(app_id='c', app_name='丙', enabled=False),
    ]
    now = datetime.now().strftime('%m-%d %H:%M')
    ctx.run_context.get_run_record.side_effect = [
        SimpleNamespace(run_time=now, run_status_under_now=status)
        for status in (AppRunRecord.STATUS_SUCCESS, AppRunRecord.STATUS_FAIL)
    ]
    ctx.push_service.push.return_value = (True, '')
    assert not app.notify().is_success
    message = ctx.push_service.push.call_args.kwargs['content']
    assert '成功指令：甲' in message and '失败指令：乙' in message and '丙' not in message
    group.app_list = []
    ctx.push_service.push.return_value = (False, '没有可用的推送渠道')
    assert app.notify().status == '没有可用的推送渠道'
    assert '近期没有已结束的启用任务' in ctx.push_service.push.call_args.kwargs['content']
