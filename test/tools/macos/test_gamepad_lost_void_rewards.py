"""悬赏领取保留8000保护，必须核对四档已领取。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.operation.gamepad.lost_void_rewards import GamepadLostVoidClaimBounty


def matches(count: int) -> MatchResultList:
    result=MatchResultList(only_best=False)
    for index in range(count):
        result.append(MatchResult(1,10,10+index*90,100,30))
    return result


def operation(score: int, done: int, incomplete: int) -> GamepadLostVoidClaimBounty:
    op=GamepadLostVoidClaimBounty(SimpleNamespace(controller=Mock()))
    op.last_screenshot=np.zeros((1080,1920,3),dtype=np.uint8)
    image=np.zeros((100,300,3),dtype=np.uint8)
    fields={
        '手柄-悬赏面板标题':{'悬赏委托':matches(1)},
        '手柄-悬赏实际进度':{f'{score}/8000':matches(1)},
        '手柄-悬赏奖励状态':{'已领取':matches(done),'未完成':matches(incomplete)},
        '手柄-悬赏底栏':{'X':matches(1),'全部领取':matches(1)},
    }
    op._read_area=lambda screen,name:(image,fields[name])
    op._known_reward_visible=Mock(return_value=False)
    op._after_round_wait=Mock()
    op._save_evidence=Mock(return_value='mock-evidence')
    return op


@pytest.mark.parametrize('score',[0,7999])
def test_incomplete_bounty_never_sends_claim(score: int) -> None:
    op=operation(score,0,4)
    assert op.claim().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_full_progress_requires_four_claimed_rows() -> None:
    op=operation(8000,0,0)
    assert not op.claim().is_success
    assert not op.claim().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('west')
    op._read_area=lambda screen,name:(np.zeros((100,300,3),dtype=np.uint8),{
        '手柄-悬赏面板标题':{'悬赏委托':matches(1)},
        '手柄-悬赏实际进度':{'8000/8000':matches(1)},
        '手柄-悬赏奖励状态':{'已领取':matches(4)},
        '手柄-悬赏底栏':{'X':matches(1),'全部领取':matches(1)},
    }[name])
    result=op.claim()
    assert result.is_success and result.data['claimed_tiers']==4
    op.ctx.controller.btn_tap.assert_called_once_with('west')


def test_already_claimed_bounty_sends_no_input() -> None:
    op=operation(8000,4,0)
    assert op.claim().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_lowercase_x_from_real_footer_still_claims_only_once() -> None:
    op=operation(8000,0,0)
    read=op._read_area
    op._read_area=lambda screen,name:(np.zeros((100,300,3),dtype=np.uint8),
        {'x':matches(1),'全部领取':matches(1)} if name=='手柄-悬赏底栏' else read(screen,name)[1])
    assert not op.claim().is_success
    assert not op.claim().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('west')
