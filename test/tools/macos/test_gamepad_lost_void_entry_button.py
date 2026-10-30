"""入口按钮就绪时无需门名OCR，明确NPC和未就绪按钮仍不放行。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_interact_target_const import (
    LostVoidInteractTarget,
)
from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel


@pytest.mark.parametrize(('entry', 'button', 'world', 'text', 'accepted'), [
    (True, True, True, '复杂区域', True),
    (True, True, True, '', True),
    (True, False, True, '复杂区域', False),
    (False, True, True, '', False),
    (True, True, False, '', False),
    (True, True, True, '蕾', False),
])
def test_entry_button_readiness_preserves_npc_and_world_guards(
    entry: bool, button: bool, world: bool, text: str, accepted: bool,
) -> None:
    """按入口意图和实际按钮进入；不再因复杂区域或门名漏读反复走位。"""
    op = object.__new__(GamepadLostVoidRunLevel)
    op.region_type = LostVoidRegionType.ENTRY
    op.interact_target = LostVoidInteractTarget('战斗-鸣徽', '战斗-鸣徽', is_entry=entry)
    op.interact_attempted = False
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    op.ctx = SimpleNamespace(controller=Mock(), ocr=Mock(), screen_loader=Mock(),
                             lost_void=SimpleNamespace(in_normal_world=Mock(return_value=world)))
    op.ctx.ocr.crop_and_run_ocr.return_value = {text: []} if text else {}
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=button))
    op.save_screenshot = Mock()
    op.round_wait = Mock(return_value='waiting')

    assert op._try_entry_button() == ('waiting' if accepted else None)
    if accepted:
        op.ctx.controller.interact.assert_called_once_with(press=True, press_time=0.2, release=True)
        assert op.interact_attempted and op.locked_interact_target is op.interact_target
    else:
        op.ctx.controller.interact.assert_not_called()
        assert not op.interact_attempted
