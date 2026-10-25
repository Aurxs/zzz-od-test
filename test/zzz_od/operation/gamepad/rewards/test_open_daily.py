"""回放已归档手册画面，验证领奖入口不依赖初始标签。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.rewards import (
    GamepadEngagementReward,
    GamepadOpenDailyCompendium,
    GamepadOpenRiduWeekly,
)

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '快捷手册'
TABS = Rect(700, 115, 1645, 205)
AREAS = {
    ('快捷手册', '手柄-顶部标签'): TABS,
    ('快捷手册-日常', '手柄-周纪入口'): Rect(350, 375, 800, 920),
    ('快捷手册-日常', '手柄-领奖提示'): Rect(700, 970, 1230, 1060),
    ('道具处理-获得', '标题-获得'): Rect(860, 386, 1060, 460),
    ('道具处理-获得', '手柄-奖励确认'): Rect(800, 680, 1120, 775),
    ('道具处理-获得', '手柄-奖励选择提示'): Rect(1000, 785, 1110, 840),
    ('丽都周纪', '手柄-页面文字'): Rect(0, 0, 1920, 1080),
}


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadOpenDailyCompendium:
    """用真实图像的颜色及快照文字框替代真实输入和 OCR 初始化。"""
    monkeypatch.setattr(GamepadOpenDailyCompendium, '_after_round_wait', Mock())
    ctx = SimpleNamespace(
        controller=Mock(spec=['click', 'btn_tap']),
        screen_loader=SimpleNamespace(get_area=lambda screen, area: SimpleNamespace(rect=AREAS[(screen, area)])),
        ocr=Mock(),
        run_context=Mock(),
        current_instance_idx=2,
    )
    return GamepadOpenDailyCompendium(ctx)


def set_frame(
    operation: GamepadOpenDailyCompendium | GamepadOpenRiduWeekly | GamepadEngagementReward,
    state: str,
) -> None:
    """按区域裁出归档的真实 OCR 框。"""
    metadata = json.loads((SCREENS / 'ios_gamepad_ocr.json').read_text(encoding='utf-8'))
    cropped = json.loads((SCREENS / 'ios_rewards_crop_ocr.json').read_text(encoding='utf-8'))
    def crop_ocr(image: np.ndarray, rect: Rect) -> dict[str, MatchResultList]:
        """同一份 OCR 快照根据请求区域返回相对坐标。"""
        results: dict[str, MatchResultList] = {}
        crop = next((area for area in cropped.get(state, {}).values() if area['rect'] == [rect.x1, rect.y1, rect.x2, rect.y2]), None)
        if crop is not None:
            for item in crop['items']:
                matches = MatchResultList()
                matches.append(MatchResult(1, item['x'], item['y'], item['width'], item['height']))
                results[item['text']] = matches
            return results
        for item in metadata.get(state, []):
            x, y, width, height = (int(item[key]) for key in ('x', 'y', 'width', 'height'))
            if rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2:
                matches = MatchResultList()
                matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
                results[str(item['text'])] = matches
        return results

    operation.ctx.ocr.crop_and_run_ocr.side_effect = crop_ocr
    directory = SCREENS.parent / '卦象集录' if state == 'ios_reward' else SCREENS
    operation.last_screenshot = cv2_utils.read_image(str(directory / f'{state}.webp'))
    assert operation.last_screenshot is not None


def test_choose_daily_uses_real_highlight_and_waits_for_new_frame(
    operation: GamepadOpenDailyCompendium,
) -> None:
    """训练页按 LB，确认日常高亮后结束；不触发任何领奖键。"""
    set_frame(operation, 'ios_training_default')
    assert operation.open_compendium().is_success
    assert operation.selected_tab() == '训练'
    assert not operation.choose_daily().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('left_shoulder')
    set_frame(operation, 'ios_daily')
    assert operation.choose_daily().is_success
    assert operation.choose_daily().status == '已打开快捷手册日常'
    operation.ctx.controller.btn_tap.assert_called_once_with('left_shoulder')
    operation.ctx.controller.click.assert_not_called()


def test_open_only_once_from_confirmed_world(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """等待手册期间不会反复开关，重新执行才重置记录。"""
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.ctx.ocr.crop_and_run_ocr.return_value = {}
    monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_success()))
    assert not operation.open_compendium().is_success
    assert not operation.open_compendium().is_success
    operation.ctx.controller.click.assert_called_once_with(gamepad_key='compendium')
    operation.handle_init()
    assert not operation.open_compendium().is_success
    assert operation.ctx.controller.click.call_count == 2


def test_unknown_page_and_missing_highlight_send_no_input(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标签文字仍存在但黄色填充消失时不能猜方向。"""
    set_frame(operation, 'ios_daily')
    operation.last_screenshot[TABS.y1:TABS.y2, TABS.x1:TABS.x2] = 0
    monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_retry()))
    assert operation.selected_tab() is None
    assert not operation.choose_daily().is_success
    assert not operation.open_compendium().is_success
    operation.last_screenshot = None
    assert not operation.open_compendium().is_success
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.controller.click.assert_not_called()


def test_weekly_entry_requires_real_focus_and_does_not_repeat_confirm(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """日常实拍左卡有黄色焦点才允许 A，空白不能算周纪到达。"""
    monkeypatch.setattr(GamepadOpenRiduWeekly, '_after_round_wait', Mock())
    weekly = GamepadOpenRiduWeekly(operation.ctx)
    set_frame(weekly, 'ios_daily')
    assert weekly.weekly_focused()
    assert not weekly.enter_weekly().is_success
    assert not weekly.enter_weekly().is_success
    weekly.ctx.controller.btn_tap.assert_called_once_with('south')
    weekly.last_screenshot[:] = 0
    weekly.ctx.ocr.crop_and_run_ocr.side_effect = None
    weekly.ctx.ocr.crop_and_run_ocr.return_value = {}
    assert not weekly.enter_weekly().is_success
    weekly.handle_init()
    assert not weekly.weekly_focused()
    assert not weekly.enter_weekly().is_success
    weekly.ctx.controller.btn_tap.assert_called_once_with('south')


def test_engagement_claims_once_then_saves_pending_unknown_result(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实日常可领提示只发送一次 X，未知奖励页保留现场并退出。"""
    monkeypatch.setattr(GamepadEngagementReward, '_after_round_wait', Mock())
    engagement = GamepadEngagementReward(operation.ctx)
    engagement.ctx.run_context.is_context_running = True
    save = Mock(side_effect=lambda prefix: prefix)
    monkeypatch.setattr(engagement, 'save_screenshot', save)
    set_frame(engagement, 'ios_daily')
    assert engagement.claim_available()
    assert engagement.claim_rewards().is_success
    assert engagement.claim_rewards().is_success
    engagement.ctx.controller.btn_tap.assert_called_once_with('west')
    assert 'engagement_before' in engagement.evidence_paths
    assert engagement.evidence_paths['engagement_before'].endswith('/.debug/images/macos_rewards_engagement_before.png')
    result = engagement.confirm_reward()
    assert '未知活跃度奖励画面' in result.status
    assert result.is_fail
    assert result.data['pending']
    assert 'engagement_after_claim' in engagement.evidence_paths
    assert 'engagement_unknown_result' in engagement.evidence_paths
    engagement.ctx.run_context.switch_context_pause_and_run.assert_not_called()
    # 即使外部再次检查同一结果，也不能再发送领取键或盲按 B。
    engagement.confirm_reward()
    engagement.ctx.controller.btn_tap.assert_called_once_with('west')
    assert save.call_count == 3


def test_engagement_known_reward_page_recovers_without_claiming(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已建档的遗留奖励页直接去确认，不把前次或人工领取算作本次行为。"""
    monkeypatch.setattr(GamepadEngagementReward, '_after_round_wait', Mock())
    engagement = GamepadEngagementReward(operation.ctx, resume_from_reward=True)
    monkeypatch.setattr(engagement, 'save_screenshot', Mock(return_value='recovered'))
    set_frame(engagement, 'ios_reward')
    result = engagement.check_initial_reward()
    assert result.status == '恢复奖励结果'
    assert engagement._recovered_result
    assert engagement._claim_sent
    engagement.ctx.controller.btn_tap.assert_not_called()


def test_common_reward_requires_own_claim_and_confirms_only_once(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通用获得页实拍的 A 提示在确认下方，必须有组件自己的领取记录。"""
    monkeypatch.setattr(GamepadEngagementReward, '_after_round_wait', Mock())
    engagement = GamepadEngagementReward(operation.ctx)
    monkeypatch.setattr(engagement, 'save_screenshot', Mock(side_effect=lambda prefix: prefix))
    set_frame(engagement, 'ios_reward')
    assert engagement._known_reward_visible()
    assert engagement.reward_confirmation_key() is None
    assert engagement.check_initial_reward().data['pending']
    engagement.ctx.controller.btn_tap.assert_not_called()
    engagement._claim_sent = True
    assert engagement.reward_confirmation_key() == 'south'
    assert not engagement.confirm_reward().is_success
    assert not engagement.confirm_reward().is_success
    assert 'engagement_before_confirm' in engagement.evidence_paths
    engagement.ctx.controller.btn_tap.assert_called_once_with('south')


def test_engagement_disabled_claim_keeps_incomplete_result_without_input(
    operation: GamepadOpenDailyCompendium,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保留提示文字，只去掉启用颜色；不能按固定 400 数字判断满档。"""
    monkeypatch.setattr(GamepadEngagementReward, '_after_round_wait', Mock())
    engagement = GamepadEngagementReward(operation.ctx)
    monkeypatch.setattr(engagement, 'save_screenshot', Mock(return_value='/tmp/before.png'))
    monkeypatch.setattr(engagement, '_reward_complete', Mock(return_value=False))
    set_frame(engagement, 'ios_daily')
    engagement.last_screenshot[985:1050, 900:1065] = 120
    assert not engagement.claim_available()
    assert engagement.claim_rewards().status == '无可领取奖励'
    assert not engagement._full_engagement
    assert '活跃度未满' in engagement._result_status
    engagement.ctx.controller.btn_tap.assert_not_called()
