"""实拍帧回放单次手柄挑战，不连接游戏或发送输入。"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon.utils import cv2_utils
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.gamepad.combat_simulation import GamepadCombatSimulation

ROOT = Path(__file__).resolve().parents[3]
SCREENS = ROOT / 'screens'
AREAS = {
    '手柄-预设列表': (Rect(90, 695, 1820, 890), None),
    '手柄-电量': (Rect(1460, 995, 1610, 1050), None),
    '手柄-挑战等级': (Rect(1340, 20, 1470, 80), '挑战等级'),
    '手柄-下一步': (Rect(1675, 995, 1800, 1050), '下一步'),
    '手柄-出战': (Rect(1690, 995, 1790, 1050), '出战'),
    '手柄-预备编队': (Rect(410, 995, 550, 1050), '预备编队'),
    '手柄-挑战结果': (Rect(700, 145, 1210, 300), '挑战结果'),
    '手柄-完成': (Rect(1660, 995, 1775, 1050), '完成'),
    '手柄-基础材料分类': (Rect(410, 595, 535, 650), '基础材料'),
    '手柄-代理人晋升分类': (Rect(645, 595, 790, 650), '代理人晋升'),
}


class FrameOcr:
    """文字框回放使用脱敏 OCR 快照，卡片边框读取实拍图。"""

    def __init__(self) -> None:
        """加载本次导航使用的少量状态。"""
        self.state: str = ''
        self.metadata: dict = json.loads(
            (SCREENS / '实战模拟室' / 'ios_gamepad_ocr.json').read_text(encoding='utf-8')
        )

    def crop_and_run_ocr(self, image: object, rect: Rect) -> dict[str, MatchResultList]:
        """将整屏快照转成请求区域的局部文字框。"""
        results: dict[str, MatchResultList] = {}
        for item in self.metadata[self.state]:
            x, y, width, height = (item[key] for key in ('x', 'y', 'width', 'height'))
            if not (rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2):
                continue
            matches = MatchResultList()
            matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
            results[item['text']] = matches
        return results


@pytest.fixture
def operation(monkeypatch: pytest.MonkeyPatch) -> GamepadCombatSimulation:
    """使用严格假控制器，并保留真实颜色识别与文字状态判断。"""
    monkeypatch.setattr(GamepadCombatSimulation, '_after_round_wait', Mock())
    controller = Mock(spec=[
        'btn_tap', 'begin_battle_input_scope', 'end_battle_input_scope',
        'battle_input_blocked', 'refresh_battle_input_scope', 'resume_input',
    ])
    controller.battle_input_blocked = False
    battle = Mock()
    battle.auto_op.auto_turn_interval = 0
    battle.last_check_end_result = None
    ctx = SimpleNamespace(
        controller=controller,
        auto_battle_context=battle,
        battle_assistant_config=SimpleNamespace(screenshot_interval=0.1),
        run_context=Mock(),
        current_instance_idx=2,
        screen_loader=Mock(),
        ocr=FrameOcr(),
    )
    ctx.run_context.get_config.return_value.plan_list = []
    ctx.screen_loader.get_area.side_effect = lambda screen, area: SimpleNamespace(rect=AREAS[area][0])
    op = GamepadCombatSimulation(ctx, ChargePlanItem(auto_battle_config='Mac全配队通用'))

    def find_area(screen: object, screen_name: str, area_name: str) -> object:
        """普通文字按对应局部快照匹配；大世界模板只在实拍大世界帧命中。"""
        if screen_name == '大世界-普通':
            return op.round_success() if ctx.ocr.state == 'ios_hia_world_return' else op.round_retry()
        rect, text = AREAS[area_name]
        results = ctx.ocr.crop_and_run_ocr(screen, rect)
        return op.round_success() if text in results else op.round_retry()

    monkeypatch.setattr(op, 'round_by_find_area', find_area)
    return op


def set_frame(operation: GamepadCombatSimulation, state: str) -> None:
    """切换实拍截图及其 OCR 状态。"""
    screen_name = '战斗画面' if state in ('ios_gamepad_combat', 'ios_simulation_result') else '实战模拟室'
    operation.ctx.ocr.state = state
    operation.last_screenshot = cv2_utils.read_image(str(SCREENS / screen_name / f'{state}.webp'))
    operation.last_screenshot_time = time.time()
    assert operation.last_screenshot is not None


def test_preparation_uses_actual_preset_and_sends_start_once(
    operation: GamepadCombatSimulation,
) -> None:
    """真实预设边框和电量通过后，预设与编队各只发一次 Start。"""
    assert operation.check_plan().is_success
    assert operation.prepare_auto_battle().is_success
    set_frame(operation, 'ios_simulation_preset')
    assert operation._survey_selected()
    assert operation._charge() == (400, 100)
    assert not operation.prepare_deployment().is_success
    assert not operation.prepare_deployment().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('start')]
    set_frame(operation, 'ios_deploy_ready')
    assert operation.prepare_deployment().status == operation.STATUS_DEPLOYMENT_READY
    assert operation.deploy().is_success
    assert operation.deploy().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('start'), call('start')]
    operation.ctx.auto_battle_context.start_auto_battle.assert_not_called()


def test_unsupported_quantity_and_insufficient_charge_send_nothing(
    operation: GamepadCombatSimulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拒绝未支持的卡片数，默认数量仍核对画面的实际一百电量。"""
    operation.plan.card_num = '1'
    assert operation.check_plan().is_fail
    operation.plan.card_num = '默认数量'
    set_frame(operation, 'ios_simulation_preset')
    monkeypatch.setattr(operation, '_charge', Mock(return_value=(99, 100)))
    assert operation.prepare_deployment().status == operation.STATUS_CHARGE_NOT_ENOUGH
    monkeypatch.setattr(operation, '_charge', Mock(return_value=(100, 20)))
    assert operation.prepare_deployment().is_fail
    operation.last_screenshot = None
    assert not operation.prepare_deployment().is_success
    operation.ctx.controller.btn_tap.assert_not_called()


def test_guard_keeps_scope_during_cutscene_and_finishes_only_once(
    operation: GamepadCombatSimulation,
) -> None:
    """HUD 过场只暂停，结算先停策略和保护，再发 B，逐帧退回大世界。"""
    history = Mock()
    history.attach_mock(operation.ctx.auto_battle_context.stop_auto_battle, 'stop')
    history.attach_mock(operation.ctx.controller.end_battle_input_scope, 'end')
    history.attach_mock(operation.ctx.controller.resume_input, 'menu')
    history.attach_mock(operation.ctx.controller.btn_tap, 'tap')
    set_frame(operation, 'ios_gamepad_combat')
    assert operation.start_auto_battle().is_success
    operation.ctx.controller.begin_battle_input_scope.assert_called_once()
    operation.ctx.controller.battle_input_blocked = True
    operation.ctx.controller.refresh_battle_input_scope.side_effect = [False, True]
    assert not operation.auto_battle().is_success
    operation.ctx.controller.end_battle_input_scope.assert_not_called()
    operation.ctx.auto_battle_context.resume_auto_battle.assert_not_called()
    assert not operation.auto_battle().is_success
    operation.ctx.auto_battle_context.resume_auto_battle.assert_called_once()
    operation.ctx.controller.end_battle_input_scope.assert_not_called()

    set_frame(operation, 'ios_simulation_result')
    assert operation.auto_battle().is_success
    assert operation.wait_for_result().is_success
    assert operation.record_battle().is_success
    assert operation.record_battle().is_success
    assert operation.plan.run_times == 1
    operation.config.add_plan_run_times.assert_not_called()
    assert operation.finish_result().is_success
    assert operation.finish_result().is_success
    calls = history.mock_calls
    assert calls.index(call.stop()) < calls.index(call.end()) < calls.index(call.menu()) < calls.index(call.tap('east'))
    assert operation.ctx.controller.btn_tap.call_args_list == [call('east')]

    set_frame(operation, 'ios_basic_preset_after_result')
    assert operation.wait_for_return().is_success
    assert not operation.back_to_world().is_success
    assert not operation.back_to_world().is_success
    set_frame(operation, 'ios_material_category')
    assert not operation.back_to_world().is_success
    assert not operation.back_to_world().is_success
    set_frame(operation, 'ios_hia_world_return')
    assert operation.back_to_world().is_success
    assert operation.ctx.controller.btn_tap.call_args_list == [call('east')] * 3


def test_cli_starts_once_on_main_thread_and_cleans_up_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工作线程失败也在主线程停止运行，等待期间继续处理 Cocoa 事件。"""
    path = ROOT.parent / 'tools' / 'macos' / 'run_combat_simulation.py'
    spec = importlib.util.spec_from_file_location('mac_simulation_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main_thread = threading.get_ident()
    observed: list[tuple[str, int]] = []
    pumped = threading.Event()

    def start() -> bool:
        """记录主线程绑定。"""
        observed.append(('start', threading.get_ident()))
        return True

    def stop() -> None:
        """记录主线程清理。"""
        observed.append(('stop', threading.get_ident()))

    def worker(ctx: object, plan: object, entry: str, prepare: bool) -> OperationResult:
        """等待一次事件处理后模拟操作异常。"""
        observed.append(('worker', threading.get_ident()))
        assert pumped.wait(2)
        raise RuntimeError('测试中的操作失败')

    def pump() -> None:
        """只处理假事件，不调用系统或游戏 API。"""
        assert threading.get_ident() == main_thread
        pumped.set()
        time.sleep(0.001)

    monkeypatch.setattr(module, 'run_single', worker)
    ctx = SimpleNamespace(run_context=SimpleNamespace(start_running=start, stop_running=stop))
    with pytest.raises(RuntimeError, match='测试中的操作失败'):
        module.run_session(ctx, ChargePlanItem(), 'world', False, pump)
    assert observed[0] == ('start', main_thread)
    assert observed[1][0] == 'worker' and observed[1][1] != main_thread
    assert observed[2] == ('stop', main_thread)
