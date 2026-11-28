"""验证走格在镜头重排后按棋盘相对位置核对。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.hollow_zero.game_data.hollow_zero_event import HollowZeroEntry
from zzz_od.hollow_zero.hollow_map.hollow_zero_map import (
    HollowZeroMap,
    HollowZeroMapNode,
)
from zzz_od.operation.gamepad import hollow_eval_battle, hollow_eval_board
from zzz_od.operation.gamepad.hollow_eval_board import (
    GamepadHollowEvalStep,
    _board_cells,
    board_moved_one_tile,
)
from zzz_od.operation.gamepad.hollow_eval_door import GamepadHollowEvalDoor
from zzz_od.operation.gamepad.hollow_eval_event import GamepadHollowEvalEvent
from zzz_od.operation.gamepad.hollow_eval_exit import GamepadHollowEvalSuspend
from zzz_od.operation.gamepad.hollow_eval_path import route_around_loop


def _board(positions: tuple[int, ...], current: int) -> HollowZeroMap:
    nodes = [
        HollowZeroMapNode(
            Rect(x - 25, 375, x + 25, 425),
            HollowZeroEntry(f'{index:04d}-{name}'),
            confidence=0.95,
        )
        for index, (name, x) in enumerate(zip(('当前', '齿轮硬币箱', '侵蚀', '休息区'), positions, strict=True))
    ]
    edges = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2]}
    return HollowZeroMap(nodes, current, edges)


def test_board_shift_uses_two_anchors_instead_of_screen_coordinates() -> None:
    before = _board((440, 590, 740, 890), 0)
    after = _board((150, 330, 510, 690), 1)
    assert board_moved_one_tile(_board_cells(before), _board_cells(after), (1, 0))
    assert not board_moved_one_tile(_board_cells(before), _board_cells(after), (-1, 0))
    assert not board_moved_one_tile({(3, 0): '休息区'}, {(2, 0): '休息区'}, (1, 0))


def test_two_rows_can_match_even_with_repeated_categories_and_lost_column() -> None:
    names = ('齿轮硬币箱', '呼叫增援', '齿轮硬币箱', '邦布商人')
    before = {(x, y): name for y in (0, 1) for x, name in enumerate(names, 1)}
    after = {(x - 1, y): name for (x, y), name in before.items() if x > 1}
    assert board_moved_one_tile(before, after, (1, 0))
    assert not board_moved_one_tile(before, after, (0, 1))


def test_narrow_board_needs_an_independent_reward_for_one_remaining_landmark() -> None:
    before = {(1, 0): '齿轮硬币箱', (2, 0): '邦布商人'}
    after = {(1, 0): '邦布商人'}
    assert not board_moved_one_tile(before, after, (1, 0))
    assert board_moved_one_tile(before, after, (1, 0), reward_confirmed=True)
    assert not board_moved_one_tile(before, after, (0, -1), reward_confirmed=True)


@pytest.mark.parametrize(('floor', 'pressure', 'resonium', 'confirmed'), [
    (2, 60, 10, True),
    (2, 60, 9, False),
    (2, 50, 10, False),
    (3, 60, 10, False),
])
def test_narrow_capsule_lane_needs_both_board_rewards_and_the_same_floor(
    floor: int, pressure: int, resonium: int, confirmed: bool,
) -> None:
    op = GamepadHollowEvalStep(SimpleNamespace())
    op.moved_node = SimpleNamespace(entry=HollowZeroEntry('0026-扭蛋机'))
    op.direction = (1, 0)
    op.before = {(1, 0): '扭蛋机', (2, 0): '危机'}
    op._before_floor, op.floor = 2, floor
    op._before_reward, op._before_resonium_count = (50, 5205), 9
    op._reward_hud = Mock(return_value=(pressure, 5205))
    op._board_number = Mock(return_value=resonium)
    assert op._narrow_reward_receipt({(1, 0): '危机'}) is confirmed
    assert not op._narrow_reward_receipt({(2, 0): '危机'})


def test_cycle_replanning_preserves_directed_rails_to_a_reachable_goal() -> None:
    positions = [(300, 400), (150, 400), (300, 260), (450, 260)]
    names = ['当前', '空白已通行', '轨道-右', '业绩考察点']
    nodes = [
        HollowZeroMapNode(Rect(x - 25, y - 25, x + 25, y + 25), HollowZeroEntry(f'{i:04d}-{name}'))
        for i, ((x, y), name) in enumerate(zip(positions, names, strict=True))
    ]
    board = HollowZeroMap(nodes, 0, {0: [1, 2], 1: [0], 2: [3]})
    assert route_around_loop(board, [nodes[3]], {(-1, 0)}, set()) == (nodes[2], (0, -1), nodes[3])
    assert route_around_loop(board, [nodes[3]], {(-1, 0), (0, -1)}, set()) is None
    board.edges = {0: [1, 2], 1: [0], 3: [2]}
    assert route_around_loop(board, [nodes[3]], {(-1, 0)}, set()) is None


def test_white_tile_animation_never_drives_movement_and_requires_stable_layout() -> None:
    first = _board((440, 590, 740, 890), 0)
    target = first.nodes[2]
    target.path_first_node = first.nodes[1]
    selector = Mock(return_value=target)
    op = GamepadHollowEvalStep(SimpleNamespace(
        controller=Mock(), withered_domain=SimpleNamespace(get_next_to_move=selector, level_info=SimpleNamespace(phase=1)),
    ))
    op._after_round_wait = Mock()
    op.active_board = Mock(return_value=first)
    op._reward_hud = Mock(return_value=None)
    op.save_screenshot = Mock(return_value='私有棋盘图')
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    white = first.nodes[1].pos
    frame[white.y1:white.y2, white.x1:white.x2] = 255
    op.last_screenshot = frame
    for _ in range(2):
        assert op.move().status == '等待棋盘展开和稳定'
    op.save_screenshot.assert_called_once_with(prefix='macos_hollow_eval_board_expanding')
    frame[:] = 0
    assert op.move().status == '等待棋盘展开和稳定'
    selector.assert_not_called()
    op.ctx.controller.btn_tap.assert_not_called()
    assert op.move().status == '等待走格后的新画面'
    selector.assert_called_once_with(first)
    op.ctx.controller.btn_tap.assert_called_once_with('dpad_right')


def test_step_does_not_repeat_until_actual_movement() -> None:
    before = _board((440, 590, 740, 890), 0)
    after = _board((150, 330, 510, 690), 1)
    before.nodes[2].path_first_node = before.nodes[1]
    context = SimpleNamespace(
        get_next_to_move=Mock(return_value=before.nodes[2]), update_context_after_move=Mock(),
        level_info=SimpleNamespace(phase=1),
    )
    op = GamepadHollowEvalStep(SimpleNamespace(controller=Mock(), withered_domain=context), reuse_run=True)
    op._after_round_wait = Mock()
    op.active_board = Mock(side_effect=[before, before, after])
    op.save_screenshot = Mock(return_value='新棋盘')
    for time in (101, 102):
        op.last_screenshot_time = time
        assert not op.move().is_success
        context.update_context_after_move.assert_not_called()
    op.last_screenshot_time = 103
    assert op.move().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('dpad_right')
    context.update_context_after_move.assert_called_once_with(before, before.nodes[1], update_current=False)


def test_pending_event_entry_requires_same_node_and_a_new_frame() -> None:
    before = _board((440, 590, 740, 890), 0)
    before.nodes[1].entry = HollowZeroEntry('0042-邦布商人')
    updater = Mock()
    op = GamepadHollowEvalStep(SimpleNamespace(withered_domain=SimpleNamespace(update_context_after_move=updater)))
    op.before_board = before
    op.moved_node = before.nodes[1]
    op.direction = (1, 0)
    op._last_frame_time = op.last_screenshot_time = 10
    assert not op.confirm_event_entry('邦布商人')
    op.last_screenshot_time = 11
    assert not op.confirm_event_entry('呼叫增援')
    updater.assert_not_called()
    assert op.confirm_event_entry('邦布商人')
    updater.assert_called_once_with(before, before.nodes[1], update_current=False)


def _word(x: int, y: int) -> MatchResultList:
    result = MatchResultList()
    result.append(MatchResult(1, x, y, 15, 20))
    return result


def test_s_door_requires_its_own_prompt_and_confirms_once() -> None:
    op = GamepadHollowEvalDoor(SimpleNamespace(controller=Mock(), tm=Mock()))
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='开门图')
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    panel = np.zeros((110, 690, 3), dtype=np.uint8)
    panel[:, 139:] = (230, 220, 0)
    words = {'开门': _word(171, 31), '上一场『守门人』战斗获得S评价可通过': _word(173, 61)}
    op.navigation._read_area = Mock(return_value=(panel, words))
    op.ctx.tm.match_template.return_value.max = None
    assert not op.open().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    op.ctx.tm.match_template.return_value.max = object()
    assert op.open().is_success
    assert not op.open().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('south')


def test_s_door_preempts_pending_battle_without_counting_a_move(monkeypatch: pytest.MonkeyPatch) -> None:
    op = hollow_eval_board.GamepadHollowEvalExplore(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op.door.try_open = Mock(return_value=op.round_success('已请求开门'))
    battle = Mock(return_value=True)
    monkeypatch.setattr(hollow_eval_board, 'is_native_battle', battle)
    op.step.direction = (1, 0)
    op._combat_wait_until = 100.0
    assert op.explore().status == '已请求开门'
    battle.assert_not_called()
    assert op.step.direction is None and op._combat_wait_until is None and op.completed == 0


def test_loan_selection_moves_to_refusal_and_requires_its_focus() -> None:
    refuse = SimpleNamespace(option_name='不需要借款', ocr_word='不需要借款')
    loan = SimpleNamespace(option_name='借888齿轮硬币', ocr_word='借888齿轮硬币')
    data = SimpleNamespace(get_normal_event_by_name=Mock(return_value=SimpleNamespace(options=(loan, refuse))))
    op = GamepadHollowEvalEvent(SimpleNamespace(controller=Mock(), withered_domain=SimpleNamespace(data_service=data)))
    op._after_round_wait = Mock()
    image = np.zeros((740, 820, 3), dtype=np.uint8)
    op.last_screenshot_time = 30
    op._choose_right_option(
        '投机客', image, {'A': _word(190, 320), '借888齿轮硬币': _word(350, 330), '不需要借款': _word(350, 630)},
        [Rect(230, 290, 820, 370)],
    )
    op.last_screenshot_time = 31
    op._choose_right_option(
        '投机客', image, {'A': _word(190, 630), '借888齿轮硬币': _word(350, 330), '不需要借款': _word(350, 630)},
        [Rect(230, 600, 820, 680)],
    )
    assert [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list] == ['dpad_down', 'south']


def test_existing_suspend_dialog_requires_this_operation_to_request_it() -> None:
    op = GamepadHollowEvalSuspend(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    modal = {'是否确认暂停空洞探索，返回街区？': _word(100, 20)}
    op.navigation._read_area = Mock(return_value=(op.last_screenshot, modal))
    assert op.leave().is_fail
    op.ctx.controller.btn_tap.assert_not_called()


def test_combat_guard_stops_strategy_before_wrapping_a_valid_return(monkeypatch: pytest.MonkeyPatch) -> None:
    context = SimpleNamespace(controller=Mock(), auto_battle_context=Mock(), run_context=Mock(),
                              withered_domain=SimpleNamespace(app_id='hollow_eval_speed'), current_instance_idx=1)
    op = hollow_eval_battle.GamepadHollowEvalBattle(context)
    op._after_round_wait = Mock()
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(hollow_eval_battle, 'is_native_battle', Mock(return_value=False))
    assert not op.prepare().is_success
    context.controller.begin_battle_input_scope.assert_not_called()
    op._active = True
    op._in_return_scene = Mock(return_value=True)
    op.save_screenshot = Mock()
    monkeypatch.setattr(hollow_eval_battle, 'MacBattleHudGuard', Mock(return_value=Mock(return_value=False)))
    assert op.fight().is_success
    context.auto_battle_context.stop_auto_battle.assert_called_once()
    context.controller.btn_tap.assert_not_called()


def test_merit_milestone_requires_current_floor_and_stable_board() -> None:
    context = SimpleNamespace(level_info=SimpleNamespace(level=2, phase=1))
    op = GamepadHollowEvalStep(SimpleNamespace(controller=Mock(), withered_domain=context), stop_on_merit=True)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='第三层考察点已核')
    board = _board((440, 590, 740, 890), 0)
    op._confirmed_merit_floor = 2
    op.floor = 3
    assert op._merit_stop(board) is None
    op._confirmed_merit_floor = 3
    op.merit_award_floor = 3
    assert not op._merit_stop(board).is_success
    result = op._merit_stop(board)
    assert result.status == op.STATUS_READY_TO_LEAVE
    assert result.data == {
        'floor': 3, 'empty_merit_tile': False, 'screenshot': '第三层考察点已核', 'weekly_cap_screenshot': None,
    }
    op.ctx.controller.btn_tap.assert_not_called()


def test_closed_award_counts_once_and_next_expedition_clears_it() -> None:
    op = hollow_eval_board.GamepadHollowEvalExplore(SimpleNamespace())
    op._after_round_wait = Mock()
    op.merit_receipt._after_round_wait = Mock()
    op.merit_receipt.try_confirm = Mock(return_value=None)
    op.merit_receipt.pending = (30, '当前回执')
    op.merit_receipt.requested_frame = 10
    op.step.active_board = Mock(return_value=_board((440, 590, 740, 890), 0))
    op.step.floor = 2
    op.last_screenshot_time = 11
    assert '30' in op._handle_merit_receipt().status
    assert op._handle_merit_receipt() is None
    assert op.merit_receipts == [(30, '当前回执')] and op.step.merit_award_floor == 2
    op.handle_init()
    assert not op.merit_receipts and op.step.merit_award_floor is None


def test_short_loop_can_return_to_mainline_without_inheriting_an_award() -> None:
    positions = [(400, 500), (240, 500), (240, 380), (560, 500)]
    labels = ('当前', '开启的门', '传送点', '诡雾')
    nodes = [
        HollowZeroMapNode(Rect(x - 25, y - 25, x + 25, y + 25), HollowZeroEntry(f'{i:04d}-{label}'), confidence=0.95)
        for i, ((x, y), label) in enumerate(zip(positions, labels, strict=True))
    ]
    board = HollowZeroMap(nodes, 0, {0: [1, 3], 1: [0, 2], 2: [1], 3: [0]})
    nodes[3].path_first_node = nodes[3]
    hollow = SimpleNamespace(level_info=SimpleNamespace(level=2, phase=1), get_next_to_move=Mock(return_value=nodes[3]),
                             _get_avoid=Mock(return_value=[]))
    op = GamepadHollowEvalStep(SimpleNamespace(controller=Mock(), withered_domain=hollow))
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='棋盘')
    op.active_board = Mock(return_value=board)
    op.floor = 2
    landmarks = tuple(sorted((cell, name) for cell, name in _board_cells(board).items() if name in op.LANDMARKS))
    op._recent_routes.append(((2, 1, landmarks, None), (1, 0)))
    assert not op.move().is_fail
    op.ctx.controller.btn_tap.assert_called_once_with('dpad_left')
    assert op._mainline_phase == (2, 1) and op.merit_award_floor is None


@pytest.mark.parametrize('empty_tile', [False, True])
def test_unproven_third_floor_or_empty_tile_keeps_the_expedition(empty_tile: bool) -> None:
    context = SimpleNamespace(level_info=SimpleNamespace(level=3, phase=2))
    op = GamepadHollowEvalStep(SimpleNamespace(controller=Mock(), withered_domain=context), stop_on_merit=True)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock(return_value='现场')
    board = _board((440, 590, 740, 890), 0)
    if empty_tile:
        board.nodes[1].entry = HollowZeroEntry('0073-业绩考察点空')
    op.floor = 3
    assert not op._merit_stop(board).is_success
    result = op._merit_stop(board)
    assert result.is_fail and result.data['weekly_cap_screenshot'] is None
    op.ctx.controller.btn_tap.assert_not_called()


def test_known_battle_entry_waits_for_hud_without_more_board_input(monkeypatch: pytest.MonkeyPatch) -> None:
    explore = hollow_eval_board.GamepadHollowEvalExplore(SimpleNamespace(controller=Mock()))
    explore._after_round_wait = Mock()
    explore._stalled_frames = 8
    explore._combat_wait_until = 40
    explore.event.identify_entry = Mock(return_value=None)
    explore.event.try_respond = Mock(return_value=None)
    explore.step.move = Mock()
    monkeypatch.setattr(hollow_eval_board, 'is_native_battle', Mock(return_value=False))
    monkeypatch.setattr(hollow_eval_board.time, 'monotonic', Mock(return_value=20))
    result = explore.explore()
    assert not result.is_fail and '等待过场' in result.status
    explore.step.move.assert_not_called()
    explore.ctx.controller.btn_tap.assert_not_called()


def test_mid_battle_result_does_not_confirm_final_b_prompt() -> None:
    op = hollow_eval_battle.GamepadHollowEvalBattleResult(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._has_result_action = Mock(side_effect=lambda _, icon, _label: icon == 'B')
    op.navigation._read_area = Mock(return_value=(None, {}))
    assert not op.confirm().is_success
    op.ctx.controller.btn_tap.assert_not_called()
