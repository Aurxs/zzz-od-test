"""商店只确认明确弹窗，交易必须有实际余额变化。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.lost_void_store import (
    GamepadLostVoidBangbooStore,
    GamepadLostVoidStoreConfirm,
)


def make_ctx() -> SimpleNamespace:
    return SimpleNamespace(controller=Mock(), lost_void=SimpleNamespace(priority_updated=True))


@pytest.mark.parametrize('balance, accepted', [(800, True), (750, False)])
def test_purchase_requires_exact_observed_cost(balance: int, accepted: bool) -> None:
    operation = GamepadLostVoidBangbooStore(make_ctx())
    operation._after_round_wait = Mock()
    operation._pending = '购买'
    operation._before_balance = 1000
    operation._cost = 200
    operation._balance = Mock(return_value=balance)
    result = operation._settle_pending(True)
    assert result.is_fail is not accepted
    assert (operation._pending is None) is accepted
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
