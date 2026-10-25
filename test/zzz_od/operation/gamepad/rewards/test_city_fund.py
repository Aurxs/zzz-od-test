"""城募整组件的已观察入口、任务状态及单次领取，不发送真实输入。"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.rewards_city_fund import GamepadCityFund

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '丽都城募'


@pytest.fixture(scope='module')
def real_ocr() -> Iterator[OnnxOcrMatcher]:
    """仅加载本地模型，三个分类共用一次初始化。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('仅使用本地已有 OCR 模型')
    assert ocr.init_model()
    yield ocr
    ocr.cleanup()


@pytest.fixture
def operation(real_ocr: OnnxOcrMatcher, monkeypatch: pytest.MonkeyPatch) -> GamepadCityFund:
    """平台区域和 OCR 均为真实实现，只替代输入与截图落盘。"""
    loader = ProfileScreenContext()
    loader.reload()
    operation = GamepadCityFund(SimpleNamespace(
        controller=Mock(spec=['click', 'btn_tap']), screen_loader=loader,
        ocr=real_ocr, tm=TemplateMatcher(TemplateLoader()),
        run_context=Mock(), current_instance_idx=2,
    ))
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'save_screenshot', Mock(side_effect=lambda prefix: prefix))
    return operation


def set_frame(operation: GamepadCityFund, state: str) -> None:
    """读取本次尚未领取的实拍，不制造已领取画面。"""
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    assert operation.last_screenshot is not None


def test_menu_uses_real_focus_and_main_tabs_exclude_purchase_entries(
    operation: GamepadCityFund,
) -> None:
    """根据代理人焦点向右移动，目标黄色后才 A；不进入 Y 解锁。"""
    set_frame(operation, 'ios_menu_agent')
    assert operation._menu_visible()
    assert not operation.open_city().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('dpad_right')
    set_frame(operation, 'ios_menu_city_focus')
    assert not operation.open_city().is_success
    assert not operation.open_city().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('dpad_right'), call('south')]
    set_frame(operation, 'ios_levels_before')
    assert operation.open_city().is_success
    assert operation.main_tab() == '等级回馈'
    assert not operation._x_claim_available()
    assert operation.claim_levels().status == '无可领取等级奖励'
    assert not operation.choose_growth().is_success
    assert operation.ctx.controller.btn_tap.call_args_list[-1] == call('right_shoulder')
    assert all(item != call('north') for item in operation.ctx.controller.btn_tap.call_args_list)


def test_three_categories_are_inspected_before_exactly_one_bulk_claim(
    operation: GamepadCityFund,
) -> None:
    """周、本期也亮黄，但只有今日四条可领，不能按三次 X。"""
    for state, tab, count in [
        ('ios_tasks_today_before', '今日任务', 4),
        ('ios_tasks_week_before', '本周任务', 0),
        ('ios_tasks_period_before', '本期任务', 0),
    ]:
        set_frame(operation, state)
        assert operation.main_tab() == '成长任务'
        assert operation.task_tab() == tab
        assert operation.task_claim_count() == count
        assert operation._x_claim_available()
        result = operation.inspect_tasks()
    assert result.is_success
    assert operation._claim_categories == ['今日任务']
    assert not operation.claim_tasks().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('left_trigger')
    set_frame(operation, 'ios_tasks_today_before')
    assert operation.claim_tasks().is_success
    assert operation.claim_tasks().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('left_trigger'), call('west')]
    # 当前 fixture 尚未领取，不能将它当作结果已完成，更不能再次 X。
    for _ in range(3):
        assert not operation.verify_tasks().is_success
    result = operation.verify_tasks()
    assert result.is_fail and result.data['pending']
    assert operation.ctx.controller.btn_tap.call_args_list == [call('left_trigger'), call('west')]


def test_unknown_reward_does_not_confirm_or_return(
    operation: GamepadCityFund,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """领取后的未知布局必须保留现场，不猜 A/B/Y。"""
    operation._tasks_claim_sent = True
    monkeypatch.setattr(operation, '_known_reward_visible', Mock(return_value=False))
    monkeypatch.setattr(operation, 'main_tab', Mock(return_value=None))
    result = operation.verify_tasks()
    assert result.is_fail and result.data['pending']
    operation.ctx.controller.btn_tap.assert_not_called()


def test_actual_claimed_tasks_and_level_reward(operation: GamepadCityFund) -> None:
    """本次生产领取后的实拍：四条已领、等级奖励确认后 X 消失。"""
    set_frame(operation, 'ios_tasks_today_after')
    assert operation.task_claim_count() == 0
    operation._tasks_claim_sent = True
    operation._claim_categories = ['今日任务']
    assert operation.verify_tasks().is_success
    set_frame(operation, 'ios_levels_claimable')
    assert operation._x_claim_available()
    assert operation.claim_levels().is_success
    set_frame(operation, 'ios_level_reward')
    assert operation._known_reward_visible()
    assert not operation.verify_levels().is_success
    set_frame(operation, 'ios_levels_after')
    assert not operation._x_claim_available()
    assert operation.verify_levels().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('west'), call('south')]
