"""实拍高亮下核对原优先级目标，确认后必须看到返回。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.lost_void.context.lost_void_artifact import LostVoidArtifact
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import LostVoidArtifactPos
from zzz_od.operation.gamepad.lost_void_common import GamepadLostVoidChooseCommon


def make_operation() -> tuple[GamepadLostVoidChooseCommon, list[LostVoidArtifactPos]]:
    candidates=[
        LostVoidArtifactPos(LostVoidArtifact('机敏','安全气囊','A'),Rect(485,520,655,550)),
        LostVoidArtifactPos(LostVoidArtifact('携游','充气泳圈','B'),Rect(870,520,1040,550)),
        LostVoidArtifactPos(LostVoidArtifact('携游','儿童餐盒','B'),Rect(1270,520,1460,550)),
    ]
    ctx=SimpleNamespace(
        controller=Mock(),
        screen_loader=SimpleNamespace(get_area=Mock(return_value=SimpleNamespace(rect=Rect(80,440,1898,650)))),
        lost_void=SimpleNamespace(
            in_normal_world=Mock(return_value=False),
            challenge_config=SimpleNamespace(artifact_priority_new=True),
            get_artifact_by_priority=Mock(return_value=[candidates[0]]),
        ),
    )
    operation=GamepadLostVoidChooseCommon(ctx)
    operation.last_screenshot=cv2_utils.read_image(str(Path(__file__).resolve().parents[3]/'screens'/'迷失之地-通用选择'/'ios_single_initial.webp'))
    operation._after_round_wait=Mock()
    operation.can_handle=Mock(return_value=True)
    candidates[0].chosen=True
    candidates[0].can_choose=False
    ctx.lost_void.get_artifact_pos=Mock(return_value=candidates)
    operation.parser.check_choose_title=Mock()
    operation.parser.to_choose_num=1
    return operation,candidates


def test_priority_target_changes_focus_instead_of_accepting_default() -> None:
    operation,candidates=make_operation()
    operation.ctx.lost_void.get_artifact_by_priority.return_value=[candidates[1]]
    assert not operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('dpad_right')
    assert not operation._confirmed


def test_confirm_once_and_require_world_before_success() -> None:
    operation,_=make_operation()
    assert not operation.choose().is_success
    assert not operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    operation.ctx.lost_void.in_normal_world.return_value=True
    assert operation.choose().is_success
    assert not operation.ctx.lost_void.priority_updated


def test_confirmed_upgrade_hands_back_to_store_without_another_a() -> None:
    operation, _ = make_operation()
    operation._confirmed = True
    operation.can_handle.return_value = False
    operation.check_and_update_current_screen = Mock(return_value='迷失之地-邦布商店')
    assert operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_not_called()


def make_gain_operation() -> GamepadLostVoidChooseCommon:
    from one_dragon.base.matcher.match_result import MatchResult,MatchResultList
    operation,_=make_operation()
    operation.last_screenshot_time=100
    footer={}
    for text in ('A','确定'):
        matches=MatchResultList()
        matches.append(MatchResult(1,20,20,70,30))
        footer[text]=matches
    operation.navigation._read_area=Mock(return_value=(operation.last_screenshot,footer))
    operation.save_screenshot=Mock()
    return operation


def test_gained_hint_change_returns_to_parent_after_stable_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_common as module
    operation=make_gain_operation()
    operation.gained_item_identity=Mock(side_effect=[('武备A','2'),('武备B','2'),('武备B','2')])
    monkeypatch.setattr(module.time,'monotonic',lambda:100)
    assert not operation.confirm_gain('武备已升级').is_success
    assert not operation.confirm_gain('武备已升级').is_success
    assert operation.confirm_gain('武备已升级').is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


def test_gained_hint_retry_requires_new_frame_and_stops_after_three(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_common as module
    operation=make_gain_operation()
    operation.gained_item_identity=Mock(return_value=('武备A','2'))
    now=[100]
    monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    assert not operation.confirm_gain('武备已升级').is_success
    now[0]=103
    assert not operation.confirm_gain('武备已升级').is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    for current,frame in [(103,101),(106,102)]:
        now[0]=current
        operation.last_screenshot_time=frame
        assert not operation.confirm_gain('武备已升级').is_success
    now[0]=109
    operation.last_screenshot_time=103
    assert operation.confirm_gain('武备已升级').is_fail
    assert operation.ctx.controller.btn_tap.call_count==3


def test_gain_card_ocr_may_omit_a_but_same_row_template_is_required() -> None:
    from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.template_loader import TemplateLoader

    frame = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-通用选择' / 'ios_gain_card_a.webp'))
    operation = make_gain_operation()
    operation.ctx.tm = TemplateMatcher(TemplateLoader())
    footer = frame[780:985, 780:1165]
    words = MatchResultList()
    words.append(MatchResult(1, 163, 49, 61, 33))
    ocr = {'确定': words}
    operation.gained_item_identity = Mock(return_value=('获得战利品', '[异常·击破]万能催化物'))
    operation.navigation._read_area = Mock(return_value=(footer, ocr))
    assert operation.has_a_confirmation((footer, ocr))
    assert not operation.confirm_gain('获得战利品').is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    missing = footer.copy()
    missing[40:92, 65:125] = 0
    assert not operation.has_a_confirmation((missing, ocr))
    wrong_row = footer.copy()
    wrong_row[120:160, 76:115] = footer[45:85, 76:115]
    wrong_row[40:92, 65:125] = 0
    assert not operation.has_a_confirmation((wrong_row, ocr))


def make_multi_operation() -> tuple[GamepadLostVoidChooseCommon,list[LostVoidArtifactPos]]:
    operation,_=make_operation()
    candidates=[LostVoidArtifactPos(LostVoidArtifact('通用',f'候选{index}','A'),Rect(245+index*407,520,455+index*407,550)) for index in range(4)]
    operation.last_screenshot=cv2_utils.read_image(str(Path(__file__).resolve().parents[3]/'screens'/'迷失之地-通用选择'/'ios_multi_empty.webp'))
    operation.parser.to_choose_num=2
    operation.parser._get_chosen_count_from_confirm_button=Mock(return_value=0)
    operation._multi_selected_indices=Mock(return_value=set())
    operation.ctx.lost_void.get_artifact_pos.return_value=candidates
    operation.ctx.lost_void.get_artifact_by_priority.return_value=[candidates[2]]
    return operation,candidates


def test_multi_waits_for_complete_candidates_before_navigating() -> None:
    operation,candidates=make_multi_operation()
    operation.ctx.lost_void.get_artifact_pos.return_value=candidates[:-1]
    assert not operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.lost_void.get_artifact_pos.return_value=candidates
    assert not operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('dpad_right')


def test_multi_confirms_with_x_only_after_actual_count_and_two_markers() -> None:
    from one_dragon.base.matcher.match_result import MatchResult,MatchResultList
    operation,_=make_multi_operation()
    operation.parser._get_chosen_count_from_confirm_button.return_value=2
    operation._multi_selected_indices.return_value={0,2}
    footer={}
    for text in ('x','确定(2/2)'):
        matches=MatchResultList()
        matches.append(MatchResult(1,20,20,100,30))
        footer[text]=matches
    operation.navigation._read_area=Mock(return_value=(operation.last_screenshot,footer))
    operation.save_screenshot=Mock()
    assert not operation.choose().is_success
    assert not operation.choose().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('west')
    operation.ctx.lost_void.in_normal_world.return_value=True
    assert operation.choose().is_success


def test_multi_does_not_repeat_a_without_observed_count_change() -> None:
    operation,_=make_multi_operation()
    operation._multi_expected_count=1
    operation._multi_expected_index=2
    assert not operation.choose().is_success
    assert not operation.choose().is_success
    assert operation.choose().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()


def test_same_style_label_recovers_selected_card_from_count_and_frame() -> None:
    operation, _ = make_multi_operation()
    operation.last_screenshot = cv2_utils.read_image(str(
        Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-通用选择' / 'ios_multi_same_style.webp',
    ))
    operation.parser._get_chosen_count_from_confirm_button.return_value = 1
    operation._multi_selected_indices.return_value = set()
    assert not operation.choose().is_success
    assert operation._multi_verified_selected == {0}
    operation.ctx.controller.btn_tap.assert_called_once_with('dpad_right')


@pytest.mark.parametrize('has_a_prompt', [False, True])
def test_two_gears_without_selected_badge_require_a_confirm(has_a_prompt: bool) -> None:
    from one_dragon.base.matcher.match_result import MatchResult, MatchResultList

    operation, _ = make_operation()
    operation.ctx.tm = SimpleNamespace(match_template=Mock(return_value=[]))
    operation.last_screenshot = cv2_utils.read_image(str(
        Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-通用选择' / 'ios_two_gears.webp',
    ))
    areas = {
        '手柄-名称栏搜索': Rect(80, 440, 1898, 650),
        '区域-武备名称': Rect(82, 415, 1898, 475),
    }
    operation.ctx.screen_loader.get_area.side_effect = lambda screen, name: SimpleNamespace(rect=areas[name])
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    candidates = [
        LostVoidArtifactPos(LostVoidArtifact('绝境', '战斗维生包', 'S'), Rect(660, 430, 870, 470)),
        LostVoidArtifactPos(LostVoidArtifact('绝境', '浩劫令牌', 'S'), Rect(1050, 430, 1260, 470)),
    ]
    operation.ctx.lost_void.get_artifact_pos.return_value = candidates
    operation.ctx.lost_void.get_artifact_by_priority.return_value = [candidates[0]]
    footer = {}
    for text in ('A', '确定') if has_a_prompt else ('确定',):
        matches = MatchResultList()
        matches.append(MatchResult(1, 20, 20, 100, 30))
        footer[text] = matches
    operation.navigation._read_area = Mock(return_value=(operation.last_screenshot, footer))

    assert not operation.choose().is_success
    assert operation._gear_layout
    assert operation._confirmed is has_a_prompt
    if has_a_prompt:
        operation.choose()
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
    else:
        operation.ctx.controller.btn_tap.assert_not_called()
