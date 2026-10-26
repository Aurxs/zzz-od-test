"""界面等待沿用更长动画时长，实时战斗不加延迟。"""

from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.gamepad_operation import GamepadOperation
from zzz_od.operation.gamepad.predefined_team import GamepadOpenPredefinedTeam
from zzz_od.operation.zzz_operation import ZOperation


def test_menu_delay_and_battle_exemption(monkeypatch) -> None:
    """通用等待取最大值，明确豁免的战斗节点保持原参数。"""
    wait = Mock()
    monkeypatch.setattr(ZOperation, '_after_round_wait', wait)
    op = object.__new__(GamepadOperation)
    op.ctx = SimpleNamespace(macos_config=SimpleNamespace(menu_action_interval_ms=500))
    op._current_node = SimpleNamespace(cn='菜单')
    op._after_round_wait()
    wait.assert_called_with(0.5)
    op._after_round_wait(1)
    wait.assert_called_with(1)
    op.realtime_nodes = frozenset({'战斗'})
    op._current_node.cn = '战斗'
    op._after_round_wait(0.1)
    wait.assert_called_with(0.1, None)


def test_ready_page_retries_lost_open_input() -> None:
    """仅仍在出战准备时重试 X，识别到列表后不再发送。"""
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock(), ocr=Mock())
    op = GamepadOpenPredefinedTeam(ctx)
    op._after_round_wait = Mock()
    op.last_screenshot = object()
    op.ctx.ocr.run_ocr.return_value = {'出战': [], '预备编队': []}
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    for _ in range(3):
        op.open_teams()
    assert ctx.controller.btn_tap.call_count == 2
    ctx.ocr.run_ocr.return_value = {'预备出战': []}
    assert op.open_teams().is_success
    assert ctx.controller.btn_tap.call_count == 2


def test_windows_keeps_original_wait(monkeypatch) -> None:
    """共用商店应用在 Windows 不读取 Mac 配置，也不增加等待。"""
    from zzz_od.operation.gamepad import gamepad_operation

    monkeypatch.setattr(gamepad_operation, 'sys', SimpleNamespace(platform='win32'))
    wait = Mock()
    monkeypatch.setattr(ZOperation, '_after_round_wait', wait)
    op = object.__new__(GamepadOperation)
    op._after_round_wait(0.2)
    wait.assert_called_once_with(0.2, None)
