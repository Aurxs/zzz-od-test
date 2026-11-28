"""第五防线保护已有分数，房间结果后才认可分数变化。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad import shiyu_defense_rooms
from zzz_od.operation.gamepad.shiyu_defense import GAMEPAD_SCREEN, focused_critical_node
from zzz_od.operation.gamepad.shiyu_defense_rooms import (
    GamepadShiyuRoomReturn,
    GamepadShiyuRooms,
    read_room_score,
)


def test_special_fifth_node_halo_on_real_gamepad_frame() -> None:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    repo = Path(__file__).resolve().parents[3]
    image = cv2_utils.read_image(str(repo / 'screens' / '式舆防卫战' / 'ios_critical_05_focused.webp'))
    cards = [loader.get_area(GAMEPAD_SCREEN, f'手柄-防线{idx}').rect for idx in range(1, 6)]
    assert focused_critical_node(image, cards) == 5


def test_scores_keep_incomplete_unknown_and_conflicting_results_separate() -> None:
    assert read_room_score({'待挑战': []}) == 0
    assert read_room_score({'总得分:': [], '0': []}) == 0
    assert read_room_score({'当前得分：0': []}) == 0
    assert read_room_score({'当前得分: 31,305': []}) == 31_305
    assert read_room_score({'总得分：0': [], '20,320': []}) is None
    assert read_room_score({'预计得分：0': []}) is None
    assert read_room_score({'S级': [], '31,305': []}) == 31_305
    assert read_room_score({'51,000': []}) is None
    assert read_room_score({'待挑战': [], '31,305': []}) is None


def test_room_list_with_numbered_zero_scores_on_real_gamepad_frame() -> None:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('回放需要本机 OCR 模型')
    assert ocr.init_model()
    try:
        op = GamepadShiyuRooms(SimpleNamespace(screen_loader=loader, ocr=ocr))
        repo = Path(__file__).resolve().parents[3]
        path = repo / 'screens' / '式舆防卫战' / 'ios_critical_05_zero_scores.webp'
        op.last_screenshot = cv2_utils.read_image(str(path))
        assert op.read_scores() == (0, 0, 0)
    finally:
        ocr.cleanup()


def test_existing_partial_scores_leave_rooms_untouched() -> None:
    op = object.__new__(GamepadShiyuRooms)
    op.ctx = SimpleNamespace(controller=Mock())
    op.rooms_visible = Mock(return_value=True)
    op.read_scores = Mock(return_value=(25_100, 0, 0))
    op._read_locked_room_agents = Mock(return_value=None)
    op.node_retry_times = 5
    op.save_screenshot = Mock()
    op._after_round_wait = Mock()
    assert op.plan().is_fail
    assert op._scores == (25_100, 0, 0)
    assert not op.ctx.controller.mock_calls


def test_scored_room_avatars_use_actual_game_portraits() -> None:
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    op = GamepadShiyuRooms(SimpleNamespace(screen_loader=loader, template_loader=TemplateLoader()))
    fixtures = Path(__file__).resolve().parents[3] / 'screens' / '式舆防卫战'
    area = loader.get_area(GAMEPAD_SCREEN, '手柄-房间1角色头像')
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.last_screenshot[area.y1:area.y2, area.x1:area.x2] = cv2_utils.read_image(
        str(fixtures / 'ios_scored_room_agents.webp'),
    )
    assert op._read_locked_room_agents((16_881, 0, 0)) == {'hoshimi_miyabi', 'nangongyu', 'yuzuha'}
    area_2 = loader.get_area(GAMEPAD_SCREEN, '手柄-房间2角色头像')
    op.last_screenshot[area_2.y1:area_2.y2, area_2.x1:area_2.x2] = cv2_utils.read_image(
        str(fixtures / 'ios_scored_room2_agents.webp'),
    )
    assert op._read_locked_room_agents((16_881, 22_327, 0)) == {
        'hoshimi_miyabi', 'nangongyu', 'yuzuha', 'seed', 'yeshunguang', 'sunna',
    }
    op.last_screenshot = cv2_utils.read_image(str(fixtures / 'ios_critical_05_zero_scores.webp'))
    assert op._read_locked_room_agents((16_881, 0, 0)) is None


def test_resume_scores_only_remaining_rooms_without_locked_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    team_list = [
        SimpleNamespace(idx=0, agent_id_list=['locked_a', 'locked_b', 'locked_c']),
        SimpleNamespace(idx=1, agent_id_list=['locked_c', 'spare_a', 'spare_b']),
        SimpleNamespace(idx=4, agent_id_list=['a', 'b', 'c']),
        SimpleNamespace(idx=7, agent_id_list=['d', 'e', 'f']),
    ]
    op = object.__new__(GamepadShiyuRooms)
    op.ctx = SimpleNamespace(team_config=SimpleNamespace(team_list=team_list), controller=Mock())
    op.rooms_visible = Mock(return_value=True)
    op.read_scores = Mock(return_value=(16_881, 0, 0))
    op._read_locked_room_agents = Mock(return_value={'locked_a', 'locked_b', 'locked_c'})
    op.read_attributes = Mock(return_value=['电'])
    op._after_round_wait = Mock()
    choose = Mock(return_value=[SimpleNamespace(team_idx=4), SimpleNamespace(team_idx=7)])
    monkeypatch.setattr(shiyu_defense_rooms, 'select_teams', choose)
    assert op.plan().is_success
    assert choose.call_args.args[2] == [4, 7]
    assert op._team_indices == {2: 4, 3: 7}
    assert not any('房间1' in args[0] for args, _ in op.read_attributes.call_args_list)
    assert not op.ctx.controller.mock_calls


@pytest.mark.parametrize(
    ('left_title', 'members', 'expected'),
    [
        ('编队', ['a', 'b', 'c'], 1),
        ('编队2', ['a', 'b', 'c'], None),
        ('编队', ['a', 'c', 'b'], None),
    ],
)
def test_visible_room_team_requires_unique_label_and_exact_members(
    monkeypatch: pytest.MonkeyPatch, left_title: str, members: list[str], expected: int | None,
) -> None:
    team = SimpleNamespace(name='编队2', agent_id_list=['a', 'b', 'c'])
    areas = [SimpleNamespace(rect=Rect(idx * 100, 0, idx * 100 + 100, 70)) for idx in range(6)]
    op = object.__new__(shiyu_defense_rooms._ShiyuChooseRoomTeam)
    op.target_team_idx = 1
    op.last_screenshot = np.zeros((80, 600, 3), dtype=np.uint8)
    op.ctx = SimpleNamespace(
        controller=Mock(),
        team_config=SimpleNamespace(get_team_by_idx=Mock(return_value=team), team_list=[team]),
        screen_loader=SimpleNamespace(get_area=lambda _name, label: areas[int(label[-1])]),
    )
    titles = [left_title, '编队2', '编队3', '编队4', '编队5', '编队6']
    monkeypatch.setattr(shiyu_defense_rooms, 'find_team_name', lambda _words, rect: titles[rect.x1 // 100])
    monkeypatch.setattr(
        shiyu_defense_rooms, 'recognize_predefined_team',
        Mock(return_value=SimpleNamespace(agent_match_result_list=[
            SimpleNamespace(data=SimpleNamespace(agent_id=agent)) for agent in members
        ])),
    )
    assert op._visible_matching_team({}) == expected
    assert not op.ctx.controller.mock_calls


@pytest.mark.parametrize(
    ('scores', 'success', 'fail'),
    [
        ((24_000, 0, 0), False, False),
        ((23_900, 26_000, 0), False, True),
        ((24_000, 26_000, 0), True, False),
    ],
)
def test_only_real_new_score_in_current_room_advances(
    scores: tuple[int, ...], success: bool, fail: bool,
) -> None:
    op = object.__new__(GamepadShiyuRoomReturn)
    op.ctx = SimpleNamespace(controller=Mock())
    op._exit_sent = True
    op._detail_closed = False
    op._previous_scores = (24_000, 0, 0)
    op.room = 2
    op.node_retry_times = 0
    op.rooms_visible = Mock(return_value=True)
    op.read_scores = Mock(return_value=scores)
    op.shown_room = Mock(return_value=False)
    op.save_screenshot = Mock()
    op._after_round_wait = Mock()
    result = op.exit_and_read()
    assert result.is_success == success
    assert result.is_fail == fail
    assert not op.ctx.controller.mock_calls
