"""仅在代行完成且周期上限的已知确认弹窗允许恢复。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.operation.gamepad.intel_board import intel_limit_popup_visible


def test_full_limit_message_and_yellow_confirmation_required(monkeypatch):
    from zzz_od.operation.gamepad import intel_board

    rect = Rect(0, 0, 100, 100)
    confirm = SimpleNamespace(max=SimpleNamespace(rect=Rect(20, 50, 80, 80)))
    words = {'代行委托完成': [], '贡献点数和站点信度已达周期可获取上限': [], '确认': confirm}
    ctx = SimpleNamespace(screen_loader=Mock(), ocr=Mock())
    ctx.screen_loader.get_area.return_value.rect = rect
    ctx.ocr.crop_and_run_ocr.return_value = words
    screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: True)
    assert intel_limit_popup_visible(ctx, screenshot)
    del words['贡献点数和站点信度已达周期可获取上限']
    assert not intel_limit_popup_visible(ctx, screenshot)
    words['贡献点数和站点信度已达周期可获取上限'] = []
    monkeypatch.setattr(intel_board, 'has_filled_highlight', lambda *args: False)
    assert not intel_limit_popup_visible(ctx, screenshot)
