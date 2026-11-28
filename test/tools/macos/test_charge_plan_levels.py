"""体力深度追猎等级从原计划、GUI到准备节点的离线检查。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.application.notorious_hunt.notorious_hunt_config import NotoriousHuntLevelEnum
from zzz_od.operation.gamepad import deep_hunt
from zzz_od.operation.gamepad.charge_plan import validate_macos_charge_plan
from zzz_od.operation.gamepad.deep_hunt import GamepadDeepHunt, GamepadDeepHuntPrepare


def hunt_plan(level: str) -> ChargePlanItem:
    """直接构造计划，不读取或写入本机实例。"""
    return ChargePlanItem(category_name='恶名狩猎', mission_type_name='库萨里库', level=level)


@pytest.mark.parametrize('level', [item.value.value for item in NotoriousHuntLevelEnum])
def test_charge_validation_allows_original_hunt_levels(level: str) -> None:
    config = SimpleNamespace(restore_charge='不使用', double_reward=False, plan_list=[hunt_plan(level)])
    assert validate_macos_charge_plan(config) is None


@pytest.mark.parametrize('level', ['最高可用等级', 'Lv.65', '等级Lv.66', '等级Lv.060', ''])
def test_invalid_level_is_rejected_before_mode_input(level: str) -> None:
    plan = hunt_plan(level)
    config = SimpleNamespace(restore_charge='不使用', double_reward=False, plan_list=[plan])
    assert validate_macos_charge_plan(config) is not None
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = GamepadDeepHunt(ctx, plan, config=config)
    operation._after_round_wait = Mock()
    assert operation.prepare().is_fail
    ctx.controller.btn_tap.assert_not_called()


def test_other_categories_do_not_gain_unimplemented_level_selection() -> None:
    for plan in [ChargePlanItem(level='等级Lv.50'), ChargePlanItem(category_name='专业挑战室', mission_type_name='恶名·杜拉罕', level='等级Lv.50')]:
        config = SimpleNamespace(restore_charge='不使用', double_reward=False, plan_list=[plan])
        assert validate_macos_charge_plan(config) is not None


def level_words(value: str, duplicate: bool = False, expanded: bool = False) -> dict:
    """位置来自已建档的恶名等级标题与下拉菜单。"""
    result = {value: [SimpleNamespace(rect=Rect(1590, 30, 1740, 70))]}
    if duplicate:
        result[value].append(SimpleNamespace(rect=Rect(1590, 30, 1740, 70)))
    if expanded:
        result['等级Lv.30'] = [SimpleNamespace(rect=Rect(1630, 110, 1760, 150))]
    return result


@pytest.mark.parametrize(('words', 'expected'), [
    (level_words('等级Lv.60'), 'ok'),
    (level_words('等级 Lv.60'), 'ok'),
    (level_words('Lv.60'), 'ok'),
    (level_words('等级Lv.50'), 'invalid'),
    (level_words('等级Lv.060'), 'invalid'),
    (level_words('等级Lv.60', duplicate=True), 'wait'),
    (level_words('等级Lv.60', expanded=True), 'wait'),
    (level_words('等级Lv.60?'), 'wait'),
    ({}, 'wait'),
])
def test_explicit_level_is_checked_again_before_next(
    monkeypatch: pytest.MonkeyPatch, words: dict, expected: str,
) -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = GamepadDeepHuntPrepare(ctx, hunt_plan('等级Lv.60'))
    operation._after_round_wait = Mock()
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    monkeypatch.setattr(deep_hunt, 'read_preset_area', lambda *_args: (object(), words))
    monkeypatch.setattr(deep_hunt, 'deep_target_selected', lambda *_args: True)
    monkeypatch.setattr(deep_hunt, 'read_preset_charge', lambda *_args: (180, 60))
    assert operation._explicit_level_state() == expected
    result = operation.prepare_deployment()
    assert result.is_fail == (expected == 'invalid')
    assert ctx.controller.btn_tap.call_args_list == ([call('start')] if expected == 'ok' else [])


def test_explicit_level_uses_existing_dropdown_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    """具体等级依次移焦、确认、回读标题；不把展开中的目标当作完成。"""
    from zzz_od.operation.gamepad import notorious_hunt

    plan = hunt_plan('等级Lv.30')
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = GamepadDeepHuntPrepare(ctx, plan)
    operation._after_round_wait = Mock()
    operation.navigation._read_area = Mock(return_value=(object(), {
        '等级Lv.65': [SimpleNamespace(rect=Rect(1590, 30, 1740, 70)), SimpleNamespace(rect=Rect(1630, 375, 1760, 420))],
        '等级Lv.30': [SimpleNamespace(rect=Rect(1630, 110, 1760, 150))],
    }))
    monkeypatch.setattr(notorious_hunt, 'has_filled_highlight', lambda _image, rect, _color: rect.center.y > 300)
    assert operation.choose_level().result == OperationRoundResultEnum.RETRY
    ctx.controller.btn_tap.assert_called_once_with('dpad_up')
    monkeypatch.setattr(notorious_hunt, 'has_filled_highlight', lambda _image, rect, _color: 95 < rect.center.y < 200)
    assert operation.choose_level().result == OperationRoundResultEnum.RETRY
    assert ctx.controller.btn_tap.call_args_list[-1] == call('south')
    operation.navigation._read_area.return_value = (object(), level_words('等级Lv.30'))
    assert operation.choose_level().is_success
    assert plan.level == '等级Lv.30'


def test_default_keeps_game_level_without_opening_dropdown() -> None:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    operation = GamepadDeepHuntPrepare(ctx, hunt_plan('默认等级'))
    operation._after_round_wait = Mock()
    operation.navigation._read_area = Mock()
    assert operation.choose_level().is_success
    operation.navigation._read_area.assert_not_called()
    ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('category', ['恶名狩猎', '实战模拟室', '区域巡防', '专业挑战室', '合成电池'])
def test_charge_gui_shows_level_only_where_both_platforms_use_it(category: str) -> None:
    from zzz_od.gui.view.one_dragon.charge_plan_interface import ChargePlanCard

    card = SimpleNamespace(plan=ChargePlanItem(category_name=category, level='等级Lv.60'), level_combo_box=Mock())
    ChargePlanCard.init_level_combo_box(card)
    options, saved = card.level_combo_box.set_items.call_args.args
    assert [item.value for item in options] == [item.value.value for item in NotoriousHuntLevelEnum]
    assert saved == card.plan.level == '等级Lv.60'
    card.level_combo_box.setVisible.assert_called_once_with(category == '恶名狩猎')


def test_charge_gui_level_change_uses_original_save_signal() -> None:
    from zzz_od.gui.view.one_dragon.charge_plan_interface import ChargePlanCard

    plan = hunt_plan('默认等级')
    before = plan.to_dict()
    card = SimpleNamespace(plan=plan, level_combo_box=Mock(), _emit_value=Mock())
    card.level_combo_box.itemData.return_value = '等级Lv.50'
    ChargePlanCard._on_level_changed(card, 3)
    assert plan.to_dict() == {**before, 'level': '等级Lv.50'}
    card._emit_value.assert_called_once_with()
