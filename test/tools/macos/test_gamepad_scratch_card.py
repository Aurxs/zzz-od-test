"""验证报刊亭已领分支不会重复开卡或确认。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from one_dragon.base.operation.operation_base import OperationResult
from zzz_od.operation.enter_game.mac_bootstrap_game_session import (
    MacBootstrapGameSession,
)
from zzz_od.operation.gamepad import scratch_card


def test_kiosk_open_and_already_claimed_return(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = scratch_card.GamepadScratchCard(ctx)
    operation.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'round_by_find_area', lambda *_: operation.round_success())
    monkeypatch.setattr(operation, '_key_visible', lambda *_: True)
    monkeypatch.setattr(operation, '_words', lambda _: [])
    monkeypatch.setattr(scratch_card, 'save_shop_frame', lambda *_: 'saved')
    visible = {'手柄-报纸标题', '手柄-刮刮卡提示', '手柄-返回提示'}
    monkeypatch.setattr(scratch_card, '_kiosk_area', lambda _, name: name in visible)

    operation.open_card()
    operation.open_card()
    assert ctx.controller.btn_tap.call_args_list == [call('west')]

    visible.update({'手柄-同类奖励已领', '手柄-确认选择'})
    assert operation.open_card().is_success
    operation.finish()
    operation.finish()
    assert ctx.controller.btn_tap.call_args_list == [call('west'), call('south')]

    visible.remove('手柄-同类奖励已领')
    monkeypatch.setattr(operation, '_world_visible', lambda: False)
    operation.finish()
    assert ctx.controller.btn_tap.call_args_list == [call('west'), call('south'), call('east')]
    monkeypatch.setattr(operation, '_world_visible', lambda: True)
    assert operation.finish().status == '今日已领取'


def test_scratch_once_per_frame_and_confirm_actual_reward(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(is_context_running=True))
    operation = scratch_card.GamepadScratchCard(ctx)
    operation.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    operation.last_screenshot_time = 20
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, '_scratch_ready', lambda: True)
    reward = Mock(return_value=False)
    monkeypatch.setattr(operation, '_known_reward_visible', reward)
    monkeypatch.setattr(operation, '_already_today', lambda: False)
    monkeypatch.setattr(scratch_card, 'save_shop_frame', lambda *_: 'saved')
    monkeypatch.setattr(scratch_card.time, 'sleep', Mock())

    operation.scratch()
    operation.scratch()
    moves = ctx.controller.set_gamepad_stick.call_args_list
    assert len(moves) == 9 * 21 + 1
    assert moves[:21] == [call('right', step / 10, -1) for step in range(-10, 11)]
    assert moves[21] == call('right', 1, -0.75)
    assert moves[-2:] == [call('right', 1, 1), call('right', 0, 0)]
    ctx.controller.btn_tap.assert_not_called()

    reward.return_value = True
    assert operation.scratch().is_success
    operation.finish()
    operation.finish()
    ctx.controller.btn_tap.assert_called_once_with('south')
    reward.return_value = False
    monkeypatch.setattr(operation, '_world_visible', lambda: True)
    assert operation.finish().status == '刮刮卡奖励已领取'


def test_scratch_grid_releases_stick_on_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    run_context = SimpleNamespace(is_context_running=True)
    controller = Mock()
    operation = scratch_card.GamepadScratchCard(SimpleNamespace(controller=controller, run_context=run_context))
    monkeypatch.setattr(scratch_card.time, 'sleep', lambda _: setattr(run_context, 'is_context_running', False))
    operation._sweep_card()
    assert controller.set_gamepad_stick.call_args_list == [call('right', -1, -1), call('right', 0, 0)]


def test_resume_revealed_card_only_sends_return(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(current_app_id='daily_signin', current_group_id='daily'))
    ctx.current_instance_idx = 1
    ctx.run_context.get_config.return_value = SimpleNamespace(selected_sign='scratch_card')
    operation = scratch_card.GamepadScratchCard(ctx)
    operation.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    bootstrap = MacBootstrapGameSession(ctx)
    monkeypatch.setattr(bootstrap, '_after_round_wait', Mock())
    monkeypatch.setattr(scratch_card.GamepadScratchCard, 'can_resume_open_card', lambda _: True)
    assert bootstrap._prepare_from_screen().is_success

    revealed = Mock(return_value=True)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, '_already_today', lambda: False)
    monkeypatch.setattr(operation, '_scratch_ready', lambda: False)
    monkeypatch.setattr(operation, '_card_revealed', revealed)
    monkeypatch.setattr(operation, '_world_visible', lambda: False)
    monkeypatch.setattr(operation, '_key_visible', lambda *_: True)
    monkeypatch.setattr(scratch_card, '_kiosk_area', lambda *_: True)
    monkeypatch.setattr(scratch_card, 'save_shop_frame', lambda *_: 'saved')

    assert operation.open_card().status == operation.STATUS_CARD_REVEALED
    operation.finish()
    operation.finish()
    ctx.controller.btn_tap.assert_called_once_with('east')
    revealed.return_value = False
    operation.finish()
    assert ctx.controller.btn_tap.call_args_list == [call('east'), call('east')]
    monkeypatch.setattr(operation, '_world_visible', lambda: True)
    assert operation.finish().status == '刮刮卡已完成'
    ctx.controller.set_gamepad_stick.assert_not_called()


def test_wake_uses_one_exact_option_then_stops_on_same_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = scratch_card.GamepadScratchCard(ctx)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, '_key_visible', lambda *_: True)
    observations = {
        '手柄-嗷呜对话正文': ['(嗷鸣睡得很香甜，要不要惊动它呢…)'],
        '手柄-嗷呜对话选项': [],
        '手柄-嗷呜醒来文案': [],
    }
    monkeypatch.setattr(operation, '_words', lambda area: observations[area])
    choose = Mock(return_value=Mock(execute=Mock(return_value=OperationResult(True))))
    monkeypatch.setattr(scratch_card, 'GamepadChooseDialogOption', choose)

    operation._advance_wake_dialogue()
    operation._advance_wake_dialogue()
    ctx.controller.btn_tap.assert_called_once_with('south')
    observations['手柄-嗷呜对话选项'] = ['叫醒他!', '还是别了…']
    operation._advance_wake_dialogue()
    operation._advance_wake_dialogue()
    choose.assert_called_once_with(ctx, '叫醒他!', single_confirmation=True)

    observations['手柄-嗷呜对话正文'] = []
    observations['手柄-嗷呜醒来文案'] = ['嗷鸣被你叫醒了.….']
    operation._advance_wake_dialogue()
    operation._advance_wake_dialogue()
    assert ctx.controller.btn_tap.call_args_list == [call('south'), call('south')]
