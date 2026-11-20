"""Mac 邮件安全分支测试；不连接游戏或保存私人邮件截图。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.application.email_app import email_app
from zzz_od.application.zzz_application import ZApplication
from zzz_od.macos import cli
from zzz_od.operation.gamepad.mailbox import GamepadClaimMailbox


@pytest.fixture
def op(monkeypatch: pytest.MonkeyPatch) -> GamepadClaimMailbox:
    operation = GamepadClaimMailbox(
        SimpleNamespace(controller=Mock(), run_context=Mock(), current_instance_idx=2),
    )
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, '_mailbox_visible', Mock(return_value=True))
    monkeypatch.setattr(operation, '_known_reward_visible', Mock(return_value=False))
    monkeypatch.setattr(operation, '_save_evidence', Mock(return_value='mock.png'))
    return operation


def text_at(x: int, y: int, w: int, h: int) -> MatchResultList:
    matches = MatchResultList()
    matches.append(MatchResult(1, x, y, w, h))
    return matches


@pytest.mark.parametrize(('hotkey', 'color', 'expected'), [
    ('x', (255, 250, 0), (True, True)),
    ('X', (100, 100, 100), (True, False)),
    ('A', (255, 250, 0), (False, False)),
])
def test_prompt_needs_exact_x_and_enabled_label(
    op: GamepadClaimMailbox,
    monkeypatch: pytest.MonkeyPatch,
    hotkey: str,
    color: tuple[int, int, int],
    expected: tuple[bool, bool],
) -> None:
    image = np.zeros((70, 250, 3), dtype=np.uint8)
    image[20:50, 93:200] = color
    monkeypatch.setattr(op, '_read_area', Mock(return_value=(
        image, {hotkey: text_at(19, 18, 31, 33), '全部领取': text_at(93, 20, 107, 30)},
    )))
    assert op._claim_prompt() == expected


def test_claim_unknown_or_disabled_never_sends_input(
    op: GamepadClaimMailbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(op, '_claim_prompt', Mock(side_effect=[(False, False), (True, False)]))
    assert not op.claim_mail().is_success
    assert op.claim_mail().is_success
    assert op.confirm_mail().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_mail_x_then_only_one_verified_popup_confirmation(
    op: GamepadClaimMailbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(op, '_claim_prompt', Mock(return_value=(True, True)))
    assert op.claim_mail().is_success
    assert op.claim_mail().is_success
    assert not op.confirm_mail().is_success
    op._known_reward_visible.return_value = True
    assert not op.confirm_mail().is_success
    assert not op.confirm_mail().is_success
    op._known_reward_visible.return_value = False
    assert op.confirm_mail().is_success
    assert op.ctx.controller.btn_tap.call_args_list == [call('west'), call('south')]


def test_existing_or_unknown_popup_never_prompts_repeated_claim(
    op: GamepadClaimMailbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    op._known_reward_visible.return_value = True
    assert not op.claim_mail().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    op._claim_sent = True
    op._known_reward_visible.return_value = False
    op.node_retry_times = 7
    monkeypatch.setattr(op, '_pending_evidence', Mock(side_effect=lambda _, reason: op.round_fail(reason)))
    assert op.confirm_mail().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_evidence_failure_blocks_x(op: GamepadClaimMailbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(op, '_claim_prompt', Mock(return_value=(True, True)))
    op._save_evidence.return_value = ''
    assert op.claim_mail().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('args', [
    ['--app', 'email'], ['--claim-all'], ['--app', 'email', '--claim-all', '--dry-run'],
    ['--app', 'email', '--claim-all', '--list'],
])
def test_cli_rejects_claim_without_exact_manual_opt_in(args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


def test_mac_guard_blocks_gui_and_leaves_original_platform_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = email_app.EmailApp.__new__(email_app.EmailApp)
    op.ctx = SimpleNamespace()
    op.op_fail = Mock(return_value='blocked')
    run = Mock(return_value='original')
    monkeypatch.setattr(ZApplication, 'execute', run)
    monkeypatch.setattr(email_app, 'sys', SimpleNamespace(platform='darwin'))
    assert op.execute() == 'blocked'
    run.assert_not_called()
    op.ctx.macos_claim_all_mail = True
    assert op.execute() == 'original'
    monkeypatch.setattr(email_app, 'sys', SimpleNamespace(platform='win32'))
    del op.ctx.macos_claim_all_mail
    assert op.execute() == 'original'


def test_mailbox_operation_has_single_safe_route(op: GamepadClaimMailbox) -> None:
    start, _nodes, edges = op._analyse_node_annotations()
    assert start.cn == '打开邮件'
    assert {(edge.node_from.cn, edge.node_to.cn) for edge in edges} == {
        ('打开邮件', '核对并领取邮件'),
        ('核对并领取邮件', '确认邮件领取结果'),
        ('确认邮件领取结果', '邮件返回大世界'),
    }
