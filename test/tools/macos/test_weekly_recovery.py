"""周活只在已识别的游戏画面中选择入口或恢复战斗。"""

from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.application.intel_board.intel_board_app import IntelBoardApp
from zzz_od.operation.gamepad import intel_board, notorious_hunt
from zzz_od.operation.gamepad.function_guide import GamepadOpenFunction


@pytest.mark.parametrize('module,class_name,reader', [
    (notorious_hunt, 'GamepadHuntBattle', 'read_hunt_result'),
    (intel_board, 'GamepadIntelBattle', 'read_intel_result'),
])
def test_missing_frame_requires_checked_recovery(
    module: ModuleType, class_name: str, reader: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = SimpleNamespace(controller=Mock(), auto_battle_context=Mock(), run_context=Mock())
    ctx.controller.battle_input_blocked = False
    ctx.controller.refresh_battle_input_scope.side_effect = [False, True]
    cls = getattr(module, class_name)
    if module is notorious_hunt:
        monkeypatch.setattr('zzz_od.operation.compendium.notorious_hunt.NotoriousHunt', Mock())
        operation = cls(ctx, Mock())
    else:
        operation = cls(ctx)
    check_result = Mock(return_value=None)
    monkeypatch.setattr(module, reader, check_result)
    operation._after_round_wait = Mock()
    operation._active = True
    operation.last_screenshot = None

    operation.battle()
    operation.battle()
    ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    ctx.controller.refresh_battle_input_scope.assert_not_called()
    ctx.auto_battle_context.check_battle_state.assert_not_called()
    check_result.assert_not_called()
    if module is notorious_hunt:
        operation.original.auto_battle.assert_not_called()

    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.battle()
    ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    operation.battle()
    ctx.auto_battle_context.resume_auto_battle.assert_called_once()


def test_themed_intel_requires_unique_focus_aligned_with_label() -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), ocr=Mock())
    operation = GamepadOpenFunction(ctx, '情报板')
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation._save_evidence = Mock()
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    target = Rect(184, 434, 236, 454)
    class SingleMatch(list):
        max = SimpleNamespace(rect=target)

    cards = {'COMMUNITY': [], '仓库': [], '个人主页': [], '情报板': SingleMatch([target])}
    hints = {'导览套件': [], '选择': [], '返回': []}
    ctx.ocr.crop_and_run_ocr.side_effect = lambda _, rect: cards if rect.x1 == 1225 else hints
    operation._read_area = Mock(return_value=None)

    operation.select_function()
    ctx.controller.btn_tap.assert_not_called()

    # 上边被遮挡的外框仍须保留独立的下、左和右边。
    panel = operation.last_screenshot[350:945, 1225:1800]
    cv2.rectangle(panel, (12, 50), (139, 117), (255, 255, 0), 4)
    panel[45:57, 9:143] = 0
    operation.select_function()
    operation.select_function()
    ctx.controller.btn_tap.assert_called_once_with('dpad_down')

    panel[:] = 0
    cv2.rectangle(panel, (148, 365), (275, 425), (255, 255, 0), 4)
    cv2.rectangle(panel, (14, 365), (140, 425), (255, 255, 0), 4)
    operation.select_function()
    ctx.controller.btn_tap.assert_called_once_with('dpad_down')
    panel[:, :144] = 0
    operation.select_function()
    assert [call.args[0] for call in ctx.controller.btn_tap.call_args_list] == ['dpad_down', 'south']


@pytest.mark.parametrize('progress,status,full', [
    ('1000/1000', '完成', True),
    ('70／1000', '继续', False),
    ('10001000', IntelBoardApp.STATUS_UNCONFIRMED_PROGRESS, False),
])
def test_progress_must_be_read_before_commission(
    progress: str, status: str, full: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr('zzz_od.application.intel_board.intel_board_app.sys.platform', 'darwin')
    app = object.__new__(IntelBoardApp)
    app.ctx = Mock()
    app.ctx.screen_loader.get_area.return_value.rect = Rect(0, 0, 5, 5)
    app.ctx.ocr.run_ocr_single_line.return_value = progress
    app.config = SimpleNamespace(exp_grind_mode=False)
    app.run_record = SimpleNamespace(progress_complete=False)
    app.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    app.node_retry_times = 0
    app.round_success = Mock(side_effect=lambda value: value)
    app.round_fail = Mock(side_effect=lambda value: value)
    app.round_retry = Mock(side_effect=lambda value, **_: value)
    app.save_screenshot = Mock()

    assert app.check_progress() == status
    assert app.run_record.progress_complete is full
