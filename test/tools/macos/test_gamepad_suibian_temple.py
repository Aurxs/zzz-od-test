"""随便观只覆盖本轮托管分支的关键资源与状态边界。"""

from types import SimpleNamespace
from unittest.mock import Mock

from zzz_od.operation.gamepad.suibian_temple import (
    GamepadTempleAutoManage,
    validate_macos_temple_config,
)


def operation() -> GamepadTempleAutoManage:
    ctx = SimpleNamespace(controller=Mock(), run_context=Mock(), ocr=Mock())
    op = GamepadTempleAutoManage(ctx)
    op._after_round_wait = Mock()
    op._save_evidence = Mock(return_value='/tmp/evidence.png')
    op._pending_evidence = Mock(side_effect=lambda *args: op.round_fail('待条件'))
    op.last_screenshot = Mock()
    op.last_screenshot_time = 1
    return op


def test_config_rejects_manual_and_purchases_without_mutation() -> None:
    cfg = SimpleNamespace(auto_manage_enabled=True, good_goods_purchase_enabled=False, boo_box_purchase_enabled=False)
    assert validate_macos_temple_config(cfg) is None
    cfg.auto_manage_enabled = False
    assert validate_macos_temple_config(cfg)
    assert cfg.auto_manage_enabled is False
    cfg.auto_manage_enabled = True
    cfg.good_goods_purchase_enabled = True
    assert validate_macos_temple_config(cfg)
    assert cfg.good_goods_purchase_enabled is True


def test_completed_claim_is_sent_once_then_known_reward_confirmed() -> None:
    op = operation()
    op.ctx.ocr.run_ocr.return_value = {'经营日志自动托管已完成领取收益': []}
    op.manage()
    op.last_screenshot_time = 2
    op.manage()
    op.ctx.controller.btn_tap.assert_called_once_with('west')
    op.ctx.ocr.run_ocr.return_value = {'获得奖励云纹徽确认': []}
    op.last_screenshot_time = 3
    op.manage()
    op.last_screenshot_time = 4
    op.manage()
    assert [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list] == ['west', 'south']
    assert op.claimed


def test_unrelated_reward_is_rejected_and_running_hosting_is_preserved() -> None:
    op = operation()
    op.ctx.ocr.run_ocr.return_value = {'获得奖励云纹徽确认': []}
    assert op.manage().is_fail
    op.ctx.controller.btn_tap.assert_not_called()
    op.ctx.ocr.run_ocr.return_value = {'经营日志自动托管停止托管': []}
    result = op.manage()
    assert result.is_success and result.data['pending_completion']
    op.ctx.controller.btn_tap.assert_not_called()
    op.ctx.ocr.run_ocr.return_value = {'邻里街坊自动托管中可关闭自动托管进行手动操作': []}
    result = op.manage()
    assert result.is_success and result.data['pending_completion']
    op.ctx.controller.btn_tap.assert_not_called()


def test_started_state_requires_running_marker() -> None:
    op = operation()
    op.ctx.ocr.run_ocr.return_value = {'经营日志自动托管开始托管': []}
    op.manage()
    op.ctx.controller.btn_tap.assert_called_once_with('west')
    op.ctx.ocr.run_ocr.return_value = {'经营日志自动托管停止托管剩余19时59分': []}
    op.last_screenshot_time = 2
    result = op.manage()
    assert result.is_success and result.data['claimed'] is False
