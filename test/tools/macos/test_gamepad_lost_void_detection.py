"""实拍 NPC 盾牌不能作为副本入口，真实交叉剑入口须保留。"""

from pathlib import Path

import pytest

from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from one_dragon.yolo.detect_utils import DetectClass, DetectFrameResult, DetectObjectResult
from zzz_od.operation.gamepad.lost_void_detection import correct_npc_gear_markers


@pytest.mark.parametrize('ignore_interact', [False, True])
def test_real_npc_is_corrected_without_reclassifying_sword_portals(ignore_interact: bool) -> None:
    image = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-大世界' / 'ios_npc_gear_misclassified.webp'))
    npc = DetectObjectResult([221, 277, 296, 351], .9, DetectClass(3, '0003-战斗-武备'))
    # 将真实剑形入口也标成武备，确认图形检查不会把正常武备入口一并抹掉。
    sword = DetectObjectResult([747, 284, 791, 331], .9, DetectClass(3, '0003-战斗-武备'))
    other = DetectObjectResult([410, 283, 456, 329], .9, DetectClass(2, '0002-战斗-鸣徽'))
    original = DetectFrameResult(image, [npc, sword, other], 100)
    result = correct_npc_gear_markers(original, TemplateMatcher(TemplateLoader()), DetectClass(0, '0000-感叹号'), ignore_interact)
    assert [item.detect_class.class_id for item in result.results] == ([3, 2] if ignore_interact else [0, 3, 2])
    assert original.results[0] is npc and npc.detect_class.class_id == 3
    assert result.run_time == original.run_time
