"""实际圆标互斥识别，已勾选且已有行焦点时不再按A。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.lost_void import GamepadLostVoidChooseBuff

SCREENS = Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-战线肃清'


@pytest.mark.parametrize(('name','y','expected'),[
    ('ios_buff_focus.webp',454,False),
    ('ios_buff_focus_scaled.webp',454,True),
    ('ios_buff_focus_scaled.webp',597,False),
    ('ios_buff_focus_scaled.webp',740,False),
])
def test_checked_and_empty_radios_are_distinct(name: str,y: int,expected: bool) -> None:
    operation=GamepadLostVoidChooseBuff(SimpleNamespace(tm=TemplateMatcher(TemplateLoader())), '第一个')
    image=cv2_utils.read_image(str(SCREENS/name))
    assert operation.checked_state(image[y-35:y+35,1725:1810]) is expected


def test_already_selected_row_does_not_reenter_or_toggle() -> None:
    loader=ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    operation=GamepadLostVoidChooseBuff(SimpleNamespace(
        tm=TemplateMatcher(TemplateLoader()),controller=Mock(),screen_loader=loader,
    ),'第一个')
    operation._after_round_wait=Mock()
    image=cv2_utils.read_image(str(SCREENS/'ios_buff_focus_scaled.webp'))
    operation.last_screenshot=image
    title=MatchResultList()
    title.append(MatchResult(1,20,10,150,30))
    def read_area(screen: str,name: str):
        area=loader.get_area(screen,name)
        rect=area.rect
        return image[rect.y1:rect.y2,rect.x1:rect.x2], {'选择周期增益':title}
    operation.navigation._read_area=Mock(side_effect=read_area)
    assert operation.choose_buff().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
