"""商店适配只验证平台分流与配置保留，不连接游戏。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.screen_area import ScreenArea
from zzz_od.application.coffee import coffee_app
from zzz_od.application.coffee.coffee_app import CoffeeApp
from zzz_od.application.coffee.coffee_config import CoffeeTransportPoint
from zzz_od.application.random_play import random_play_app
from zzz_od.application.random_play.random_play_app import RandomPlayApp
from zzz_od.operation.gamepad import shop


@pytest.fixture(autouse=True)
def memory_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """节点测试只记录留图意图，不写开发者的真实截图目录。"""
    for module in (shop, coffee_app, random_play_app):
        monkeypatch.setattr(module, 'save_shop_frame', Mock(return_value='memory.png'))


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> CoffeeApp:
    """用内存候选及假控制器验证原业务节点。"""
    result = CoffeeApp.__new__(CoffeeApp)
    result.ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap', 'interact', 'click', 'drag_to']),
        screen_loader=Mock(), ocr=Mock(), compendium_service=Mock(),
    )
    result.config = SimpleNamespace(
        transport_point=CoffeeTransportPoint.POINT_2.value.value,
        run_charge_plan_afterwards=False,
    )
    result.had_coffee_list = set()
    result.chosen_coffee = None
    result.resume_from_charge_reward = False
    result.turn_compensator = Mock()
    result._previous_node = None
    result._previous_round_result = None
    result.node_clicked = False
    result.last_screenshot = object()
    monkeypatch.setattr(result, '_after_round_wait', Mock())
    monkeypatch.setattr(result, 'screenshot', Mock())
    monkeypatch.setattr(result, 'round_by_find_area', Mock(return_value=result.round_retry()))
    monkeypatch.setattr(coffee_app, 'sys', SimpleNamespace(platform='darwin'))
    return result


def test_shop_unknown_or_missing_prompt_never_sends_input(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有已核实按键或专属可识别提示时，不退回坐标点击。"""
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_fail
    monkeypatch.setitem(shop.SHOP_ACTION_KEYS, ('咖啡店', '电量确认'), 'south')
    app.ctx.screen_loader.get_area.return_value = ScreenArea()
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_fail
    app.ctx.controller.btn_tap.assert_not_called()
    app.ctx.controller.click.assert_not_called()


def test_shop_requires_current_prompt_before_single_tap(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已经核实的动作仍需同帧提示，命中后只点按一次。"""
    monkeypatch.setitem(shop.SHOP_ACTION_KEYS, ('咖啡店', '电量确认'), 'xbox_a')
    app.ctx.screen_loader.get_area.return_value = ScreenArea(text='确认')
    monkeypatch.setattr(app, 'round_by_find_area', Mock(return_value=app.round_retry()))
    assert not shop.press_shop_action(app, '咖啡店', '电量确认').is_success
    app.ctx.controller.btn_tap.assert_not_called()
    app.round_by_find_area.return_value = app.round_success()
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_success
    app.ctx.controller.btn_tap.assert_called_once_with('south')


def test_daily_action_saves_both_frames_and_never_repeats(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """消费前先留图，发送后重新截图；再次调用不能再确认。"""
    events: list[str] = []
    monkeypatch.setitem(shop.SHOP_ACTION_KEYS, ('咖啡店', '电量确认'), 'south')
    app.ctx.screen_loader.get_area.return_value = ScreenArea(text='确认')
    monkeypatch.setattr(app, 'round_by_find_area', Mock(return_value=app.round_success()))

    def save(operation: CoffeeApp, screen_name: str, stage: str) -> str:
        """记录保存时序，文件系统由独立证据保存接口处理。"""
        events.append(stage)
        return 'memory.png'

    monkeypatch.setattr(shop, 'save_shop_frame', save)
    app.ctx.controller.btn_tap.side_effect = lambda key: events.append('发送按键')
    app.screenshot.side_effect = lambda: events.append('获取新帧')
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_success
    assert events == ['电量确认_操作前', '发送按键', '获取新帧', '电量确认_操作后']
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_fail
    app.ctx.controller.btn_tap.assert_called_once_with('south')


def test_missing_before_frame_stops_before_daily_input(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """证据写盘失败时保留当天机会，不先按键再报告缺图。"""
    monkeypatch.setitem(shop.SHOP_ACTION_KEYS, ('咖啡店', '电量确认'), 'south')
    app.ctx.screen_loader.get_area.return_value = ScreenArea(text='确认')
    monkeypatch.setattr(app, 'round_by_find_area', Mock(return_value=app.round_success()))
    monkeypatch.setattr(shop, 'save_shop_frame', Mock(return_value=None))
    assert shop.press_shop_action(app, '咖啡店', '电量确认').is_fail
    app.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('supported', [True, False])
def test_coffee_transport_keeps_saved_destination(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch, supported: bool,
) -> None:
    """支持点调公共手柄传送；需转向的六分街不会被换成澄辉坪。"""
    factory = Mock()
    factory.return_value.execute.return_value = OperationResult(True)
    monkeypatch.setitem(sys.modules, 'zzz_od.operation.gamepad.transport',
                        SimpleNamespace(GamepadTransport=factory))
    if not supported:
        app.config.transport_point = CoffeeTransportPoint.POINT_1.value.value
    saved = app.config.transport_point
    result = app.transport()
    assert result.is_success == supported
    assert app.config.transport_point == saved
    if supported:
        factory.assert_called_once_with(app.ctx, '澄辉坪', '汀曼咖啡')
    else:
        factory.assert_not_called()


def test_new_macos_run_rechecks_coffee_instead_of_reusing_yesterday(
    app: CoffeeApp,
) -> None:
    """应用跨日复用时清除上次候选记录，原传送与体力开关仍保留。"""
    app.had_coffee_list.add('汀曼特调')
    app.chosen_coffee = SimpleNamespace(coffee_name='汀曼特调')
    saved = (app.config.transport_point, app.config.run_charge_plan_afterwards)
    app.handle_init()
    assert app.had_coffee_list == set() and app.chosen_coffee is None
    assert (app.config.transport_point, app.config.run_charge_plan_afterwards) == saved


def test_coffee_uses_visible_extra_before_tinmaster(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对话中保留原额外咖啡优先级，选中前由公共操作核对焦点。"""
    extra = SimpleNamespace(coffee_name='额外特调', extra=True)
    regular = SimpleNamespace(coffee_name='汀曼特调', extra=False)
    app.ctx.compendium_service.get_extra_coffee_list.return_value = [extra]
    app.ctx.compendium_service.name_2_coffee = {
        extra.coffee_name: extra, regular.coffee_name: regular,
    }
    app.ctx.ocr.crop_and_run_ocr.return_value = {'请来一杯汀曼特调！': Mock(), '请来一杯额外特调！': Mock()}
    monkeypatch.setattr(app, 'round_by_find_area', lambda image, screen, name: app.round_retry()
                        if name == '手柄-今日已喝' else app.round_success())
    factory = Mock()
    factory.return_value.execute.return_value = OperationResult(True)
    monkeypatch.setitem(sys.modules, 'zzz_od.operation.gamepad.dialog',
                        SimpleNamespace(GamepadChooseDialogOption=factory))
    assert app.dialog_choose_coffee().status == '已点单'
    factory.assert_called_once_with(app.ctx, '请来一杯额外特调！')
    assert app.chosen_coffee is extra
    assert app._get_coffee_to_choose() == ['汀曼特调']
    app.ctx.controller.click.assert_not_called()


def test_coffee_does_not_call_blank_frame_already_drunk(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标题消失还需大世界证据，过渡帧不能记成功。"""
    monkeypatch.setitem(sys.modules, 'zzz_od.operation.gamepad.dialog',
                        SimpleNamespace(GamepadChooseDialogOption=Mock()))
    finder = Mock(return_value=app.round_retry())
    monkeypatch.setattr(app, 'round_by_find_area', finder)
    assert not app.dialog_choose_coffee().is_success
    finder.side_effect = [app.round_retry(), app.round_success()]
    assert app.dialog_choose_coffee().status == '已喝过'
    app.ctx.controller.btn_tap.assert_not_called()
    app.ctx.controller.click.assert_not_called()


def test_extra_confirmation_returns_to_dialog_and_empty_selection_cannot_confirm(
    app: CoffeeApp, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """额外咖啡继续对话菜单；未记录咖啡不发送确认键。"""
    action = Mock(return_value=app.round_success())
    monkeypatch.setattr(coffee_app, 'press_shop_action', action)
    monkeypatch.setattr(app, 'round_by_find_area', Mock(return_value=app.round_success()))
    assert app.charge_confirm().is_fail
    action.assert_not_called()
    app.chosen_coffee = SimpleNamespace(extra=True)
    monkeypatch.setattr(app, '_macos_energy_reward_visible', Mock(return_value=True))
    assert app.charge_confirm().status == CoffeeApp.STATUS_MACOS_EXTRA_COFFEE
    app.ctx.controller.btn_tap.assert_called_once_with('south')


def test_random_play_skips_running_without_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """营业态仍保留原跳过状态，不尝试再次营业。"""
    app = RandomPlayApp.__new__(RandomPlayApp)
    app.ctx = SimpleNamespace(controller=Mock(spec=['btn_tap', 'click']))
    app.config = SimpleNamespace(agent_name_1='安比', agent_name_2='妮可')
    app.run_record = SimpleNamespace(get_current_dt=lambda: '20261025')
    app.last_screenshot = object()
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(random_play_app, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(app, 'round_by_find_area', Mock(return_value=app.round_success()))
    assert app.check_running().status == RandomPlayApp.STATUS_ALREADY_RUNNING
    assert (app.config.agent_name_1, app.config.agent_name_2) == ('安比', '妮可')
    app.ctx.controller.btn_tap.assert_not_called()
    app.ctx.controller.click.assert_not_called()


def test_random_play_unknown_promoter_entry_cannot_finish_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mac 入口失败不能沿 PC 的关闭页面分支记为营业成功。"""
    app = RandomPlayApp.__new__(RandomPlayApp)
    monkeypatch.setattr(app, '_after_round_wait', Mock())
    monkeypatch.setattr(random_play_app, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(RandomPlayApp, 'previous_node', property(lambda self: SimpleNamespace(
        name='点击宣传员入口', status='手柄宣传员入口未建档',
    )))
    action = Mock()
    monkeypatch.setattr(random_play_app, 'press_shop_action', action)
    result = app.close_business_page()
    assert result.is_fail and result.status == '手柄宣传员入口未建档'
    action.assert_not_called()
