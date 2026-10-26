"""每日签到沿用原选择，Mac 只派发一个手柄操作。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.application.daily_signin import daily_signin_app
from zzz_od.application.daily_signin.daily_signin_app import DailySignInApp
from zzz_od.operation.gamepad import signin


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_platform_dispatch_preserves_one_selected_sign(
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 不进入 PC 子应用，Windows 仍执行用户选择的原子应用。"""
    app = DailySignInApp.__new__(DailySignInApp)
    app.ctx = SimpleNamespace(run_context=Mock())
    app.instance_idx = 2
    app.group_id = 'one_dragon'
    app.config = SimpleNamespace(selected_sign='trigrams_collection')
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(daily_signin_app, 'sys', SimpleNamespace(platform=platform))
    gamepad = Mock()
    gamepad.return_value.execute.return_value = OperationResult(True, '今日已领取')
    monkeypatch.setattr(signin, 'GamepadDailySignIn', gamepad)
    app.ctx.run_context.get_application.return_value.execute.return_value = OperationResult(
        True, '原签到应用完成'
    )

    result = app.run_sub_app()

    assert result.is_success
    if platform == 'darwin':
        assert result.status == '今日已领取'
        gamepad.assert_called_once_with(app.ctx, 'trigrams_collection')
        gamepad.return_value.execute.assert_called_once_with()
        app.ctx.run_context.get_application.assert_not_called()
    else:
        assert result.status == '原签到应用完成'
        app.ctx.run_context.get_application.assert_called_once_with(
            app_id='trigrams_collection', instance_idx=2, group_id='one_dragon'
        )
        gamepad.assert_not_called()


def test_missing_selection_does_not_run_any_signin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空选项不能回退到另一种签到。"""
    app = DailySignInApp.__new__(DailySignInApp)
    app.ctx = SimpleNamespace(run_context=Mock())
    app.config = SimpleNamespace(selected_sign='')
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    gamepad = Mock()
    monkeypatch.setattr(signin, 'GamepadDailySignIn', gamepad)

    assert app.run_sub_app().status == '未选择子应用'
    gamepad.assert_not_called()
    app.ctx.run_context.get_application.assert_not_called()
