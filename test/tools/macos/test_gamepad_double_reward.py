"""双倍次数与临时卡数组合的最小验证，不访问设备。"""

import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.double_reward import make_double_reward_plan, read_double_reward_count


def matches(x: int, y: int, width: int) -> MatchResultList:
    result = MatchResultList()
    result.append(MatchResult(1, x, y, width, 30))
    return result


def test_double_counter_must_belong_to_label_row() -> None:
    words = {'每日怪物卡双倍掉落次数': matches(700, 300, 300), '3/5': matches(1020, 300, 50), '5/5': matches(1020, 700, 50)}
    assert read_double_reward_count(words) == 3
    del words['3/5']
    with pytest.raises(ValueError):
        read_double_reward_count(words)
    assert read_double_reward_count({'基础材料': matches(700, 300, 100)}) == 0


@pytest.mark.parametrize(('remaining', 'charge', 'cards'), [(5, 100, '5'), (3, 45, '2'), (0, 100, None), (5, 19, None)])
def test_temp_plan_never_mutates_source(remaining: int, charge: int, cards: str | None) -> None:
    source = ChargePlanItem(mission_name='音擎专项', predefined_team_idx=6, plan_times=8, run_times=4)
    before = source.to_dict()
    result = make_double_reward_plan(source, remaining, charge)
    assert source.to_dict() == before
    if cards is None:
        assert result is None
    else:
        assert result.card_num == cards
        assert (result.run_times, result.plan_times, result.predefined_team_idx) == (0, 1, 6)
        assert result.plan_id != source.plan_id
