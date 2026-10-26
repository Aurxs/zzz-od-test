"""恶名狩猎 GUI 难度选择兼容检查，不操作游戏。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.gui.app_setting import notorious_hunt_setting_interface as module


@pytest.mark.parametrize(('platform', 'saved', 'selected'), [
    ('darwin', '默认等级', '最高可用等级'),
    ('darwin', '等级Lv.50', '等级Lv.50'),
    ('win32', '默认等级', '默认等级'),
])
def test_gui_level_preserves_user_choice(
    monkeypatch: pytest.MonkeyPatch, platform: str, saved: str, selected: str,
) -> None:
    """Mac 默认最高，明确保存的等级保持原样，Windows 不新增选项。"""
    monkeypatch.setattr(module, 'sys', SimpleNamespace(platform=platform))
    card = SimpleNamespace(plan=ChargePlanItem(level=saved), level_combo_box=Mock())
    module.NotoriousHuntCard.init_level_combo_box(card)
    options, current = card.level_combo_box.set_items.call_args.args
    assert current == selected
    assert ('最高可用等级' in [option.value for option in options]) == (platform == 'darwin')
    assert card.plan.level == saved


def test_gui_change_uses_existing_plan_notification() -> None:
    """GUI 选择具体等级后写回原计划并触发原保存链路。"""
    card = SimpleNamespace(
        plan=ChargePlanItem(level='最高可用等级'),
        level_combo_box=Mock(), _emit_value=Mock(),
    )
    card.level_combo_box.itemData.return_value = '等级Lv.60'
    module.NotoriousHuntCard._on_level_changed(card, 2)
    assert card.plan.level == '等级Lv.60'
    card._emit_value.assert_called_once_with()
