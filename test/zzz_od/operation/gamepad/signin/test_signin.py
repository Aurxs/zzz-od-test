"""回放阿朔主界面与零进度实拍，不发送真实输入或领取奖励。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.signin import GamepadDailySignIn
from zzz_od.operation.zzz_operation import ZOperation

SCREENS = Path(__file__).resolve().parents[5] / 'screens' / '卦象集录'
AREAS: dict[str, tuple[Rect, str | None]] = {
    '手柄-标题': (Rect(1300, 915, 1620, 985), '卦象集录'),
    '手柄-占卜提示': (Rect(1290, 910, 1640, 1045), '占卜'),
    '手柄-摇杆提示': (Rect(800, 910, 1120, 975), '拨动右摇杆以获取卦象'),
    '手柄-占卜进度': (Rect(900, 960, 1040, 1015), None),
    '手柄-奖励标题': (Rect(900, 390, 1020, 450), '获得'),
    '手柄-奖励选择提示': (Rect(1000, 785, 1110, 840), '选择'),
    '手柄-奖励确认': (Rect(800, 680, 1120, 775), None),
    '手柄-结果确认': (Rect(975, 930, 1290, 1000), '确认'),
    '手柄-结果解卦': (Rect(630, 930, 945, 1000), '解卦'),
    '手柄-娱乐说明': (Rect(750, 1000, 1165, 1060), '算卦占卜只作娱乐'),
    '手柄-可占卜封面': (Rect(1340, 345, 1580, 575), None),
    '手柄-已完成封面': (Rect(1340, 345, 1580, 575), None),
}


class FrameOcr:
    """把实拍 OCR 快照按实际请求区域回放。"""

    def __init__(self) -> None:
        """起始为空，避免把缺失截图视为已知页面。"""
        self.state: str = ''
        self.metadata: dict = json.loads(
            (SCREENS / 'ios_gamepad_ocr.json').read_text(encoding='utf-8')
        )

    def crop_and_run_ocr(self, image: object, rect: Rect) -> dict[str, MatchResultList]:
        """返回局部坐标，保留进度原文。"""
        result: dict[str, MatchResultList] = {}
        for item in self.metadata.get(self.state, []):
            x, y, width, height = (item[key] for key in ('x', 'y', 'width', 'height'))
            if rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2:
                matches = result.setdefault(item['text'], MatchResultList())
                matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
        return result


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadDailySignIn:
    """使用严格假控制器，截图保存用文件名替身隔离写盘。"""
    monkeypatch.setattr(GamepadDailySignIn, '_after_round_wait', Mock())
    loader = Mock()
    loader.get_area.side_effect = lambda screen, area: SimpleNamespace(rect=AREAS[area][0])
    ctx = SimpleNamespace(
        controller=Mock(spec=['btn_tap', 'btn_press', 'btn_release', 'interact']),
        screen_loader=loader, ocr=FrameOcr(), run_context=Mock(),
        tm=TemplateMatcher(TemplateLoader()),
    )
    ctx.run_context.is_context_stop = False
    ctx.run_context.is_context_pause = False
    op = GamepadDailySignIn(ctx, 'trigrams_collection')
    monkeypatch.setattr(op, 'save_screenshot', Mock(return_value='saved_signin_evidence'))

    def find_area(screen: object, screen_name: str, area_name: str) -> object:
        """按实际区域的原文识别，不伪造尚未出现的奖励页。"""
        if screen_name == '大世界-普通':
            return op.round_success() if ctx.ocr.state == 'world' else op.round_retry()
        rect, text = AREAS[area_name]
        if area_name in ('手柄-可占卜封面', '手柄-已完成封面'):
            template = 'main_open' if area_name == '手柄-可占卜封面' else 'main_closed'
            matches = ctx.tm.crop_and_match_template(screen, rect, 'ios_trigrams', template, threshold=0.9)
            return op.round_success() if matches.max is not None else op.round_retry()
        results = ctx.ocr.crop_and_run_ocr(screen, rect)
        return op.round_success() if any(text in word for word in results) else op.round_retry()

    monkeypatch.setattr(op, 'round_by_find_area', find_area)
    return op


def set_frame(operation: GamepadDailySignIn, state: str) -> None:
    """新帧同时更新图像、OCR 状态与时间。"""
    operation.ctx.ocr.state = state
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    operation.last_screenshot_time += 1
    assert operation.last_screenshot is not None


def test_divination_can_resume_zero_progress_and_waits_for_new_frame(
    operation: GamepadDailySignIn,
) -> None:
    """从零进度恢复，一帧只旋转三秒，方向按圆周顺序且每段都释放。"""
    set_frame(operation, 'ios_divine_zero')
    assert operation.check_config().is_success
    assert operation.check_entry().status == operation.STATUS_AT_TRIGRAMS
    assert operation._progress() == 0
    assert not operation.collect().is_success
    assert not operation.collect().is_success
    directions = ['right_stick_right', 'right_stick_down', 'right_stick_left', 'right_stick_up'] * 3
    assert operation.ctx.controller.btn_press.call_args_list == [
        call(key, press_time=0.25) for key in directions
    ]
    assert sum(item.kwargs['press_time'] for item in operation.ctx.controller.btn_press.call_args_list) == 3.0
    assert operation.ctx.controller.mock_calls == [
        action for key in directions
        for action in (call.btn_press(key, press_time=0.25), call.btn_release(key))
    ]
    set_frame(operation, 'ios_divine_zero')
    assert not operation.collect().is_success
    assert operation.ctx.controller.btn_press.call_args_list == [
        call(key, press_time=0.25) for key in directions * 2
    ]
    assert operation._rotation_rounds == 2 and operation._active_gesture_key is None
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.controller.interact.assert_not_called()
    assert Path(operation.evidence['progress_0']).is_absolute()


def test_main_starts_once_and_unknown_result_stops_with_evidence(
    operation: GamepadDailySignIn,
) -> None:
    """主界面 A 占卜只发一次，未建档结果不确认也不宣布成功。"""
    set_frame(operation, 'ios_main')
    assert operation.check_entry().status == operation.STATUS_AT_TRIGRAMS
    assert not operation.collect().is_success
    assert not operation.collect().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    operation.ctx.ocr.state = ''
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for _ in range(3):
        assert not operation.collect().is_fail
    result = operation.collect()
    assert result.is_fail and '未发送确认' in result.status
    assert 'result_pending' in result.data['evidence']
    operation.ctx.controller.btn_press.assert_not_called()


def test_stalled_progress_does_not_keep_shaking(
    operation: GamepadDailySignIn,
) -> None:
    """连续不增长有限退出，不因确认页出现较慢而无限转动。"""
    set_frame(operation, 'ios_divine_zero')
    for _ in range(3):
        set_frame(operation, 'ios_divine_zero')
        assert not operation.collect().is_fail
    set_frame(operation, 'ios_divine_zero')
    assert operation.collect().is_fail
    assert operation.ctx.controller.btn_press.call_count == 36
    assert operation.ctx.controller.btn_release.call_count == 36


def test_stable_prompt_allows_rotation_without_percentage(
    operation: GamepadDailySignIn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """常态摇杆提示足以开始三秒动作，不把动态百分数当页面门槛。"""
    set_frame(operation, 'ios_divine_zero')
    monkeypatch.setattr(operation, '_progress', lambda: None)
    assert not operation.collect().is_success
    assert operation.ctx.controller.btn_press.call_count == 12


def test_arrival_interacts_without_npc_name_position(
    operation: GamepadDailySignIn,
) -> None:
    """传送节点已确认到达，交互不依赖随镜头移动的姓名。"""
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    assert not operation.interact().is_success
    assert not operation.interact().is_success
    operation.ctx.controller.interact.assert_called_once_with(
        press=True, press_time=0.2, release=True,
    )
    set_frame(operation, 'ios_main')
    assert operation.interact().is_success


def test_result_can_be_confirmed_again_after_reward(
    operation: GamepadDailySignIn,
) -> None:
    """结果先出现、随后奖励覆盖，关闭奖励后还能再次确认结果。"""
    operation._gesture_count = 12
    for state in ('ios_trigram_result', 'ios_reward', 'ios_trigram_result'):
        set_frame(operation, state)
        assert not operation.collect().is_success
        assert not operation.collect().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('south')] * 3
    set_frame(operation, 'ios_main_completed')
    assert operation.collect().is_success


@pytest.mark.parametrize('stop_flag', ['is_context_pause', 'is_context_stop'])
def test_rotation_checks_pause_or_stop_between_segments(
    operation: GamepadDailySignIn, stop_flag: str,
) -> None:
    """一段完成后收到暂停或停止，不再发送后续方向且保持归零。"""
    def press(key: str, press_time: float) -> None:
        """第二段后模拟运行上下文接收停止或暂停请求。"""
        if operation.ctx.controller.btn_press.call_count == 2:
            setattr(operation.ctx.run_context, stop_flag, True)

    operation.ctx.controller.btn_press.side_effect = press
    set_frame(operation, 'ios_divine_zero')
    assert not operation.collect().is_fail
    assert operation.ctx.controller.btn_press.call_count == 2
    assert operation.ctx.controller.btn_release.call_args_list == [
        call('right_stick_right'), call('right_stick_down'),
    ]
    assert operation._rotation_rounds == 0 and operation._active_gesture_key is None


def test_rotation_press_exception_still_releases_current_direction(
    operation: GamepadDailySignIn,
) -> None:
    """按杆异常也必须尝试释放当前方向，不留下持续摇杆。"""
    operation.ctx.controller.btn_press.side_effect = RuntimeError('输入异常')
    set_frame(operation, 'ios_divine_zero')
    with pytest.raises(RuntimeError, match='输入异常'):
        operation.collect()
    operation.ctx.controller.btn_release.assert_called_once_with('right_stick_right')
    assert operation._active_gesture_key is None


@pytest.mark.parametrize('outcome', ['完成', '人工结束', '异常'])
def test_rotation_execute_exit_releases_pending_direction(
    operation: GamepadDailySignIn, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    """Operation 正常、停止或异常收尾均释放尚在保持的方向。"""
    operation._active_gesture_key = 'right_stick_up'
    result = OperationResult(outcome == '完成', outcome)
    delegate = Mock(return_value=result)
    if outcome == '异常':
        delegate.side_effect = RuntimeError('操作异常')
    monkeypatch.setattr(ZOperation, 'execute', delegate)
    if outcome == '异常':
        with pytest.raises(RuntimeError, match='操作异常'):
            operation.execute()
    else:
        assert operation.execute() is result
    operation.ctx.controller.btn_release.assert_called_once_with('right_stick_up')
    assert operation._active_gesture_key is None


def test_confirmed_reward_resume_confirms_once_and_returns_to_world(
    operation: GamepadDailySignIn,
) -> None:
    """已核实来源的奖励页可恢复，确认后要看到主界面与大世界才完成。"""
    operation.resume_from_reward = True
    set_frame(operation, 'ios_reward')
    assert operation._reward_visible()
    assert operation.check_entry().status == operation.STATUS_AT_TRIGRAMS
    assert not operation.collect().is_success
    assert not operation.collect().is_success
    set_frame(operation, 'ios_trigram_result')
    assert operation._result_visible()
    assert not operation.collect().is_success
    assert not operation.collect().is_success
    set_frame(operation, 'ios_main')
    assert operation.collect().is_success
    assert not operation.return_to_world().is_success
    assert not operation.return_to_world().is_success
    operation.ctx.ocr.state = 'world'
    operation.last_screenshot = cv2_utils.read_image(str(
        SCREENS.parent / '大世界-普通' / 'ios_ashuo_arrived.webp'
    ))
    result = operation.return_to_world()
    assert result.is_success and result.status == '奖励恢复确认完成'
    assert result.data['resumed_from_reward']
    assert not result.data['started_from_world'] and result.data['right_stick_segments'] == 0
    assert 'world_after' in result.data['evidence']
    assert operation.ctx.controller.btn_tap.call_args_list == [
        call('south'), call('south'), call('east'),
    ]
    operation.ctx.controller.btn_press.assert_not_called()


def test_unrelated_reward_or_missing_confirm_highlight_sends_nothing(
    operation: GamepadDailySignIn,
) -> None:
    """通用获得弹窗不能充当签到起点，也不能仅凭确认文字领取。"""
    set_frame(operation, 'ios_reward')
    assert operation.check_entry().is_fail
    assert operation.collect().is_fail
    operation.resume_from_reward = True
    operation.last_screenshot[680:775, 800:1120] = 0
    assert not operation._reward_visible()
    assert operation.collect().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()


def test_trigram_result_resume_confirms_once_and_unknown_main_stops(
    operation: GamepadDailySignIn,
) -> None:
    """明确恢复结果页只按 A，不触发解卦或分享，未知主界面保留现场。"""
    set_frame(operation, 'ios_trigram_result')
    assert operation.check_entry().is_fail
    operation.resume_from_reward = True
    assert operation.check_entry().status == operation.STATUS_AT_TRIGRAMS
    assert not operation.collect().is_success
    assert not operation.collect().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    operation.ctx.ocr.state = ''
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for _ in range(3):
        assert not operation.collect().is_fail
    result = operation.collect()
    assert result.is_fail
    assert result.data['resumed_from_reward'] and result.data['right_stick_segments'] == 0
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


@pytest.mark.parametrize('selected_sign', ['scratch_card', 'hou_hou_bakery'])
def test_other_signin_never_falls_back_to_trigrams(
    operation: GamepadDailySignIn, selected_sign: str,
) -> None:
    """保留三选一语义，未支持选择不改成另一种签到。"""
    operation.selected_sign = selected_sign
    assert operation.check_config().is_fail
    operation.ctx.controller.btn_tap.assert_not_called()
    operation.ctx.controller.btn_press.assert_not_called()
