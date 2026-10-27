"""恶名狩猎迁移的关键判断，不连接游戏。"""

from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.notorious_hunt import (
    GamepadHuntPrepare,
    read_hunt_result,
)


def test_result_requires_hunt_objective() -> None:
    """通用结果标题本身不能证明通关；0/1 为失败。"""
    op = Mock()
    op.round_by_find_area.return_value.is_success = True
    from one_dragon.base.geometry.rectangle import Rect

    op.ctx.screen_loader.get_area.return_value.rect = Rect(80,660,630,725)
    for text, expected in [('完成恶名狩猎0/1', False), ('完成恶名狩猎1/1', True), ('通关时长不超过5分钟1/1', None)]:
        op.ctx.ocr.run_ocr.return_value = {text:[SimpleNamespace(center=SimpleNamespace(x=300,y=690))]}
        assert read_hunt_result(op) is expected
    op.round_by_find_area.return_value.is_success = False
    assert read_hunt_result(op) is None


def test_level_dropdown_ignores_duplicate_header(monkeypatch) -> None:
    """当前等级和下拉选项相同也只确认一次，不反复开关下拉框。"""
    from one_dragon.base.geometry.rectangle import Rect
    from zzz_od.operation.gamepad import notorious_hunt

    ctx = SimpleNamespace(controller=Mock(), run_context=Mock())
    op = GamepadHuntPrepare(ctx, SimpleNamespace(mission_type_name='库萨里库', level='最高可用等级'))
    op._after_round_wait = Mock()
    op.navigation._read_area = Mock(return_value=(None, {
        '等级Lv.65': [SimpleNamespace(rect=Rect(1590, 30, 1740, 70)), SimpleNamespace(rect=Rect(1630, 375, 1760, 420))],
        '等级Lv.30': [SimpleNamespace(rect=Rect(1630, 110, 1760, 150))],
    }))
    monkeypatch.setattr(notorious_hunt, 'has_filled_highlight', lambda image, rect, color: rect.center.y > 300)
    op.choose_level()
    ctx.controller.btn_tap.assert_called_once_with('south')


def test_mobile_boss_bar_positive_and_negative_frames() -> None:
    """同一模板覆盖两帧血条，进场和引导遮罩不会当作已接敌。"""
    from pathlib import Path

    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.base.screen.template_loader import TemplateLoader
    from one_dragon.utils import cv2_utils

    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    area = loader.get_area('恶名狩猎', '标识-BOSS血条')
    matcher = TemplateMatcher(TemplateLoader())
    root = Path(__file__).resolve().parents[3] / 'screens' / '恶名狩猎'
    for name, expected in [
        ('macos_hunt_after_upstream_move_1792985742996', True),
        ('macos_hunt_after_upstream_move_1792986889664', True),
        ('macos_hunt_scene_1792984681494', False),
        ('macos_hunt_after_upstream_move_1792985206921', False),
    ]:
        result = matcher.crop_and_match_template(
            cv2_utils.read_image(str(root / f'{name}.webp')), area.rect,
            area.template_sub_dir, area.template_id, threshold=area.template_match_threshold,
        )
        assert (result.max is not None) is expected


def test_failed_result_never_updates_plan(monkeypatch) -> None:
    """结算失败返回入口后立即失败，不获取配置或增加次数。"""
    from zzz_od.operation.gamepad import notorious_hunt

    ctx = SimpleNamespace(run_context=Mock())
    op = notorious_hunt.GamepadNotoriousHunt(ctx, Mock())
    op._after_round_wait = Mock()
    op._won = False
    exit_op = Mock()
    exit_op.execute.return_value = SimpleNamespace(success=True, data={'won': False, 'left_times': 3})
    monkeypatch.setattr(notorious_hunt, 'GamepadHuntResultExit', Mock(return_value=exit_op))
    assert op.finish().is_fail
    ctx.run_context.get_config.assert_not_called()


def test_period_rewards_gray_returns_without_claiming() -> None:
    """全领按钮明确置灰两帧后只按 B，避免重复消费领奖动作。"""
    from zzz_od.operation.gamepad.notorious_hunt_rewards import GamepadHuntRewards

    op = GamepadHuntRewards(SimpleNamespace(run_context=Mock(), controller=Mock()))
    op._after_round_wait = Mock()
    op._known_reward_visible = Mock(return_value=False)
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    op._yellow_text = Mock(return_value=False)
    op._has_text = Mock(return_value=True)
    op._save_evidence = Mock()
    op.claim()
    op.ctx.controller.btn_tap.assert_not_called()
    op.claim()
    op.ctx.controller.btn_tap.assert_called_once_with('east')


def test_application_keeps_failed_status_after_return(monkeypatch) -> None:
    """成功返回街区不能覆盖挑战或领奖失败。"""
    from zzz_od.application.notorious_hunt import notorious_hunt_app
    from zzz_od.operation.gamepad import notorious_hunt

    monkeypatch.setattr(notorious_hunt_app.sys, 'platform', 'darwin')
    app = object.__new__(notorious_hunt_app.NotoriousHuntApp)
    app.ctx = Mock()
    app._previous_node = None
    app._previous_round_result = SimpleNamespace(is_success=False, status='领奖未完成')
    app.round_fail = Mock(return_value='failed')
    back = Mock()
    back.execute.return_value = SimpleNamespace(success=True)
    monkeypatch.setattr(notorious_hunt, 'GamepadHuntBackToWorld', Mock(return_value=back))
    assert app.back_to_world() == 'failed'
    app.round_fail.assert_called_once_with('领奖未完成')
    app.round_fail.reset_mock()
    assert app.check_left_times() == 'failed'
    app.round_fail.assert_called_once_with('领奖未完成')


def test_macos_buff_uses_original_index_and_unique_card_focus(monkeypatch) -> None:
    """实拍三卡按原序号选第三张，确认后不重复 A。"""
    from pathlib import Path

    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.utils import cv2_utils
    from zzz_od.operation.gamepad import notorious_hunt

    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    ctx = SimpleNamespace(run_context=Mock(), controller=Mock(), screen_loader=loader,
                          macos_config=SimpleNamespace(menu_action_interval_ms=500))
    op = notorious_hunt.GamepadNotoriousHuntMove(ctx, 3)
    op._after_round_wait = Mock()
    op.save_screenshot = Mock()
    op._buff_parser.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    path = Path(__file__).resolve().parents[3] / 'screens' / '恶名狩猎' / 'ios_buff_three_cards.webp'
    op.last_screenshot = cv2_utils.read_image(str(path))
    names = op._buff_names()
    assert len(names) == 3
    op.choose_buff()
    target = names[2]
    monkeypatch.setattr(notorious_hunt, 'find_yellow_focus_frames', lambda *args: [
        Rect(target.x1 - 20, target.y1 - 200, target.x2 + 20, target.y2 + 200),
    ])
    op.choose_buff()
    op.choose_buff()
    assert [call.args[0] for call in ctx.controller.btn_tap.call_args_list] == ['dpad_right', 'south']
    ctx.controller.click.assert_not_called()


def test_macos_failed_buff_is_not_approach_success() -> None:
    """父流程的选择失败兜底不能把 Mac 的异常记成接敌成功。"""
    from zzz_od.operation.gamepad.notorious_hunt import GamepadNotoriousHuntMove

    op = Mock()
    op.previous_node.name = '选择'
    op.previous_node.is_success = False
    GamepadNotoriousHuntMove.move_done(op)
    op.round_fail.assert_called_once()
    op.round_success.assert_not_called()
