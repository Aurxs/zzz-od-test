"""电池合成准备阶段的真实截图验证，不连接游戏。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.ether_battery import (
    GamepadCloseEtherBattery,
    GamepadPrepareEtherBattery,
    GamepadSynthesizeEtherBattery,
    ether_synthesis_materials,
)

SCREENS = Path(__file__).resolve().parents[3] / 'screens/道具处理'


def synthesis_words(state: str) -> dict[str, MatchResultList]:
    """回放完整OCR框，保留顶部与底部两个同名合成按钮。"""
    metadata = json.loads((SCREENS / 'ios_battery_synthesis_ocr.json').read_text())
    words: dict[str, MatchResultList] = {}
    for item in metadata[state]:
        words.setdefault(item['text'], MatchResultList(only_best=False)).append(
            MatchResult(1, item['x'], item['y'], item['w'], item['h']),
        )
    return words


@pytest.mark.parametrize('state', ['insufficient', 'source'])
def test_battery_preparation_never_synthesizes(state: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """素材不足只报告，来源页只进入合成，均不能直接确认消耗。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    assert ocr.init_model()
    ctx = SimpleNamespace(ocr=ocr, controller=Mock(spec=['btn_tap']), run_context=Mock())
    op = GamepadPrepareEtherBattery(ctx)
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock(return_value='battery_evidence'))
    path = Path(__file__).resolve().parents[3] / f'screens/道具处理/ios_battery_{state}.webp'
    op.last_screenshot = cv2_utils.read_image(str(path))
    try:
        result = op.enter_synthesis()
        if state == 'insufficient':
            assert result.is_success
            assert result.status == '合成素材不足'
            assert result.data['quantity'] == 1
            assert result.data['material_insufficient'] is True
            ctx.controller.btn_tap.assert_not_called()
        else:
            assert not result.is_success
            ctx.controller.btn_tap.assert_called_once_with('south')
            assert op._entered
    finally:
        ocr.cleanup()


def test_synthesis_requires_obtained_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回合成页不等于获得；确认后须有获得1电池的证据。"""
    words = synthesis_words('panel')
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda screen: words), run_context=Mock(), controller=Mock())
    plan, config = Mock(), Mock()
    op = GamepadSynthesizeEtherBattery(ctx, plan, config)
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_ready_panel.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    assert not op.synthesize().is_success
    assert op._requested
    ctx.controller.btn_tap.assert_called_once_with('south')
    op.synthesize()
    ctx.controller.btn_tap.assert_called_once_with('south')
    words = synthesis_words('confirm')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_confirm_single.webp'))
    assert not op.synthesize().is_success
    assert op._confirmed
    words.clear()
    words.update({'道具处理': [], '以太电池': [], '合成数量×1': []})
    assert not op.synthesize().is_success
    assert not op._obtained
    words.clear()
    words.update({'获得': [], '以太电池': [], '1': [], '确认': []})
    assert not op.synthesize().is_success
    assert op._obtained
    config.add_plan_run_times.assert_called_once_with(plan)
    assert not op.synthesize().is_success
    config.add_plan_run_times.assert_called_once_with(plan)
    words.clear()
    words.update({'道具处理': [], '以太电池': []})
    assert op.synthesize().is_success


def test_list_selection_does_not_mark_synthesis_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """左侧选卡只进入右面板，重复同帧既不连按也不误记请求。"""
    words = synthesis_words('list')
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_ready_list.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    assert not op.synthesize().is_success
    assert op._item_selected and not op._requested
    op.synthesize()
    ctx.controller.btn_tap.assert_called_once_with('south')


@pytest.mark.parametrize(('old', 'new'), [
    ('6/1', '0/1'), ('71/60', '59/60'), ('9460981/100', '99/100'),
    ('合成数量×1', '合成数量×2'), ('以太电池×15', '其他道具×15'),
])
def test_synthesis_does_not_request_with_wrong_item_quantity_or_material(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str,
) -> None:
    words = synthesis_words('panel')
    words[new] = words.pop(old)
    assert ether_synthesis_materials(words) is None
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_ready_panel.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    assert not op.synthesize().is_success
    assert not op._requested
    ctx.controller.btn_tap.assert_not_called()


def test_synthesis_requires_a_prompt_on_same_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """页脚的绿色A不能代替右下合成按钮的同排提示。"""
    words = synthesis_words('panel')
    words['A'] = synthesis_words('list')['A']
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_ready_panel.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    op.synthesize()
    assert not op._requested
    ctx.controller.btn_tap.assert_not_called()


def test_confirmation_rejects_changed_recipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """二次确认的储值电卡不是1时，不能沿用准备页读数消费。"""
    words = synthesis_words('confirm')
    words['2'] = words.pop('1')
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op._requested = True
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_confirm_single.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    assert op.synthesize().is_fail
    assert not op._confirmed
    ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('missing', ['电量', '储值电卡', '丁尼', '60', '1', '100'])
def test_confirmation_transition_waits_for_complete_materials(
    monkeypatch: pytest.MonkeyPatch, missing: str,
) -> None:
    """标题先出现而材料仍在过渡时只等，完整新帧可继续同一笔确认。"""
    words = synthesis_words('confirm')
    words.pop(missing)
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op._requested = True
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_confirm_single.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    result = op.synthesize()
    assert not result.is_fail and not result.is_success
    assert not op._confirmed
    ctx.controller.btn_tap.assert_not_called()
    words = synthesis_words('confirm')
    assert not op.synthesize().is_fail
    assert op._confirmed
    ctx.controller.btn_tap.assert_called_once_with('south')


def test_actual_synthesis_balance_counts_once_without_immediate_obtained_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实前后帧核对+1/-1/-60/-100，延迟获得页不再累计。"""
    words = synthesis_words('before')
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    plan, config = Mock(), Mock()
    op = GamepadSynthesizeEtherBattery(ctx, plan, config)
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_before_synthesis.webp'))
    op.synthesize()
    assert op._materials_before == {'inventory': 15, 'ticket': 6, 'charge': 73, 'denny': 9490981}
    words = synthesis_words('confirm')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_confirm_single.webp'))
    op.synthesize()
    assert op._confirmed
    words = synthesis_words('after')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_after_synthesis.webp'))
    assert op.synthesize().is_success
    assert op._materials_after == {'inventory': 16, 'ticket': 5, 'charge': 13, 'denny': 9490881}
    config.add_plan_run_times.assert_called_once_with(plan)
    assert op.synthesize().is_success
    config.add_plan_run_times.assert_called_once_with(plan)
    words = synthesis_words('obtained')
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_obtained_late.webp'))
    op.synthesize()
    config.add_plan_run_times.assert_called_once_with(plan)


@pytest.mark.parametrize(('field', 'value', 'elapsed', 'valid'), [
    ('charge', 13, 20, True), ('charge', 14, 20, True),
    ('charge', 15, 20, False), ('charge', 12, 20, False), ('charge', 14, 360, False),
    ('inventory', 15, 20, False), ('inventory', 17, 20, False),
    ('ticket', 6, 20, False), ('ticket', 4, 20, False),
    ('denny', 9490981, 20, False), ('denny', 9490880, 20, False),
])
def test_synthesis_requires_all_four_exact_balance_changes(
    monkeypatch: pytest.MonkeyPatch, field: str, value: int, elapsed: int, valid: bool,
) -> None:
    """不能仅凭库存增加计数，回电容差限于本笔六分钟以内的一次。"""
    from zzz_od.operation.gamepad import ether_battery

    ctx = SimpleNamespace(run_context=Mock())
    op = GamepadSynthesizeEtherBattery(ctx, Mock(), Mock())
    op._materials_before = {'inventory': 15, 'ticket': 6, 'charge': 73, 'denny': 9490981}
    op._requested_at = 1000
    monkeypatch.setattr(ether_battery.time, 'monotonic', lambda: 1000 + elapsed)
    after = {'inventory': 16, 'ticket': 5, 'charge': 13, 'denny': 9490881, field: value}
    assert op._balance_matches_synthesis(after) == valid


@pytest.mark.parametrize('allowed', [False, True])
def test_delayed_obtained_receipt_only_closes_after_verified_synthesis(
    monkeypatch: pytest.MonkeyPatch, allowed: bool,
) -> None:
    """已核账返回才可关闭单枚回执，重复帧不连按，也不再写计数。"""
    words = synthesis_words('obtained')
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda _: words), run_context=Mock(), controller=Mock())
    op = GamepadCloseEtherBattery(ctx, allow_obtained_receipt=allowed)
    op.last_screenshot = cv2_utils.read_image(str(SCREENS / 'ios_battery_obtained_late.webp'))
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    monkeypatch.setattr(op, 'save_screenshot', Mock())
    op.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=True))
    assert not op.close().is_success
    assert not op.close().is_success
    assert ctx.controller.btn_tap.call_count == int(allowed)
    words = {}
    assert op.close().is_success
    ctx.run_context.get_config.assert_not_called()
