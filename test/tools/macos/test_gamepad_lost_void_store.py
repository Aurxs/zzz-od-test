"""商店只确认明确弹窗，交易必须有实际余额变化。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.application.hollow_zero.lost_void.context.lost_void_artifact import (
    LostVoidArtifact,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
    LostVoidArtifactPos,
)
from zzz_od.operation.gamepad.lost_void_store import (
    GamepadLostVoidBangbooStore,
    GamepadLostVoidStoreConfirm,
)


def currency_operation() -> GamepadLostVoidBangbooStore:
    from one_dragon.base.matcher.template_matcher import TemplateMatcher
    from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
    from one_dragon.base.screen.template_loader import TemplateLoader

    ctx = make_ctx()
    ctx.screen_loader = ProfileScreenContext(defer_missing_screens=True)
    ctx.screen_loader.reload()
    ctx.screen_loader.apply_profile_patches()
    ctx.tm = TemplateMatcher(TemplateLoader())
    op = GamepadLostVoidBangbooStore(ctx)
    op._after_round_wait = Mock()
    path = Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-邦布商店' / 'ios_gold_refresh_exhausted.webp'
    op.last_screenshot = cv2_utils.read_image(str(path))
    return op


def test_currency_after_refresh_exhausted_uses_goods_gold() -> None:
    op = currency_operation()
    assert not op.round_by_find_area(op.last_screenshot, '迷失之地-邦布商店', '标识-金币').is_success
    assert op._currency_flags() == (True, False)


@pytest.mark.parametrize('use_blood_icon', [False, True])
def test_currency_never_uses_wallet_gold_to_allow_unknown_goods(use_blood_icon: bool) -> None:
    op = currency_operation()
    blood = op.ctx.tm.template_loader.get_template('lost_void', 'blood_drop').raw
    for idx in range(1, 5):
        rect = op.ctx.screen_loader.get_area('迷失之地-邦布商店', f'手柄-商品金币-{idx}').rect
        op.last_screenshot[rect.y1:rect.y2, rect.x1:rect.x2] = 0
        if use_blood_icon:
            height, width = blood.shape[:2]
            op.last_screenshot[rect.y1:rect.y1 + height, rect.x1:rect.x1 + width] = blood
    assert op._currency_flags() == (False, False)


def test_currency_does_not_override_an_existing_blood_marker() -> None:
    op = GamepadLostVoidBangbooStore(make_ctx())
    op.last_screenshot = object()
    op.round_by_find_area = Mock(side_effect=[SimpleNamespace(is_success=False), SimpleNamespace(is_success=True)])
    assert op._currency_flags() == (False, True)
    assert op.round_by_find_area.call_count == 2


def make_ctx() -> SimpleNamespace:
    return SimpleNamespace(controller=Mock(), lost_void=SimpleNamespace(priority_updated=True))


@pytest.mark.parametrize('price_text',['× 1000','Q×1000','e×1000'])
def test_full_price_overrides_truncated_filtered_digits(price_text: str) -> None:
    ctx=make_ctx()
    price_area=SimpleNamespace(rect=Rect(90,735,1800,780),left_top=SimpleNamespace(x=90,y=735))
    buy_area=SimpleNamespace(rect=Rect(90,780,1800,840),left_top=SimpleNamespace(x=90,y=780))
    ctx.screen_loader=SimpleNamespace(get_area=Mock(side_effect=lambda screen,name:price_area if name=='区域-价格' else buy_area))
    operation=GamepadLostVoidBangbooStore(ctx)
    operation.last_screenshot=object()
    item=LostVoidArtifactPos(LostVoidArtifact('通用','拆弹器','A'),Rect(694,499,833,526))
    item.store_price=100
    operation.parser.get_artifact_pos=Mock(return_value=([item],[item]))
    def words(text: str,y: int) -> dict[str,MatchResultList]:
        matches=MatchResultList()
        matches.append(MatchResult(1,645,y,90,28))
        return {text:matches}
    operation.navigation._read_area=Mock(side_effect=lambda screen,name:(None,
        words(price_text,7) if name=='区域-价格' else words('购买',12)))
    all_goods,goods=operation._goods()
    assert all_goods==goods==[item]
    assert item.store_price==1000
    operation.navigation._read_area=Mock(side_effect=lambda screen,name:(None,
        {} if name=='区域-价格' else words('购买',12)))
    assert operation._goods()[1]==[]
    assert item.store_price is None


@pytest.mark.parametrize('text',['1600×1000','×1000×600','余额1000'])
def test_ambiguous_price_is_not_used(text: str) -> None:
    assert GamepadLostVoidBangbooStore.parse_price(text) is None


@pytest.mark.parametrize('balance, accepted', [(800, True), (750, False)])
def test_purchase_requires_exact_observed_cost(balance: int, accepted: bool) -> None:
    operation = GamepadLostVoidBangbooStore(make_ctx())
    operation._after_round_wait = Mock()
    operation._pending = '购买'
    operation._before_balance = 1000
    operation._cost = 200
    operation._balance = Mock(return_value=balance)
    operation.save_screenshot = Mock()
    result = operation._settle_pending(True)
    if not accepted:
        assert not result.is_fail
        result = operation._settle_pending(True)
    assert result.is_fail is not accepted
    assert (operation._pending is None) is accepted
    operation.ctx.controller.btn_tap.assert_not_called()


def test_balance_animation_waits_for_exact_cost_without_more_input() -> None:
    operation = GamepadLostVoidBangbooStore(make_ctx())
    operation._after_round_wait = Mock()
    operation._pending = '购买'
    operation._before_balance = 1000
    operation._cost = 200
    operation._balance = Mock(side_effect=[850, 800])
    assert not operation._settle_pending(True).is_fail
    assert operation._pending == '购买'
    assert not operation._settle_pending(True).is_fail
    assert operation._pending is None
    operation.ctx.controller.btn_tap.assert_not_called()


def test_unchanged_balance_never_repeats_purchase() -> None:
    operation = GamepadLostVoidBangbooStore(make_ctx())
    operation._after_round_wait = Mock()
    operation.save_screenshot = Mock()
    operation._pending = '购买'
    operation._before_balance = 1000
    operation._cost = 200
    operation._balance = Mock(return_value=1000)
    results = [operation._settle_pending(True) for _ in range(5)]
    assert results[-1].is_fail
    operation.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('prompt_visible', [False, True])
def test_purchase_modal_requires_a_prompt_and_confirms_once(prompt_visible: bool) -> None:
    operation = GamepadLostVoidStoreConfirm(make_ctx(), '购买')
    operation._after_round_wait = Mock()
    operation.save_screenshot = Mock()
    operation.last_screenshot = cv2_utils.read_image(str(
        Path(__file__).resolve().parents[3] / 'screens' / '迷失之地-邦布商店' / 'ios_purchase_confirm.webp',
    ))

    def words(*texts: str) -> dict[str, MatchResultList]:
        result = {}
        for text in texts:
            matches = MatchResultList()
            matches.append(MatchResult(1, 65, 8, 70, 30))
            result[text] = matches
        return result

    areas = {
        '手柄-购买正文': (None, words('是否确认购买此商品')),
        '按钮-购买-确认': (operation.last_screenshot[600:654, 1034:1230], words('确认')),
        '手柄-商店确认提示': (None, words('A', '选择') if prompt_visible else words('选择')),
    }
    operation.navigation._read_area = Mock(side_effect=lambda screen, area: areas[area])
    assert not operation.confirm().is_success
    assert not operation.confirm().is_success
    if prompt_visible:
        operation.ctx.controller.btn_tap.assert_called_once_with('south')
    else:
        operation.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('name','expected'), [('ios_purchase_confirm.webp','dpad_left'),('ios_purchase_cancel.webp','south')])
def test_unplanned_purchase_moves_to_cancel_without_accepting_default(name: str,expected: str) -> None:
    operation=GamepadLostVoidStoreConfirm(make_ctx(),'购买',accept=False)
    operation._after_round_wait=Mock()
    operation.save_screenshot=Mock()
    image=cv2_utils.read_image(str(Path(__file__).resolve().parents[3]/'screens'/'迷失之地-邦布商店'/name))
    operation.last_screenshot=image
    def words(items: list[tuple[str,int,int]]) -> dict[str,MatchResultList]:
        result={}
        for text,x,y in items:
            matches=MatchResultList()
            matches.append(MatchResult(1,x,y,70,30))
            result[text]=matches
        return result
    areas={
        '手柄-购买正文':(None,words([('是否确认购买此商品',0,0)])),
        '按钮-购买-确认':(image[600:654,1034:1230],words([('确认',65,8)])),
        '手柄-商店确认提示':(None,words([('A',0,0),('选择',40,0)])),
        '手柄-商店确认选项':(image[580:680,650:1270],words([('取消',150,35),('确认',450,35)])),
    }
    operation.navigation._read_area=Mock(side_effect=lambda screen,name:areas[name])
    assert not operation.confirm().is_success
    assert not operation.confirm().is_success
    operation.ctx.controller.btn_tap.assert_called_once_with(expected)


def test_store_cancels_unplanned_modal_before_reading_goods(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void_store as module
    ctx=make_ctx()
    ctx.lost_void.in_normal_world=Mock(return_value=False)
    operation=GamepadLostVoidBangbooStore(ctx)
    operation.last_screenshot=object()
    operation._after_round_wait=Mock()
    operation.check_and_update_current_screen=Mock(return_value=None)
    operation._goods=Mock()
    cancel=Mock()
    cancel.can_handle.return_value=True
    cancel.execute.return_value=SimpleNamespace(success=True)
    factory=Mock(return_value=cancel)
    monkeypatch.setattr(module,'GamepadLostVoidStoreConfirm',factory)
    assert not operation.buy().is_success
    factory.assert_called_once_with(ctx,'购买',accept=False)
    operation._goods.assert_not_called()
    assert operation._unplanned_cancel_count==1
    operation.ctx.controller.btn_tap.assert_not_called()
