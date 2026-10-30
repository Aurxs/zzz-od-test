"""通过真实执行生命周期验证事件监听不会保留结束的指令和截图。"""

from __future__ import annotations

import gc
import logging
import weakref
from types import SimpleNamespace

import numpy as np
import pytest

from one_dragon.base.operation.context_event_bus import (
    ContextEventBus,
    ContextEventItem,
)
from one_dragon.base.operation.operation import Operation
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import OperationRoundResult


class ScreenshotOperation(Operation):
    """假节点仅生成一张截图，不接触窗口、模型或输入。"""

    def __init__(self, ctx: SimpleNamespace, outcome: str) -> None:
        super().__init__(ctx, op_name='事件清理检查', need_check_game_win=False)
        self.outcome: str = outcome

    def handle_init(self) -> None:
        """模拟业务订阅旧总线，并保留一张真实尺寸截图。"""
        self.ctx.listen_event('业务事件', self.on_business_event)
        self.last_screenshot = np.full((1080, 1920, 3), 17, dtype=np.uint8)
        if self.outcome == 'init_failure':
            raise RuntimeError('预期的初始化失败')

    def on_business_event(self, event: ContextEventItem) -> None:
        """只用于核对旧总线的业务监听也能正常清理。"""

    @operation_node(name='完成', is_start_node=True, screenshot_before_round=False)
    def finish(self) -> OperationRoundResult:
        """节点结束时运行总线和旧总线都应仍有当前对象的监听。"""
        assert sum(listener.__self__ is self
                   for listeners in self.ctx.run_context.event_bus.callbacks.values()
                   for listener in listeners) == 2
        assert self.ctx.legacy_bus.has_event_listener('业务事件')
        return self.round_fail('预期失败') if self.outcome == 'failure' else self.round_success()


class OtherListener:
    """模拟仍在运行的其他订阅者。"""

    def receive(self, event: ContextEventItem) -> None:
        """当前指令结束不应清除这个对象的事件。"""


@pytest.mark.parametrize('outcome', ['success', 'failure', 'init_failure'])
def test_finished_operations_release_listeners_and_screens(
    outcome: str, caplog: pytest.LogCaptureFixture,
) -> None:
    """成功、失败和初始化异常后，两个总线都不再持有指令或它的截图。"""
    if outcome == 'init_failure':
        # pytest的报告处理器会持有异常回溯，本例只检查事件总线的对象生命周期。
        caplog.set_level(logging.CRITICAL, logger='OneDragon')
    run_bus, legacy_bus = ContextEventBus(), ContextEventBus()
    other = OtherListener()
    run_bus.listen_event('其他运行事件', other.receive)
    legacy_bus.listen_event('其他业务事件', other.receive)
    ctx = SimpleNamespace(
        run_context=SimpleNamespace(event_bus=run_bus, is_context_stop=False,
                                    is_context_pause=False, notify_pool=None),
        listen_event=legacy_bus.listen_event, unlisten_all_event=legacy_bus.unlisten_all_event,
        legacy_bus=legacy_bus, debug_trace_bus=None,
        notify_config=SimpleNamespace(enable_notify=False),
    )
    operation_refs, frame_refs = [], []
    for _ in range(2):
        op = ScreenshotOperation(ctx, outcome)
        assert op.execute().success is (outcome == 'success')
        operation_refs.append(weakref.ref(op))
        frame_refs.append(weakref.ref(op.last_screenshot))
        del op
    gc.collect()
    assert sum(map(len, run_bus.callbacks.values())) == 1
    assert sum(map(len, legacy_bus.callbacks.values())) == 1
    assert run_bus.callbacks['其他运行事件'] == [other.receive]
    assert legacy_bus.callbacks['其他业务事件'] == [other.receive]
    assert all(reference() is None for reference in operation_refs)
    assert all(reference() is None for reference in frame_refs)
