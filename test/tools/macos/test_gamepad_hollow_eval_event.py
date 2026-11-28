"""回放施工废墟实拍事件及核对手柄输入。"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.withered_domain.withered_domain_context import (
    WitheredDomainContext,
)
from zzz_od.game_data.agent import AgentEnum
from zzz_od.hollow_zero.hollow_zero_challenge_config import HollowZeroChallengeConfig
from zzz_od.operation.gamepad.hollow_eval_event import GamepadHollowEvalEvent


@pytest.fixture(scope='module')
def recognition() -> Iterator[SimpleNamespace]:
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    assert ocr.init_model()
    screens = ProfileScreenContext()
    screens.reload()
    yield SimpleNamespace(ocr=ocr, screen_loader=screens, tm=TemplateMatcher(TemplateLoader()))
    ocr.cleanup()


@pytest.fixture
def event(recognition: SimpleNamespace) -> GamepadHollowEvalEvent:
    ctx = SimpleNamespace(**vars(recognition), controller=Mock())
    domain = WitheredDomainContext(ctx)
    domain.init_before_run(
        challenge_config=HollowZeroChallengeConfig('', is_mock=True),
        speed_run=True,
    )
    ctx.withered_domain = domain
    op = GamepadHollowEvalEvent(ctx)
    op._after_round_wait = Mock()
    return op


def _load(op: GamepadHollowEvalEvent, name: str) -> None:
    folder = Path(__file__).resolve().parents[3] / 'screens' / '零号空洞-事件'
    op.last_screenshot = cv2_utils.read_image(str(folder / f'手柄-{name}.webp'))
    assert op.last_screenshot is not None
    op.last_screenshot_time += 1


def test_support_observes_real_team_and_updates_only_after_join(event: GamepadHollowEvalEvent) -> None:
    domain = event.ctx.withered_domain
    _load(event, '呼叫增援')
    assert event.identify_entry() == '呼叫增援'
    event.try_respond()
    assert [agent and agent.agent_name for agent in domain.agent_list] == ['雅', None, None]
    _load(event, '增援选择位置')
    event.try_respond()
    assert domain.agent_list[1] is None
    _load(event, '增援确认')
    event.try_respond()
    event.try_respond()
    assert domain.agent_list[1] is AgentEnum.SOUKAKU.value
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south'] * 3


def test_unknown_support_receipt_does_not_update_team(event: GamepadHollowEvalEvent) -> None:
    _load(event, '增援确认')
    assert event.try_respond().status == '增援结果与本次选位不一致'
    assert event.ctx.withered_domain.agent_list is None
    event.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('name', 'entry', 'key'), (
    ('商店', '邦布商人', 'east'),
    ('压力过载', None, 'south'),
    ('插件获得', None, 'south'),
    ('战后鸣徽', None, 'dpad_right'),
    ('投机客援助', None, 'dpad_down'),
))
def test_real_event_replay_presses_only_the_confirmed_action(
    event: GamepadHollowEvalEvent, name: str, entry: str | None, key: str,
) -> None:
    """鸣徽优先级会选第二张，左卡下方的 A 确认当前焦点。"""
    event.ctx.withered_domain.challenge_config.resonium_priority = ['闪避']
    _load(event, name)
    assert event.identify_entry() == entry
    result = event.try_respond()
    assert result is not None
    event.try_respond()
    event.ctx.controller.btn_tap.assert_called_once_with(key)


def test_speculator_aid_requires_both_free_effects(event: GamepadHollowEvalEvent) -> None:
    _load(event, '投机客援助')
    area = event._read_event_panel()
    assert area is not None
    area[1].pop('压力值-20')
    result = event.try_respond()
    assert result is not None and result.status == '没有核实到速刷允许的事件选项'
    event.ctx.controller.btn_tap.assert_not_called()


def test_camp_rest_uses_two_distinct_inline_prompts(event: GamepadHollowEvalEvent) -> None:
    for name in ('篝火休整', '篝火恢复'):
        _load(event, name)
        assert event.identify_entry() == '邂逅'
        assert event.try_respond() is not None
        assert event.try_respond() is not None
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south', 'south']


def test_support_reward_respects_category_priority(event: GamepadHollowEvalEvent) -> None:
    event.ctx.withered_domain.challenge_config.resonium_priority = ['决斗']
    _load(event, '增援物资')
    assert event.identify_entry() is None
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('dpad_down')


def test_support_reward_receipt_confirms_known_resonium_once(event: GamepadHollowEvalEvent) -> None:
    _load(event, '获得战利品')
    assert event.try_respond() is not None
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')


def test_lost_property_canonical_title_and_return(event: GamepadHollowEvalEvent) -> None:
    for name in ('侦探出现', '侦探递卡', '侦探道别'):
        _load(event, name)
        assert event.identify_entry() == '奇怪的侦探'
        assert event.try_respond() is not None
        assert event.try_respond() is not None
    _load(event, '音频数据卡')
    assert event.try_respond() is not None
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south'] * 3 + ['east']


@pytest.mark.parametrize('name', ('压力过载', '抗性衰弱', '蛮横'))
def test_corrosion_confirms_complete_symptom_and_single_button(
    event: GamepadHollowEvalEvent, name: str,
) -> None:
    _load(event, name)
    assert event.try_respond() is not None
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')


def test_academic_aid_replays_narrative_and_one_free_offer(event: GamepadHollowEvalEvent) -> None:
    for name in ('学会安全点', '学会离开', '学会赠礼', '学会休整', '获得战利品', '学会恢复'):
        _load(event, name)
        assert event.try_respond() is not None
        assert event.try_respond() is not None
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south'] * 6


def test_uc0011_report_continues_once_per_page(event: GamepadHollowEvalEvent) -> None:
    for name in ('特殊区域播报', '特殊区域委托目标'):
        _load(event, name)
        assert event.identify_entry() == '盲盒区域'
        assert event.try_respond() is not None
        event.last_screenshot_time += 1
        assert event.try_respond() is not None
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south', 'south']


def test_uc0011_report_waits_if_commission_code_is_missing(event: GamepadHollowEvalEvent) -> None:
    _load(event, '特殊区域播报')
    area = event._read_event_panel()
    assert area is not None
    for text in list(area[1]):
        if 'UC-0011' in text:
            del area[1][text]
    assert event.identify_entry() is None
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_not_called()


def test_special_area_report_uses_body_signature_instead_of_fixed_area_code(
    event: GamepadHollowEvalEvent,
) -> None:
    _load(event, '特殊区域代号播报')
    assert event.identify_entry() == '盲盒区域'
    assert event.try_respond() is not None
    event.last_screenshot_time += 1
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')
    area = event._read_event_panel()
    assert area is not None
    for text in list(area[1]):
        if '0018' in text:
            area[1][text.replace('0018', '0099')] = area[1].pop(text)
    assert event.try_respond() is not None
    assert [call.args[0] for call in event.ctx.controller.btn_tap.call_args_list] == ['south', 'south']


def test_special_zone_exit_only_confirms_the_known_continue_option(event: GamepadHollowEvalEvent) -> None:
    _load(event, '离开特殊区域')
    assert event.identify_entry() == '不宜久留'
    assert event.try_respond() is not None
    event.last_screenshot_time += 1
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')


def test_house_options_match_live_alias_and_original_reward_order(event: GamepadHollowEvalEvent) -> None:
    _load(event, '坍塌的房屋')
    assert event.identify_entry() == '房屋残骸'
    assert event.try_respond() is not None
    event.last_screenshot_time += 1
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('dpad_down')


def test_house_uses_the_verified_row_when_preferred_reward_is_unreadable(
    event: GamepadHollowEvalEvent,
) -> None:
    _load(event, '坍塌的房屋')
    area = event._read_event_panel()
    assert area is not None
    area[1].pop('获得1400齿轮硬币')
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')


def test_house_narrative_uses_inline_continue_once(event: GamepadHollowEvalEvent) -> None:
    _load(event, '坍塌房屋结果')
    assert event.try_respond() is not None
    event.last_screenshot_time += 1
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('south')


def test_station_moves_towards_verified_exit_even_with_changed_focused_effect(
    event: GamepadHollowEvalEvent,
) -> None:
    _load(event, '研究站默认焦点')
    assert event.identify_entry() == '怀斯塔学会研究站'
    assert event.try_respond() is not None
    event.last_screenshot_time += 1
    assert event.try_respond() is not None
    event.ctx.controller.btn_tap.assert_called_once_with('dpad_down')


@pytest.mark.parametrize('effect_visible', (True, False))
def test_treasure_only_moves_for_verified_timed_mission_decline(
    event: GamepadHollowEvalEvent, effect_visible: bool,
) -> None:
    _load(event, '邦布的秘宝')
    if not effect_visible:
        area = event._read_event_panel()
        assert area is not None
        area[1].pop('放弃限时任务')
    assert event.identify_entry() == ('限时战斗' if effect_visible else None)
    assert event.try_respond() is not None
    if effect_visible:
        event.ctx.controller.btn_tap.assert_called_once_with('dpad_down')
    else:
        event.ctx.controller.btn_tap.assert_not_called()
