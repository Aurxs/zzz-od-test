"""验证 Mac 输入保护与生产连携头像识别接口兼容。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.controller.macos_battle_input_guard import MacBattleHudGuard


@pytest.mark.parametrize('matched_area', [0, 1, None])
def test_chain_hud_uses_production_matcher(matched_area: int | None) -> None:
    """普攻不可用时，两侧真实识别入口均可放行连携，未命中仍拒绝。"""
    battle = AutoBattleContext.__new__(AutoBattleContext)
    agent = SimpleNamespace()
    battle.ctx = SimpleNamespace(tm=SimpleNamespace(match_template=Mock(
        side_effect=[SimpleNamespace(max=agent if matched_area == i else None)
                     for i in range(2)],
    )))
    battle.is_normal_attack_btn_available = Mock(return_value=False)
    battle.agent_context = SimpleNamespace(
        get_possible_agent_list=lambda: [(agent, 'test_agent')],
    )
    battle.area_chain_1 = SimpleNamespace(rect=Rect(20, 30, 60, 70))
    battle.area_chain_2 = SimpleNamespace(rect=Rect(80, 90, 120, 130))

    allowed = MacBattleHudGuard(battle)(np.zeros((1080, 1920, 3), dtype=np.uint8))

    assert allowed is (matched_area is not None)
