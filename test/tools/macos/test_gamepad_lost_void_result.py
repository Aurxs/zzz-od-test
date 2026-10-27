"""道中核对完成关卡，最终核对胜利标识与真实结晶增量。"""

from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult,MatchResultList
from zzz_od.operation.gamepad.lost_void_result import GamepadLostVoidBattleResult
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel


def words(*texts: str) -> dict[str,MatchResultList]:
    result={}
    for index,text in enumerate(texts):
        matches=MatchResultList()
        matches.append(MatchResult(1,20+index*150,10,100,30))
        result[text]=matches
    return result


def make_operation(objective: dict,actions: dict) -> GamepadLostVoidBattleResult:
    op=GamepadLostVoidBattleResult(SimpleNamespace(controller=Mock()))
    op.last_screenshot=np.zeros((1080,1920,3),dtype=np.uint8)
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=True))
    op.navigation._read_area=lambda screen,name:(op.last_screenshot,objective if name=='手柄-完成关卡' else actions)
    op._after_round_wait=Mock()
    op.save_screenshot=Mock()
    return op


@pytest.mark.parametrize(('icon','label','key','status','region'),[
    ('A','确定','south',LostVoidRunLevel.STATUS_NEXT_LEVEL,'挚交会谈'),
    ('B','完成','east',LostVoidRunLevel.STATUS_COMPLETE,'入口'),
])
def test_result_preserves_next_region_and_confirms_once(icon: str,label: str,key: str,status: str,region: str) -> None:
    op=make_operation(words('完成关卡','1/1'),words(icon,label))
    assert not op.confirm().is_success
    assert not op.confirm().is_success
    op.ctx.controller.btn_tap.assert_called_once_with(key)
    op.round_by_find_area.return_value=SimpleNamespace(is_success=False)
    result=op.confirm()
    assert result.is_success and result.status==status and result.data==region


def test_missing_completion_objective_does_not_confirm_or_count() -> None:
    op=make_operation(words('完成关卡','0/1'),words('B','完成'))
    assert not op.confirm().is_success
    op.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('completion_banner','s_grade','gain','accepted'),[
    (False,True,'+4500',True),
    (True,False,'+4500',True),
    (False,True,'+0',False),
    (False,False,'+4500',False),
])
def test_final_result_needs_victory_and_positive_data(completion_banner: bool,s_grade: bool,gain: str,accepted: bool) -> None:
    op=make_operation({},words('B','完成'))
    op.investigation_completed=completion_banner
    op.navigation._read_area=lambda screen,name:(op.last_screenshot,
        {} if name=='手柄-完成关卡' else words(gain) if name=='手柄-最终结晶' else words('B','完成'))
    op.round_by_find_area=Mock(side_effect=lambda screen,name,area:SimpleNamespace(
        is_success=area=='标题-挑战结果' or (area=='手柄-最终S评级' and s_grade)))
    assert not op.confirm().is_success
    if accepted:
        op.ctx.controller.btn_tap.assert_called_once_with('east')
    else:
        op.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('name','expected'), [('ios_final_s.webp',True),('ios_aborted_result.webp',False)])
def test_actual_final_grade_rejects_aborted_result(name: str,expected: bool) -> None:
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.template_loader import TemplateLoader
    from one_dragon.utils import cv2_utils
    image=cv2_utils.read_image(str(Path(__file__).resolve().parents[3]/'screens'/'迷失之地-挑战结果'/name))
    match=TemplateMatcher(TemplateLoader()).match_template(
        image[335:815,710:1215],'ios_gamepad','lost_void_final_s',threshold=0.9,
    )
    assert (match.max is not None) is expected
