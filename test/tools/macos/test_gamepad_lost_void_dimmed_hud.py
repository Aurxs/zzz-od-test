"""灰暗普攻只延长已知战斗状态等待，不放行输入。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.operation.gamepad.lost_void_run_level import GamepadLostVoidRunLevel


@pytest.mark.parametrize(('dimmed', 'elapsed', 'failed'), [(False, 13, True), (True, 13, False), (True, 46, True)])
def test_dimmed_wait_has_separate_bound_and_never_resumes_without_hud(
    monkeypatch: pytest.MonkeyPatch, dimmed: bool, elapsed: int, failed: bool,
) -> None:
    operation = object.__new__(GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(
        auto_battle_context=Mock(),
        controller=SimpleNamespace(battle_input_blocked=True, refresh_battle_input_scope=Mock(return_value=False)),
        battle_assistant_config=SimpleNamespace(screenshot_interval=0.1),
    )
    operation._battle_active = False
    operation._recovering_battle_frame = False
    operation._unknown_hud_since = 100
    operation.region_type = LostVoidRegionType.ENTRY
    operation.last_screenshot = object()
    operation._stop_battle = Mock()
    operation.save_screenshot = Mock()
    operation.check_and_update_current_screen = Mock(return_value=None)
    operation.round_by_find_area = Mock(side_effect=lambda image, screen, area: SimpleNamespace(
        is_success=dimmed and area == '手柄-普攻灰暗',
    ))
    operation.round_wait = Mock(return_value='wait')
    operation.round_fail = Mock(return_value='failed')
    monkeypatch.setattr('zzz_od.operation.gamepad.lost_void_run_level.time.monotonic', lambda: 100 + elapsed)
    assert operation.in_battle() == ('failed' if failed else 'wait')
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    if not failed:
        operation.ctx.controller.refresh_battle_input_scope.return_value = True
        assert operation.in_battle() == 'wait'
        operation.ctx.auto_battle_context.resume_auto_battle.assert_called_once()
        assert operation._unknown_hud_since == 0


def test_dimmed_ui_template_is_known_wait_but_not_active_attack_or_reward_menu() -> None:
    """用纯色画布核对公共UI小模板；私人整屏验收图保留在本机。"""
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    tm = TemplateMatcher(TemplateLoader())
    area = loader.get_area('迷失之地-大世界', '手柄-普攻灰暗')
    screens = Path(__file__).resolve().parents[3] / 'screens'
    frame = np.full((1080, 1920, 3), 17, dtype=np.uint8)
    template = tm.template_loader.get_template(area.template_sub_dir, area.template_id).raw
    height, width = template.shape[:2]
    frame[area.rect.y1:area.rect.y1 + height, area.rect.x1:area.rect.x1 + width] = template
    assert tm.match_template(cv2_utils.crop_image_only(frame, area.rect), area.template_sub_dir,
                             area.template_id, threshold=0.9).max is not None
    battle = object.__new__(AutoBattleContext)
    battle.ctx = SimpleNamespace(tm=tm)
    battle.area_btn_normal = SimpleNamespace(rect=Rect(1403, 916, 1505, 1017))
    battle.normal_attack_template_variants = (('ios_gamepad', 'lost_void_attack_inner'),)
    assert not battle.is_normal_attack_btn_available(frame)
    for name in ('迷失之地-通用选择/ios_single_initial.webp', '迷失之地-挑战结果/ios_final_s.webp',
                 '迷失之地-邦布商店/ios_gold_store.webp'):
        frame = cv2_utils.read_image(str(screens / name))
        assert tm.match_template(cv2_utils.crop_image_only(frame, area.rect), area.template_sub_dir,
                                 area.template_id, threshold=0.9).max is None
