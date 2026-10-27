"""情报板只覆盖零消耗、确认目标和真实计数的关键边界。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.application.intel_board.intel_board_app import CommissionType, IntelBoardApp
from zzz_od.operation.gamepad import intel_board


def context() -> SimpleNamespace:
    return SimpleNamespace(controller=Mock(), run_context=Mock())


@pytest.mark.parametrize('consumption,allowed', [('00', True), ('40', False), ('?', False)])
def test_next_requires_zero_consumption(consumption: str, allowed: bool) -> None:
    op = intel_board.GamepadIntelNextStep(context())
    op._after_round_wait = Mock()
    op._save_evidence = Mock()
    op._pending_evidence = Mock(side_effect=lambda *args: op.round_fail('未知'))
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    op._read_area = Mock(return_value=(None, {f'委托代行中ON电量消耗143/{consumption}下一步': []}))
    result = op.prepare()
    assert result.is_fail is not allowed
    if allowed:
        op.ctx.controller.btn_tap.assert_called_once_with('start')
    else:
        op.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('focused,key', [(False, 'dpad_right'), (True, 'south')])
def test_forward_never_confirms_abandon(monkeypatch, focused: bool, key: str) -> None:
    op = intel_board.GamepadAcceptIntelCommission(context())
    op._after_round_wait = Mock()
    op._has_text = Mock(return_value=False)
    words = {name: SimpleNamespace(max=SimpleNamespace(rect=Rect(x, 500, x + 100, 540)))
             for name, x in [('放弃委托', 300), ('前往', 600)]}
    op._read_area = Mock(return_value=(None, words))
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: focused)
    op.accept()
    op.ctx.controller.btn_tap.assert_called_once_with(key)


def test_result_requires_completed_objective() -> None:
    op = Mock()
    op.round_by_find_area.return_value.is_success = True
    op.ctx.screen_loader.get_area.return_value.rect = Rect(80, 660, 630, 725)
    for text, expected in [('完成专业挑战1/1', True), ('完成专业挑战室1/1', True), ('完成恶名狩猎0/1', False), ('通关时长1/1', None)]:
        op.ctx.ocr.run_ocr.return_value = {text: [SimpleNamespace(center=SimpleNamespace(x=300, y=690))]}
        assert intel_board.read_intel_result(op) is expected


@pytest.mark.parametrize('won,count', [(None, 0), (False, 0), (True, 1)])
def test_count_requires_victory_and_board(monkeypatch, won: bool | None, count: int) -> None:
    monkeypatch.setattr('zzz_od.application.intel_board.intel_board_app.sys.platform', 'darwin')
    app = object.__new__(IntelBoardApp)
    app.ctx = Mock()
    app.current_commission_type = CommissionType.EXPERT_CHALLENGE
    app._macos_battle_won = won
    app.run_record = SimpleNamespace(expert_challenge_count=0)
    app.last_screenshot = None
    app.round_by_ocr = Mock(return_value=SimpleNamespace(is_success=True))
    app.round_success = Mock()
    app.check_back_to_list()
    assert app.run_record.expert_challenge_count == count


@pytest.mark.parametrize('depth_off', [False, True])
def test_hunt_delegation_requires_depth_off(depth_off: bool) -> None:
    op = intel_board.GamepadIntelNextStep(context())
    op._after_round_wait = Mock()
    op._save_evidence = Mock()
    op._pending_evidence = Mock(side_effect=lambda *args: op.round_fail('未知'))
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    op._read_area = Mock(return_value=(None, {'委托代行中ON剩余奖励次数0/3无报酬模式': []}))
    op._has_text = Mock(return_value=depth_off)
    result = op.prepare()
    assert result.is_fail is not depth_off
    if depth_off:
        op.ctx.controller.btn_tap.assert_called_once_with('start')
    else:
        op.ctx.controller.btn_tap.assert_not_called()


def test_recorded_mobile_focus_and_progress_region() -> None:
    """实际截图的功能焦点及进度文字都落在平台配置区域内。"""
    import json
    from pathlib import Path

    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.utils import cv2_utils
    from zzz_od.operation.gamepad.transport import find_yellow_focus_frames

    root = Path(__file__).resolve().parents[3] / 'screens'
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    area = loader.get_area('功能导览', '手柄-卡片').rect
    frame = cv2_utils.read_image(str(root / '功能导览' / 'ios_gamepad.webp'))
    assert len(find_yellow_focus_frames(frame[area.y1:area.y2, area.x1:area.x2], 100, 175, 100, 180)) == 1
    data = json.loads((root / '情报板' / 'ios_ocr.json').read_text())['ios_list']
    word = next(item for item in data['ocr_texts'] if item['text'] == '周期内可获取')
    region = loader.get_area('情报板', '手柄-列表标识').rect
    assert region.x1 <= word['x'] and word['x'] + word['width'] <= region.x2
    assert region.y1 <= word['y'] and word['y'] + word['height'] <= region.y2


@pytest.mark.parametrize('title,yellow,pressed', [(False, True, False), (True, False, False), (True, True, True)])
def test_reward_confirmation_requires_known_title_and_focus(monkeypatch, title: bool, yellow: bool, pressed: bool) -> None:
    op = intel_board.GamepadIntelSettlement(context())
    op._after_round_wait = Mock()
    op._save_evidence = Mock()
    op._has_text = Mock(return_value=False)
    op.node_retry_times = 0
    op._read_area = Mock(return_value=(None, {'确认': SimpleNamespace(max=SimpleNamespace(rect=Rect(80, 20, 150, 55)))}))
    op.round_by_find_area = Mock(side_effect=lambda screen, name, area: SimpleNamespace(is_success=title and area == '手柄-代行奖励标题'))
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: yellow)
    op.finish()
    assert op.ctx.controller.btn_tap.called is pressed
    if pressed:
        op.ctx.controller.btn_tap.assert_called_once_with('south')


def test_deploy_accepts_interaction_hud_without_pressing_deploy_again() -> None:
    """鸣徽入口使用交互按钮，也属于已加载场景。"""
    ctx = context()
    ctx.auto_battle_context = Mock()
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    op = intel_board.GamepadIntelDeploy(ctx)
    op._after_round_wait = Mock()
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    assert op.deploy().is_success
    ctx.controller.btn_tap.assert_not_called()


def test_exit_unknown_page_and_repeated_frame_send_no_input() -> None:
    op = intel_board.GamepadIntelBackToWorld(context())
    op._after_round_wait = Mock()
    op.last_screenshot = Mock()
    op.last_screenshot_time = 1
    op._has_text = Mock(return_value=False)
    op._save_evidence = Mock()
    op._pending_evidence = Mock(side_effect=lambda *args: op.round_fail('未知'))
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    assert op.back().is_fail
    op.ctx.controller.btn_tap.assert_not_called()
    op.round_by_find_area = Mock(side_effect=lambda screen, name, area: SimpleNamespace(is_success=area == '返回'))
    op.back()
    op.back()
    op.ctx.controller.btn_tap.assert_called_once_with('east')


def test_configured_team_uses_existing_macos_selector(monkeypatch) -> None:
    from zzz_od.operation.gamepad import predefined_team

    app = object.__new__(IntelBoardApp)
    app.ctx = Mock()
    app.config = SimpleNamespace(predefined_team_idx=5)
    app.round_by_op_result = Mock()
    selector = Mock()
    monkeypatch.setattr(predefined_team, 'GamepadChoosePredefinedTeam', selector)
    app.choose_predefined_team()
    selector.assert_called_once_with(app.ctx, 5)
