"""验证 Mac 启动识别失败时的本机诊断证据，不连接真实游戏。"""

import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
from test_mac_bootstrap_game_session import show

from zzz_od.operation.enter_game import mac_bootstrap_game_session as bootstrap

pytest_plugins = ['test_mac_bootstrap_game_session']


def test_unknown_screen_saves_private_local_frame_and_stage(session, monkeypatch, tmp_path):
    """仅在八帧未知后保存遮挡过 UID 的现有帧，并保留动作阶段。"""
    original_mkdtemp = tempfile.mkdtemp

    def private_dir(*, prefix, dir):
        assert dir == '/tmp'
        return original_mkdtemp(prefix=prefix, dir=tmp_path)

    monkeypatch.setattr(bootstrap.tempfile, 'mkdtemp', private_dir)
    warning = Mock()
    monkeypatch.setattr(bootstrap.log, 'warning', warning)
    session.operation._sent_actions.add('打开登录设置')
    for _ in range(8):
        show(session, 'unknown', {})
        result = session.operation.prepare_session()
    assert result.is_fail
    paths = list(tmp_path.glob('zzz-bootstrap-*/failure.png'))
    assert len(paths) == 1
    path = paths[0]
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert np.array_equal(cv2.imread(str(path)), np.zeros((1080, 1920, 3), dtype=np.uint8))
    args = warning.call_args.args
    assert args[1] == '启动识别'
    assert args[3] == 8
    assert args[4] == ['打开登录设置']
    assert args[5] == str(path)
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


def test_failure_without_current_frame_does_not_save_stale_image(session, monkeypatch):
    """流不可用时只记录无帧，不将之前的截图当作当前画面。"""
    op = session.operation
    op.ctx.is_game_window_ready = False
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.last_screenshot_time = 100
    writer = Mock()
    warning = Mock()
    monkeypatch.setattr(bootstrap.tempfile, 'mkdtemp', writer)
    monkeypatch.setattr(bootstrap.log, 'warning', warning)
    assert op._failure_with_evidence('冷启动识别', '失败').is_fail
    writer.assert_not_called()
    assert warning.call_args.args[-1] == '无有效新帧'


def test_failure_to_write_evidence_preserves_stop(session, monkeypatch):
    """编码失败不会放行未知页面或改变原失败状态。"""
    monkeypatch.setattr(bootstrap.cv2, 'imencode', Mock(side_effect=OSError('test')))
    for _ in range(8):
        show(session, 'unknown', {})
        result = session.operation.prepare_session()
    assert result.is_fail
    assert result.status == '未识别到已支持的 Mac 启动画面，已停止且未猜测点击'
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


def test_framework_timeout_records_phase_without_stale_frame(session, monkeypatch):
    """外层总超时仍保留阶段，但不保存可能过期的截图。"""
    op = session.operation
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.last_screenshot_time = 100
    writer = Mock()
    warning = Mock()
    after = Mock()
    monkeypatch.setattr(bootstrap.tempfile, 'mkdtemp', writer)
    monkeypatch.setattr(bootstrap.log, 'warning', warning)
    monkeypatch.setattr(bootstrap.Operation, 'after_operation_done', after)
    result = SimpleNamespace(success=False, status=bootstrap.Operation.STATUS_TIMEOUT)
    op.after_operation_done(result)
    writer.assert_not_called()
    assert warning.call_args.args[1] == '流程超时'
    assert warning.call_args.args[-1] == '无有效新帧'
    after.assert_called_once_with(result)
