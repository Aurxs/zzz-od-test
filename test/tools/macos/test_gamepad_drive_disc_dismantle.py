"""驱动盘拆解只按确认过的页面和条件发手柄键。"""

from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from zzz_od.operation.gamepad.drive_disc_dismantle import (
    GamepadDriveDiscDismantle,
    QuickDiscSelection,
)


@pytest.fixture
def op() -> GamepadDriveDiscDismantle:
    ctx = SimpleNamespace(controller=Mock())
    operation = GamepadDriveDiscDismantle(ctx, 'A及以下', False)
    operation._after_round_wait = Mock()
    operation._pending_evidence = Mock(side_effect=lambda stage, reason: operation.round_fail(reason))
    operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    operation.last_screenshot_time = 1
    return operation


def test_storage_does_not_send_dismantle_key_on_wengine_page(op: GamepadDriveDiscDismantle) -> None:
    op._quantity = Mock(side_effect=lambda _screen, _area, name: (725, 2000) if name == '音擎仓库' else None)
    op._labels = Mock(return_value={'RB', '拆解'})

    op.enter_dismantle()
    op.last_screenshot_time += 1
    op.enter_dismantle()

    op.ctx.controller.btn_tap.assert_called_once_with('right_shoulder')


def test_quick_selection_needs_button_hint_and_single_focus(op: GamepadDriveDiscDismantle) -> None:
    image = np.zeros((640, 749, 3), dtype=np.uint8)
    cv2.rectangle(image, (381, 293), (710, 343), (210, 198, 18), 3)
    cv2.rectangle(image, (386, 298), (705, 338), (31, 143, 249), -1)
    matches = {
        '快速选择': [(20, 20, 120, 30)],
        '在已弃置的驱动盘中选择：': [(52, 150, 200, 20)],
        '在未弃置的驱动盘中选择：': [(52, 253, 200, 20)],
        '全选已弃置': [(158, 204, 100, 20)],
        'B': [(195, 308, 20, 20), (411, 600, 20, 20)],
        'A及以下': [(503, 305, 80, 24)],
        'S及以下': [(170, 363, 65, 20)],
        '符合以上条件的驱动盘数量：': [(249, 425, 238, 24)],
        '0': [(485, 426, 18, 20)],
        'x': [(408, 493, 25, 24)],
        'X': [(685, 5, 44, 45)],
        '确认': [(512, 491, 60, 25)],
        'A': [(272, 600, 24, 20)],
        '选择': [(314, 600, 40, 20)],
        '返回': [(446, 600, 40, 20)],
    }
    words: dict[str, MatchResultList] = {}
    for text, rects in matches.items():
        items = MatchResultList(only_best=False)
        for rect in rects:
            items.append(MatchResult(1, *rect))
        words[text] = items
    op._read_area = Mock(return_value=(image, words))

    assert op._quick_selection() == QuickDiscSelection('A及以下', frozenset({'A及以下'}), 0)
    prompt = words.pop('x')
    assert op._quick_selection() is None
    words['x'] = prompt
    cv2.rectangle(image, (42, 293), (369, 343), (210, 198, 18), 3)
    assert op._quick_selection() is None


def test_zero_matches_closes_the_filter_without_applying(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    op._quick_selection = Mock(return_value=QuickDiscSelection('A及以下', frozenset({'A及以下'}), 0))

    assert op.choose_discs().is_success
    assert op._expected == 0
    op.ctx.controller.btn_tap.assert_called_once_with('east')


def test_inherited_options_must_match_user_configuration(op: GamepadDriveDiscDismantle) -> None:
    op._quick_selection = Mock(
        return_value=QuickDiscSelection('全选已弃置', frozenset({'A及以下', '全选已弃置'}), 8),
    )

    assert not op.choose_discs().is_success
    op.last_screenshot_time += 1
    assert not op.choose_discs().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('south')


def test_lock_rule_requires_both_conditions_and_same_capacity(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    words = dict.fromkeys((
        '驱动拆解说明', '[拆解条件]', '驱动盘在满足以下条件时可以被拆解:',
        '1. 驱动盘未被装备', '2. 驱动盘未被标记为[锁定]状态',
        '处于[锁定]状态的驱动盘不可直接拆解，如需拆解需要取消[锁定]状态。',
        '每次最多可以选择300个驱动盘',
    ))
    op._read_area = Mock(return_value=(op.last_screenshot, words))
    op._has_prompt = Mock(return_value=True)

    assert op._lock_rule_visible()
    op._limit = 200
    assert not op._lock_rule_visible()
    op._limit = 300
    del words['2. 驱动盘未被标记为[锁定]状态']
    assert not op._lock_rule_visible()


def test_positive_selection_uses_native_cap_and_opens_lock_rules(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    op._quick_selection = Mock(return_value=QuickDiscSelection('A及以下', frozenset({'A及以下'}), 324))
    op._save_evidence = Mock(return_value='筛选截图')

    assert op.choose_discs().is_success
    assert op._expected == 300
    op._save_evidence.assert_called_once_with('disc_quick_nonempty')

    op._selected_quantity = Mock(return_value=(300, 300))
    op._equipped_hidden = Mock(return_value=True)
    op._labels = Mock(return_value={'LT'})
    op._lock_rule_visible = Mock(return_value=False)
    op.last_screenshot_time += 1
    assert not op.check_selected().is_success
    op.last_screenshot_time += 1
    assert not op.check_selected().is_success
    assert [call.args[0] for call in op.ctx.controller.btn_tap.call_args_list] == ['west', 'left_trigger']


def test_dismantle_action_requires_rule_count_and_saved_evidence(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    op._expected = 3
    op._before = 20
    op._selected_quantity = Mock(return_value=(3, 300))
    op._equipped_hidden = Mock(return_value=True)
    op._is_dismantle_enabled = Mock(return_value=True)
    op._save_evidence = Mock(return_value='')

    assert not op.open_dismantle_confirmation().is_success
    op._sent.add('关闭拆解说明')
    op._selected_quantity.return_value = (4, 300)
    assert not op.open_dismantle_confirmation().is_success
    op._selected_quantity.return_value = (3, 300)
    assert op.open_dismantle_confirmation().is_fail
    op.ctx.controller.btn_tap.assert_not_called()

    op._save_evidence.return_value = '截图路径'
    assert op.open_dismantle_confirmation().is_success
    op.last_screenshot_time += 1
    assert op.open_dismantle_confirmation().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('start')


def test_a_confirmation_requires_correct_rarity_focused_button_and_gamepad_prompt(
    op: GamepadDriveDiscDismantle,
) -> None:
    image = np.full((50, 100, 3), (244, 225, 50), dtype=np.uint8)
    confirm = MatchResultList()
    confirm.append(MatchResult(1, 22, 11, 57, 35))
    op._labels = Mock(return_value={'选中的驱动盘稀有度包含A级，', '确认要分解吗？'})
    op._read_area = Mock(return_value=(image, {'确认': confirm}))
    op._has_prompt = Mock(return_value=True)

    assert op._is_a_dismantle_confirmation()
    image[:] = 17
    assert not op._is_a_dismantle_confirmation()
    image[:] = (244, 225, 50)
    op._has_prompt.return_value = False
    assert not op._is_a_dismantle_confirmation()
    op._has_prompt.return_value = True
    op._labels.return_value = {'选中的驱动盘稀有度包含S级，', '确认要分解吗？'}
    assert not op._is_a_dismantle_confirmation()


def test_dismantle_confirmation_never_repeats_input(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    op._selected_quantity = Mock(return_value=(5, 300))
    op._is_dismantle_receipt = Mock(return_value=False)
    op._is_a_dismantle_confirmation = Mock(return_value=True)
    op._save_evidence = Mock(return_value='确认截图')

    assert not op.inspect_dismantle_confirmation().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    op._sent.add('打开拆解确认')
    assert op.inspect_dismantle_confirmation().is_success
    op.last_screenshot_time += 1
    assert op.inspect_dismantle_confirmation().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('south')


def test_dismantle_receipt_closes_once_and_requires_zero_selection(op: GamepadDriveDiscDismantle) -> None:
    op._limit = 300
    op._sent.add('打开拆解确认')
    op._is_dismantle_receipt = Mock(return_value=True)
    op._selected_quantity = Mock(return_value=(5, 300))
    op._equipped_hidden = Mock(return_value=True)
    op._save_evidence = Mock(return_value='获得截图')

    assert not op.check_dismantle_result().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    op.last_screenshot_time += 1
    assert not op.check_dismantle_result().is_success
    op.last_screenshot_time += 1
    assert not op.check_dismantle_result().is_success
    op._is_dismantle_receipt.return_value = False
    assert not op.check_dismantle_result().is_success
    op._selected_quantity.return_value = (0, 300)
    assert op.check_dismantle_result().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('south')


def test_dismantle_receipt_rejects_fade_and_checks_mother_disc_quantity(op: GamepadDriveDiscDismantle) -> None:
    body = np.zeros((300, 300, 3), dtype=np.uint8)
    body[30:65, 100:160] = 220
    button = np.full((50, 100, 3), (244, 225, 50), dtype=np.uint8)
    op._expected = 5
    op._has_prompt = Mock(return_value=True)
    areas = {
        '手柄-拆解获得正文': (body, {
            '获得': [MatchResult(1, 100, 30, 60, 35)],
            '5': [MatchResult(1, 85, 215, 15, 20)],
            '降噪处理母盘': [MatchResult(1, 45, 245, 95, 20)],
            '10': [MatchResult(1, 223, 216, 26, 20)],
            '塑化镀剂': [MatchResult(1, 200, 245, 71, 20)],
        }),
        '手柄-拆解获得确认': (button, {'确认': [MatchResult(1, 22, 11, 57, 35)]}),
        '手柄-拆解获得选择提示': (body, {}),
    }
    op._read_area = Mock(side_effect=lambda _screen, name: areas[name])

    assert op._is_dismantle_receipt()
    op._expected = 10
    assert not op._is_dismantle_receipt()
    op._expected = 5
    body[30:65, 100:160] = 165
    assert not op._is_dismantle_receipt()


def test_resume_requires_receipt_and_does_not_open_storage(op: GamepadDriveDiscDismantle) -> None:
    op.resume_receipt = (5, 300)
    op.warehouse.execute = Mock()
    op._is_dismantle_receipt = Mock(return_value=False)
    op._selected_quantity = Mock(return_value=(0, 300))
    op._equipped_hidden = Mock(return_value=True)

    assert op.open_warehouse().status == '续接拆解获得'
    op.warehouse.execute.assert_not_called()
    assert not op.check_dismantle_result().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_inventory_delta_must_match_expected_dismantle(op: GamepadDriveDiscDismantle) -> None:
    op._expected = 2
    op._before = 100
    op._limit = 300
    op._sent.add('退出拆解')
    op._selected_quantity = Mock(return_value=None)
    op._quantity = Mock(return_value=(97, 3000))

    assert op.leave_storage().is_fail
    op.ctx.controller.btn_tap.assert_not_called()
