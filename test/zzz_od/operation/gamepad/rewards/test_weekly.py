"""周纪的当前已领态及未来可领分支，不发送真实输入。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.rewards_weekly import GamepadRiduWeekly


def test_actual_weekly_no_reward_and_confirmed_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实裁图需读出七格 BINGO 和两格未完成，灰 X 不产生领取。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    if not ocr.is_file_existed():
        pytest.skip('仅使用本地已有 OCR 模型')
    assert ocr.init_model()
    try:
        loader = ProfileScreenContext()
        loader.reload()
        operation = GamepadRiduWeekly(SimpleNamespace(
            controller=Mock(spec=['click', 'btn_tap']), screen_loader=loader,
            ocr=ocr, tm=TemplateMatcher(TemplateLoader()),
            run_context=Mock(), current_instance_idx=2,
        ))
        monkeypatch.setattr(operation, '_after_round_wait', Mock())
        monkeypatch.setattr(operation, 'save_screenshot', Mock(side_effect=lambda prefix: prefix))
        screens = Path(__file__).resolve().parents[5] / 'screens'
        operation.last_screenshot = cv2_utils.read_image(str(
            screens / '丽都周纪/ios_weekly_claimable_progress_ocr.webp'
        ))
        completed, unfinished, claimable, unknown = operation.grid_state()
        assert claimable == [9]
        assert unknown == []
        assert set(completed + unfinished) == set(range(1, 9))
        operation.last_screenshot = cv2_utils.read_image(str(
            screens / '丽都周纪/macos_rewards_weekly_score_claimable_1792978815622.webp'
        ))
        assert operation.focused_task() == 1
        assert operation.grid_state() == ([], list(range(2, 10)), [1], [])
        assert not operation.claim_available()
        assert not operation.check_score_tasks().is_success
        assert not operation.check_score_tasks().is_success
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
        operation.last_screenshot = cv2_utils.read_image(str(
            screens / '丽都周纪/macos_rewards_weekly_score_unchanged_1792978961515.webp'
        ))
        assert operation.grid_state() == ([1], list(range(2, 10)), [], [])
        assert operation.check_score_tasks().is_success
        assert operation._claimed_tasks == [1]
        assert operation.claim_available()
        assert operation.claim_special_reward().is_success
        assert operation.ctx.controller.btn_tap.call_args_list == [call('south'), call('west')]
        operation.handle_init()
        operation.ctx.controller.reset_mock()
        operation.last_screenshot = cv2_utils.read_image(str(screens / '丽都周纪/ios_weekly_no_reward.webp'))
        assert operation.check_entry().status == '已在周纪'
        assert operation.grid_state() == ([1, 4, 5, 6, 7, 8, 9], [2, 3], [], [])
        assert operation.check_score_tasks().is_success
        assert not operation.claim_available()
        assert operation.claim_special_reward().status == '无可领取特赏'
        operation.ctx.controller.btn_tap.assert_not_called()
        assert not operation.back_to_world().is_success
        assert not operation.back_to_world().is_success
        operation.last_screenshot = cv2_utils.read_image(str(screens / '快捷手册/ios_daily_claimed.webp'))
        assert not operation.back_to_world().is_success
        assert not operation.back_to_world().is_success
        assert operation.ctx.controller.btn_tap.call_args_list == [call('east'), call('east')]
        monkeypatch.setattr(operation, 'round_by_find_area', Mock(return_value=operation.round_success()))
        result = operation.back_to_world()
        assert result.is_success
        assert not result.data['claimed_by_operation']
    finally:
        ocr.cleanup()


def test_unknown_task_and_prompt_remain_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知任务状态和缺失提示不能伪称当前无奖励。"""
    operation = GamepadRiduWeekly(SimpleNamespace(
        controller=Mock(spec=['click', 'btn_tap']), run_context=Mock(), current_instance_idx=2,
    ))
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr(operation, 'save_screenshot', Mock(side_effect=lambda prefix: prefix))
    monkeypatch.setattr(operation, '_weekly_visible', Mock(return_value=True))
    monkeypatch.setattr(operation, 'grid_state', Mock(return_value=([1, 4, 5, 6, 7, 8, 9], [3], [], [2])))
    result = operation.check_score_tasks()
    assert result.is_fail and result.data['pending']
    monkeypatch.setattr(operation, 'claim_available', Mock(return_value=False))
    monkeypatch.setattr(operation, '_has_text', Mock(return_value=False))
    result = operation.claim_special_reward()
    assert result.is_fail and result.data['pending']
    operation.ctx.controller.btn_tap.assert_not_called()
    # 仅验证已知 X 提示对应的状态机，不伪造未来未领取画面。
    monkeypatch.setattr(operation, 'claim_available', Mock(return_value=True))
    assert operation.claim_special_reward().is_success
    assert operation.claim_special_reward().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('west')
