"""咖啡只确认确实显示电量、获得标题和黄色确认的奖励。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from one_dragon.base.geometry.rectangle import Rect
from zzz_od.application.coffee.coffee_app import CoffeeApp


def test_energy_reward_title_in_separate_crop(monkeypatch):
    from zzz_od.application.coffee import coffee_app

    op = object.__new__(CoffeeApp)
    op.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    title, main = Rect(860, 386, 1060, 460), Rect(760, 365, 1160, 850)
    loader = Mock()
    loader.get_area.side_effect = lambda screen, name: SimpleNamespace(rect=title if name == '标题-获得' else main)
    confirm = SimpleNamespace(max=SimpleNamespace(rect=Rect(50, 300, 150, 340)))
    ocr = Mock()
    ocr.crop_and_run_ocr.side_effect = lambda image, rect: {'获得': []} if rect is title else {'电量': [], '确认': confirm}
    op.ctx = SimpleNamespace(screen_loader=loader, ocr=ocr)
    monkeypatch.setattr(coffee_app, 'has_filled_highlight', lambda *args: True)
    assert op._macos_energy_reward_visible()
    ocr.crop_and_run_ocr.side_effect = lambda image, rect: {'其他': []} if rect is title else {'电量': [], '确认': confirm}
    assert not op._macos_energy_reward_visible()
    ocr.crop_and_run_ocr.side_effect = lambda image, rect: {'获得': []} if rect is title else {'其他': [], '确认': confirm}
    assert not op._macos_energy_reward_visible()
    ocr.crop_and_run_ocr.side_effect = lambda image, rect: {'获得': []} if rect is title else {'电量': [], '确认': confirm}
    monkeypatch.setattr(coffee_app, 'has_filled_highlight', lambda *args: False)
    assert not op._macos_energy_reward_visible()


def test_explicit_tinman_only_excludes_extra_coffees():
    """显式单杯模式不能选择额外咖啡或重复选择已点的特调。"""
    op = object.__new__(CoffeeApp)
    op.ctx = SimpleNamespace(macos_tinman_only=True, compendium_service=Mock())
    op.had_coffee_list = set()
    assert op._get_coffee_to_choose() == ['汀曼特调']
    op.had_coffee_list.add('汀曼特调')
    assert op._get_coffee_to_choose() == []
    op.ctx.compendium_service.get_extra_coffee_list.assert_not_called()
