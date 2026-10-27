"""任务失败先恢复主界面，恢复失败或手动停止不运行下一任务。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad import application_group
from zzz_od.operation.gamepad.application_group import GamepadGroupApplication
from zzz_od.operation.gamepad.back_to_normal_world import GamepadBackToNormalWorld


def make_group() -> GamepadGroupApplication:
    """运行原组调度逻辑，用两个假任务检查失败记录和执行顺序。"""
    apps = [Mock(app_id='first', op_name='第一项'), Mock(app_id='second', op_name='第二项')]
    apps[0].execute.return_value = OperationResult(False, '执行超时')
    apps[1].execute.return_value = OperationResult(True)
    run = SimpleNamespace(
        current_group_id='one_dragon', current_app_id=None, is_context_running=True,
        get_application=lambda app_id, **_: next(app for app in apps if app.app_id == app_id),
        get_run_record=lambda **_: None,
    )
    op = GamepadGroupApplication(SimpleNamespace(run_context=run, current_instance_idx=2), 'one_dragon')
    op._group_config = SimpleNamespace(app_list=[
        SimpleNamespace(app_id=app.app_id, enabled=True) for app in apps
    ])
    op._after_round_wait = Mock()
    return op


@pytest.mark.parametrize('recovered', [True, False])
def test_failed_task_recovers_before_next_task(
    monkeypatch: pytest.MonkeyPatch, recovered: bool,
) -> None:
    """保留首项失败，只有恢复成功才返回可继续状态。"""
    op = make_group()
    recovery = Mock(return_value=SimpleNamespace(execute=Mock(return_value=OperationResult(recovered, '恢复结果'))))
    monkeypatch.setattr(application_group, 'GamepadBackToNormalWorld', recovery)
    result = op.run_app()
    assert result.is_success == recovered
    assert op._fail_app_idx_list == [0]
    op.ctx.run_context.get_application('second').execute.assert_not_called()
    recovery.assert_called_once_with(op.ctx)
    if recovered:
        assert op.run_app().is_success
        op.ctx.run_context.get_application('second').execute.assert_called_once()
        recovery.assert_called_once()


def test_manual_stop_does_not_recover(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户停止导致的任务失败不能触发返回键。"""
    op = make_group()
    op.ctx.run_context.is_context_running = False
    recovery = Mock()
    monkeypatch.setattr(application_group, 'GamepadBackToNormalWorld', recovery)
    assert op.run_app().is_fail
    recovery.assert_not_called()


@pytest.mark.parametrize('state', ['world', 'back', 'unknown', 'stale', 'limit'])
def test_recovery_only_presses_back_on_recognized_fresh_frame(
    monkeypatch: pytest.MonkeyPatch, state: str,
) -> None:
    """主界面无输入，未知、旧帧和上限均不盲按。"""
    op = GamepadBackToNormalWorld(SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    monkeypatch.setattr(op, 'round_by_find_area', lambda image, screen, area: (
        op.round_success() if (state == 'world' and screen == '大世界-普通')
        or (state in ('back', 'stale', 'limit') and screen == '画面-通用') else op.round_fail()
    ))
    op.last_screenshot = object()
    op.last_screenshot_time = 1
    op.node_retry_times = 3
    if state == 'stale':
        op._last_action_frame_time = 1
    if state == 'limit':
        op._back_count = 6
    result = op.back()
    assert result.is_success == (state == 'world')
    if state == 'back':
        op.ctx.controller.btn_tap.assert_called_once_with('east')
    else:
        op.ctx.controller.btn_tap.assert_not_called()
    if state in ('unknown', 'limit'):
        assert result.is_fail


@pytest.mark.parametrize('relative', [
    '卦象集录/ios_main_current_scale.webp', '丽都周纪/ios_weekly_claimable_progress_ocr.webp',
])
def test_daily_failure_screens_have_existing_return_template(relative: str) -> None:
    """今天两处失败现场均能用已有通用返回模板识别，不新增画面资源。"""
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    area = loader.get_area('画面-通用', '返回')
    image = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / relative))
    assert image is not None
    result = TemplateMatcher(TemplateLoader()).match_template(
        image[area.y1:area.y2, area.x1:area.x2], area.template_sub_dir, area.template_id,
        threshold=area.template_match_threshold,
    )
    assert result.max is not None
