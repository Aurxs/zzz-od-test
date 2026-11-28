"""式舆手柄的选关、配队、结算与原应用分派。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import cv2
import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.shiyu_defense.shiyu_defense_app import ShiyuDefenseApp
from zzz_od.operation.gamepad import shiyu_defense_battle, shiyu_rewards
from zzz_od.operation.gamepad.shiyu_defense import (
    GAMEPAD_SCREEN,
    GamepadShiyuDeploy,
    _result_exit_button,
    find_focused_team,
    focused_critical_node,
    read_critical_progress,
    read_team_order,
)


def _words(*items: tuple[str, int, int]) -> dict[str, MatchResultList]:
    result: dict[str, MatchResultList] = {}
    for text, x, y in items:
        matches = result.setdefault(text, MatchResultList(only_best=False))
        matches.append(MatchResult(1, x, y, 20, 16))
    return result


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('3/5', (3, 5)), ('剧变节点5／5', (5, 5)), ('315', None), ('3/2', None), ('5', None)],
)
def test_progress_needs_an_unambiguous_ratio(text: str, expected: tuple[int, int] | None) -> None:
    assert read_critical_progress(_words(('剧变节点', 0, 12), (text, 15, 42))) == expected
    assert read_critical_progress(_words(('稳定节点', 0, 12), (text, 15, 42))) == (
        expected if text.startswith('剧变节点') else None
    )


def test_current_node_requires_one_complete_yellow_ring() -> None:
    image = np.zeros((400, 620, 3), dtype=np.uint8)
    cards = [Rect(10, 10, 205, 205), Rect(220, 191, 415, 387), Rect(425, 10, 618, 205)]
    cv2.circle(image, (318, 291), 87, (235, 213, 52), 5)
    assert focused_critical_node(image, cards) == 2
    cv2.circle(image, (525, 101), 87, (235, 213, 52), 5)
    assert focused_critical_node(image, cards) is None


def test_gamepad_fourth_node_ring_on_archived_frame() -> None:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    repo = Path(__file__).resolve().parents[3]
    frame = repo / 'screens' / '式舆防卫战' / 'ios_critical_04_focused.webp'
    image = cv2_utils.read_image(str(frame))
    cards = [loader.get_area(GAMEPAD_SCREEN, f'手柄-防线{idx}').rect for idx in range(1, 6)]
    assert focused_critical_node(image, cards) == 4


def test_team_badge_belongs_to_the_selected_card() -> None:
    words = _words(('TEAM', 662, 92), ('01', 660, 126), ('TEAM', 1430, 92), ('02', 1428, 126))
    assert read_team_order(words, Rect(0, 0, 743, 216)) == 1
    assert read_team_order(words, Rect(770, 0, 1536, 216)) == 2
    assert read_team_order(_words(('TEAM', 662, 185), ('01', 660, 125)), Rect(0, 0, 743, 216)) is None


def test_multi_team_focus_requires_one_card_with_active_hint() -> None:
    image = np.zeros((400, 1810, 3), dtype=np.uint8)
    cv2.rectangle(image, (45, 42), (843, 301), (235, 213, 52), 7)
    cv2.rectangle(image, (935, 42), (1743, 301), (235, 213, 52), 7)
    assert find_focused_team(image, {}) is None
    focus = find_focused_team(image, _words(('RS', 1105, 73), ('Y', 1719, 72)))
    assert focus is not None and focus.center.x > 935
    assert find_focused_team(image, _words(('RS', 215, 73), ('Y', 1719, 72))) is None


def test_start_requires_six_agents_on_two_team_page() -> None:
    op = object.__new__(GamepadShiyuDeploy)
    op.ctx = SimpleNamespace(controller=Mock())
    op.last_screenshot = None
    op._sent = False
    op._single_room = False
    current = {'手柄-出战准备详情'}
    op._found = lambda name: name in current
    op._read = lambda _name: (None, _words(('出战', 1750, 1030)))
    op._after_round_wait = Mock()
    op.deploy()
    op.ctx.controller.btn_tap.assert_not_called()
    current.add('手柄-满员计数')
    op.deploy()
    op.ctx.controller.btn_tap.assert_called_once_with('start')


def test_result_reads_enemy_goal_and_exit_hint() -> None:
    text = _words(('剩余时间大于180秒', 95, 70), ('消灭所有敌人', 94, 124), ('1/1', 511, 70))
    assert shiyu_defense_battle.read_enemy_goal(text) is None
    assert shiyu_defense_battle.read_enemy_goal(
        _words(('1/1', 511, 70), ('消灭所有敌人', 94, 124), ('0/1', 511, 125))
    ) is False
    assert shiyu_defense_battle.read_enemy_goal(_words(('消灭所有敌人1/1', 190, 124))) is True
    assert _result_exit_button(_words(('A', 101, 87), ('下一防线', 139, 88), ('退出', 318, 87))) is None
    assert _result_exit_button(_words(('A下一防线', 140, 88), ('B', 280, 88), ('退出', 318, 87))) == 'east'
    assert _result_exit_button(_words(('B', 98, 43), ('退出', 220, 40))) == 'east'


def test_original_app_dispatches_both_battle_teams_before_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = object.__new__(ShiyuDefenseApp)
    app.ctx = SimpleNamespace()
    app._mac_teams = [6, 12]
    app.phase_idx = 0
    app.run_record = Mock()
    app._after_round_wait = Mock()
    original = shiyu_defense_battle.GamepadShiyuBattle
    played: list[tuple[int, int | None]] = []

    def create_battle(_ctx: object, team: int, next_team: int | None) -> SimpleNamespace:
        played.append((team, next_team))
        status = original.STATUS_NEXT_TEAM if next_team is not None else original.STATUS_VICTORY
        return SimpleNamespace(execute=lambda: OperationResult(True, status))

    function = Mock(side_effect=create_battle)
    function.STATUS_NEXT_TEAM = original.STATUS_NEXT_TEAM
    function.STATUS_VICTORY = original.STATUS_VICTORY
    monkeypatch.setattr(shiyu_defense_battle, 'GamepadShiyuBattle', function)
    assert not app.mac_battle().is_success
    assert app.mac_battle().is_success
    assert played == [(6, 12), (12, None)]
    app.run_record.add_node_finished.assert_not_called()


def test_explicit_layer_resume_keeps_the_first_half_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    op = object.__new__(shiyu_defense_battle.GamepadShiyuBattle)
    op.ctx = SimpleNamespace(controller=Mock(), auto_battle_context=Mock())
    op.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    op._resume_between = True
    op._scope = False
    op.original = SimpleNamespace(team_config=SimpleNamespace(idx=2), check_shiyu_countdown=Mock(return_value=False))
    op._is_next_team = Mock(return_value=False)
    op._team_matches = Mock(return_value=True)
    op._layer_target = Mock(return_value=(550, 19.2))
    op._has_layer_interact = Mock(return_value=False)
    op._after_round_wait = Mock()
    monkeypatch.setattr(shiyu_defense_battle, 'is_native_battle', Mock(return_value=True))
    assert op.wait_for_battle().status == op.STATUS_RESUME_BETWEEN
    op.ctx.auto_battle_context.start_auto_battle.assert_not_called()


def test_layer_moves_toward_bounded_actual_offset() -> None:
    op = object.__new__(shiyu_defense_battle.GamepadShiyuBattle)
    op.ctx = SimpleNamespace(controller=Mock(), project_config=SimpleNamespace(screen_standard_width=1920))
    op.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    op.original = SimpleNamespace(check_shiyu_countdown=Mock(return_value=False))
    op._between_moves = 0
    op._interact_sent = False
    op._read_transition = Mock(return_value=None)
    op._refresh_scope = Mock(return_value=True)
    op._has_layer_interact = Mock(return_value=False)
    op._layer_target = Mock(return_value=(550, 19.2))
    op._after_round_wait = Mock()
    op.move_between()
    op.ctx.controller.turn_by_distance.assert_called_once_with(-230)
    op.ctx.controller.move_w.assert_not_called()


def test_confirmed_portal_sends_one_interaction_after_battle_scope_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    op = object.__new__(shiyu_defense_battle.GamepadShiyuBattle)
    op.ctx = SimpleNamespace(controller=Mock())
    op.original = SimpleNamespace(team_config=SimpleNamespace(idx=2))
    op.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    op._scope = True
    op._interact_sent = False
    op._read_transition = Mock(return_value=None)
    op._has_layer_interact = Mock(return_value=True)
    op._stop_strategy = Mock()
    op._wait_for_known_screen = Mock()
    monkeypatch.setattr(shiyu_defense_battle, 'is_native_battle', Mock(return_value=False))
    op.move_between()
    op.move_between()
    assert op.ctx.controller.mock_calls == [
        call.end_battle_input_scope(),
        call.resume_input(),
        call.interact(press=True, press_time=0.2, release=True),
    ]


def test_confirmed_portal_matches_native_interact_and_left_a_on_archived_frame() -> None:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    tm = TemplateMatcher(TemplateLoader())
    repo = Path(__file__).resolve().parents[3]
    image = cv2_utils.read_image(str(repo / 'screens' / '式舆防卫战' / 'ios_layer_portal_ready.webp'))
    for screen, name in (('战斗画面', '按键-交互'), (GAMEPAD_SCREEN, '手柄-层间交互键')):
        area = loader.get_area(screen, name)
        result = tm.crop_and_match_template(
            image, area.rect, area.template_sub_dir, area.template_id, threshold=area.template_match_threshold,
        )
        assert result.max is not None


@pytest.mark.parametrize('badge', (False, True))
def test_entry_reward_uses_existing_claim_only_with_visible_badge(
    monkeypatch: pytest.MonkeyPatch, badge: bool,
) -> None:
    checked: list[str] = []
    app = object.__new__(ShiyuDefenseApp)
    app.ctx = SimpleNamespace()
    app.last_screenshot = np.zeros((10, 10, 3), dtype=np.uint8)
    app._after_round_wait = Mock()
    child = Mock(execute=Mock(return_value=OperationResult(True, '领取完成')))
    monkeypatch.setattr(shiyu_rewards, 'GamepadClaimShiyuRewards', Mock(return_value=child))

    def find_area(_image: object, _screen: str, label: str) -> SimpleNamespace:
        checked.append(label)
        return SimpleNamespace(is_success=label != '手柄-可领奖红标' or badge)

    app.round_by_find_area = find_area
    assert app.mac_claim_entry_reward().is_success
    assert checked == ['手柄-前哨档案', '手柄-选关选择', '手柄-可领奖红标']
    assert child.execute.call_count == int(badge)
