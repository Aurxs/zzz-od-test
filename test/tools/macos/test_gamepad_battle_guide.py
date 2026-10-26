"""共用引导只在确认页码后输入，不依赖具体 Boss。"""

from unittest.mock import Mock

from zzz_od.operation.gamepad.battle_guide import GamepadBattleGuide


def test_optional_guide_pages_and_reset() -> None:
    """缺席不输入，多页逐页翻阅，最后一页才返回。"""
    op = Mock()
    guide = GamepadBattleGuide()
    op.round_by_find_area.return_value.is_success = False
    assert guide.handle(op) is None
    op.ctx.controller.btn_press.assert_not_called()
    op.round_by_find_area.return_value.is_success = True
    for page in ('01/04', '02/04', '03/04', '04/04'):
        op.ctx.ocr.crop_and_run_ocr.return_value = {page: []}
        guide.handle(op)
    assert [call.args[0] for call in op.ctx.controller.btn_press.call_args_list] == [
        'dpad_right', 'dpad_right', 'dpad_right', 'east',
    ]
    op.round_by_find_area.return_value.is_success = False
    assert guide.handle(op) is None


def test_unknown_page_and_stuck_page_stop() -> None:
    """页码未知不按 B，卡页最多尝试三次。"""
    op = Mock()
    op.round_by_find_area.return_value.is_success = True
    guide = GamepadBattleGuide()
    op.ctx.ocr.crop_and_run_ocr.return_value = {'乱码': []}
    for _ in range(3):
        guide.handle(op)
    op.ctx.controller.btn_press.assert_not_called()
    op.round_fail.assert_called_once()
    op.ctx.ocr.crop_and_run_ocr.return_value = {'01/02': []}
    for _ in range(4):
        guide.handle(op)
    assert op.ctx.controller.btn_press.call_count == 3
    assert op.round_fail.call_count == 2
