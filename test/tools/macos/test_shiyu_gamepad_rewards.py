"""验证剧变奖励只能在已确认的可领取状态提交一次。"""

from unittest.mock import Mock

from zzz_od.operation.gamepad.shiyu_rewards import GamepadClaimShiyuRewards


def test_claim_once_and_verify_receipt_before_return() -> None:
    op = GamepadClaimShiyuRewards(Mock())
    op._after_round_wait = Mock()
    op._save_evidence = Mock(return_value='saved')
    op._has_text = Mock(side_effect=lambda _, area, __: area in ('奖励标题', '防线列表'))
    op._yellow_text = Mock(return_value=True)
    op._known_reward_visible = Mock(return_value=False)
    op._node_list = Mock(return_value=False)
    op.claim()
    op.claim()
    op.ctx.controller.btn_tap.assert_called_once_with('west')
    op._yellow_text.return_value = False
    op.claim()
    op.ctx.controller.btn_tap.assert_called_once_with('west')
    op._known_reward_visible.return_value = True
    op.claim()
    op.claim()
    op._known_reward_visible.return_value = False
    op.claim()
    op._has_text.return_value = False
    op._has_text.side_effect = None
    op._node_list.return_value = True
    assert op.claim().is_success
    assert [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list] == ['west', 'south', 'east']
