"""验证 Mac 扫描沿用 Windows 更新语义及原导航保护。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.base.geometry.rectangle import Rect
from zzz_od.config.team_config import TeamConfig
from zzz_od.game_data.agent import AgentEnum
from zzz_od.operation.gamepad import predefined_team_scan as scan
from zzz_od.operation.predefined_team_recognizer import PredefinedTeamRecognition


def context() -> SimpleNamespace:
    config = object.__new__(TeamConfig)
    YamlOperator.__init__(config)
    config.data = {'team_list': [{'name': '原别名', 'auto_battle': '保留策略', 'agent_id_list': ['a', 'b', 'c']}]}
    config.update = Mock(wraps=config.update)
    return SimpleNamespace(team_config=config, current_instance_idx=2, run_context=Mock(), controller=Mock())


@pytest.mark.parametrize('count,name', [(0, '游戏队名'), (1, '游戏队名'), (2, '游戏队名'), (3, '游戏队名'), (3, None)])
def test_automatic_sync_uses_original_windows_update_rules(count: int, name: str | None) -> None:
    ctx = context()
    op = scan.GamepadScanPredefinedTeams(ctx)
    agents = [item.value for item in list(AgentEnum)[:count]]
    recognition = PredefinedTeamRecognition(name, [SimpleNamespace(data=agent) for agent in agents])
    op._sync_recognition(0, recognition)
    actual = ctx.team_config.get_team_by_idx(0)
    assert actual.auto_battle == '保留策略'
    if count:
        assert actual.name == (name or '原别名')
        assert actual.agent_id_list == [agent.agent_id for agent in agents] + ['unknown'] * (3 - count)
        ctx.team_config.update.assert_called_once()
        assert op.updated_indices == {0}
    else:
        assert actual.name == '原别名' and actual.agent_id_list == ['a', 'b', 'c']
        ctx.team_config.update.assert_not_called()
        assert not op.updated_indices


def test_bad_scroll_overlap_never_guesses_team_indices_or_sends_another_key(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    ctx.ocr = Mock()
    ctx.ocr.run_ocr.return_value = {'BANGBOO': [], '选择': [], '返回': []}
    ctx.screen_loader = Mock()
    ctx.screen_loader.get_area.return_value = SimpleNamespace(rect=Rect(0, 0, 800, 280), center=SimpleNamespace(x=400, y=140))
    op = scan.GamepadScanPredefinedTeams(ctx)
    op._after_round_wait = Mock()
    op.last_screenshot = Mock()
    op._previous_state = (4, tuple(f'旧队{i}' for i in range(6)))
    monkeypatch.setattr(scan, 'find_yellow_focus_frames', Mock(return_value=[SimpleNamespace(center=SimpleNamespace(x=400, y=140))]))
    monkeypatch.setattr(scan, 'find_team_name', Mock(return_value='不同队'))
    for _ in range(4):
        result = op.scan()
    assert result.is_fail and op._page_start == 0
    ctx.controller.btn_tap.assert_not_called()
    ctx.team_config.update.assert_not_called()


def test_account_change_stops_before_any_further_update() -> None:
    ctx = context()
    op = scan.GamepadScanPredefinedTeams(ctx)
    op._after_round_wait = Mock()
    ctx.current_instance_idx = 3
    assert op.scan().is_fail
    ctx.team_config.update.assert_not_called()
    ctx.controller.btn_tap.assert_not_called()
