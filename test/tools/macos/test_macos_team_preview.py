"""只覆盖扫描不落盘、确认保护和未识别字段保留。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.config.team_config import PredefinedTeamInfo
from zzz_od.macos.predefined_team_preview import (
    MacPredefinedTeamPreview,
    MacTeamRecognition,
    team_signature,
)


def context() -> SimpleNamespace:
    teams = [PredefinedTeamInfo(0, '原队名', '原策略', ['a', 'b', 'c']), PredefinedTeamInfo(1, '第二队', '保留策略', ['d', 'e', 'f'])]
    config = SimpleNamespace(team_list=teams, get=Mock(return_value=[
        {'name': team.name, 'auto_battle': team.auto_battle, 'agent_id_list': list(team.agent_id_list), 'custom': True} for team in teams
    ]), update=Mock())
    return SimpleNamespace(team_config=config, current_instance_idx=2, run_context=SimpleNamespace(is_context_stop=True))


def preview(ctx: SimpleNamespace) -> MacPredefinedTeamPreview:
    return MacPredefinedTeamPreview(2, team_signature(ctx.team_config.team_list), (
        MacTeamRecognition(0, None, ('x', 'y', 'z')), MacTeamRecognition(1, '游戏队名', ('unread',)),
    ), ())


def test_preview_does_not_write_and_confirm_preserves_missing_fields_and_strategy() -> None:
    ctx = context()
    before = deepcopy(ctx.team_config.get.return_value)
    result = preview(ctx)
    ctx.team_config.update.assert_not_called()
    assert result.apply(ctx) == 2
    assert ctx.team_config.update.call_count == 1
    output = ctx.team_config.update.call_args.args[1]
    assert output[0] == {**before[0], 'agent_id_list': ['x', 'y', 'z']}
    assert output[1] == {**before[1], 'name': '游戏队名'}
    assert ctx.team_config.get.return_value == before


@pytest.mark.parametrize('changed', ['account', 'strategy', 'running'])
def test_stale_or_running_preview_is_rejected(changed: str) -> None:
    ctx = context()
    result = preview(ctx)
    if changed == 'account':
        ctx.current_instance_idx = 3
    elif changed == 'strategy':
        ctx.team_config.team_list[0].auto_battle = '用户新策略'
    else:
        ctx.run_context.is_context_stop = False
    with pytest.raises(ValueError):
        result.apply(ctx)
    ctx.team_config.update.assert_not_called()


def test_cancel_in_original_page_does_not_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.gui.view.one_dragon import predefined_team_interface as ui

    ctx = context()
    ctx.macos_predefined_team_preview = preview(ctx)
    page = SimpleNamespace(ctx=ctx, window=Mock())
    monkeypatch.setattr(ui, 'TeamRecognitionPreviewDialog', Mock(return_value=SimpleNamespace(exec=lambda: False)))
    ui.PredefinedTeamInterface._on_preview_clicked(page)
    ctx.team_config.update.assert_not_called()
    assert ctx.macos_predefined_team_preview is not None


def test_bad_scroll_overlap_never_guesses_team_indices_or_sends_another_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from one_dragon.base.geometry.rectangle import Rect
    from zzz_od.operation.gamepad import predefined_team_scan as scan

    ctx = context()
    ctx.controller = Mock()
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
