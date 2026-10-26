"""电池合成准备阶段的真实截图验证，不连接游戏。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.ether_battery import GamepadPrepareEtherBattery


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


def test_synthesis_requires_obtained_evidence(monkeypatch) -> None:
    """返回合成页不等于获得；确认后须有获得1电池的证据。"""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from zzz_od.operation.gamepad.ether_battery import GamepadSynthesizeEtherBattery

    words = {'道具处理': [], '以太电池': [], '合成数量×1': []}
    ctx = SimpleNamespace(ocr=SimpleNamespace(run_ocr=lambda screen: words), run_context=Mock())
    plan, config = Mock(), Mock()
    op = GamepadSynthesizeEtherBattery(ctx, plan, config)
    op.last_screenshot = object()
    monkeypatch.setattr(op, '_after_round_wait', Mock())
    press = Mock(return_value=True)
    monkeypatch.setattr(op, '_press_highlighted', press)
    assert not op.synthesize().is_success
    press.assert_called_once_with(words, '合成')
    words.clear()
    words.update({'确认使用下列素材合成1个[以太电池]吗？': [], '确认': []})
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
