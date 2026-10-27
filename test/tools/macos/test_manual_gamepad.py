"""手动手柄的所有权、松开和真实Qt映射保存检查，不连接设备。"""

from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from one_dragon.base.config.yaml_config import YamlConfig
from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunContext,
)
from zzz_od.config.game_config import GameConfig
from zzz_od.config.macos_config import MacOsConfig
from zzz_od.gui.view.setting.setting_gamepad_interface import SettingGamepadInterface
from zzz_od.macos.manual_gamepad import APP_ID, ManualGamepadSession


def make_context() -> SimpleNamespace:
    """初始化纯内存上下文，只有明确标为手动持有时允许输入。"""
    ctx = SimpleNamespace(
        ready_for_application=True, initialization_error=None, current_instance_idx=1,
        controller=Mock(), init_controller=Mock(), dispatch_event=Mock(),
        run_context=SimpleNamespace(
            is_context_stop=True, is_context_running=False, current_app_id=None,
            stop_running=Mock(), run_application_async=Mock(return_value=True),
        ),
    )
    ctx.manual_gamepad = ManualGamepadSession(ctx)
    return ctx


def activate(ctx: SimpleNamespace) -> None:
    """模拟原运行器已经进入手动应用。"""
    ctx.manual_gamepad.requested.set()
    ctx.manual_gamepad.ready.set()
    ctx.run_context.current_app_id = APP_ID
    ctx.run_context.is_context_running = True
    ctx.run_context.is_context_stop = False


def test_automatic_task_and_cancelled_start_cannot_send_input() -> None:
    """已有任务时拒绝接管；初始化期间撤回请求后也不能放行。"""
    ctx = make_context()
    ctx.run_context.is_context_stop = False
    ctx.run_context.current_app_id = 'charge_plan'
    with pytest.raises(RuntimeError, match='停止当前任务'):
        ctx.manual_gamepad.start()
    ctx.manual_gamepad.stop()
    ctx.run_context.stop_running.assert_not_called()
    ctx.run_context.is_context_stop = True
    ctx.manual_gamepad.start()
    ctx.manual_gamepad.stop()
    with pytest.raises(RuntimeError, match='停止当前任务'):
        ctx.manual_gamepad.start()
    ctx.manual_gamepad.ready.set()
    ctx.run_context.current_app_id = APP_ID
    ctx.run_context.is_context_running = True
    ctx.manual_gamepad.set_button('xbox_a', True)
    ctx.controller.btn_press.assert_not_called()


def test_async_initialization_failure_releases_pending_request() -> None:
    """调度future失败也清理连接中状态，允许用户再次启动。"""
    ctx = make_context()
    ctx.manual_gamepad.start()
    callback = ctx.run_context.run_application_async.call_args.kwargs['on_done']
    future = Future()
    future.set_exception(RuntimeError('无法采集'))
    callback(future)
    assert not ctx.manual_gamepad.requested.is_set()
    assert not ctx.manual_gamepad.pending.is_set()
    assert '无法采集' in ctx.manual_gamepad.last_status


def test_concurrent_start_does_not_reinitialize_controller() -> None:
    """初始化尚未完成时第二入口即被拒绝，只允许一个控制器持有者。"""
    entered, finish = Event(), Event()

    def initialize() -> bool:
        entered.set()
        return finish.wait(timeout=2)

    ctx = SimpleNamespace(controller=SimpleNamespace(init_before_context_run=Mock(side_effect=initialize)))
    rc = ApplicationRunContext(ctx)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(rc.start_running)
        try:
            assert entered.wait(timeout=2)
            assert rc.start_running() is False
        finally:
            finish.set()
        assert first.result(timeout=2) is True
    ctx.controller.init_before_context_run.assert_called_once()
    rc.after_app_shutdown()


@pytest.fixture
def page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[SettingGamepadInterface, SimpleNamespace]]:
    """真实配置适配器使用临时文件，所有输入由Mock接收。"""
    app = QApplication.instance() or QApplication([])

    def paths(config: YamlConfig) -> tuple[str, str, None]:
        path = str(tmp_path / f'{config.instance_idx}_{config.module_name}.yml')
        return path, path, None

    monkeypatch.setattr(YamlConfig, '_get_yaml_file_paths', paths)
    ctx = make_context()
    ctx.game_config, ctx.macos_config = GameConfig(1), MacOsConfig(1)
    ctx.game_config.data['background_gamepad_type'] = 'ds4'
    widget = SettingGamepadInterface(ctx)
    widget.on_interface_shown()
    for _ in range(3):
        app.processEvents()
    yield widget, ctx
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_show_mapping_and_account_switch_do_not_save_or_connect(
    page: tuple[SettingGamepadInterface, SimpleNamespace],
) -> None:
    """显示Xbox实际映射，不覆盖旧DS4；重复进入和切账户不自动保存或连接。"""
    widget, ctx = page
    ctx.init_controller.assert_not_called()
    ctx.controller.cleanup_after_app_shutdown.assert_not_called()
    assert ctx.game_config.background_gamepad_type == 'ds4'
    assert widget.key_cards['normal_attack'].combo_box.currentData() == ctx.game_config.xbox_key_normal_attack
    old = ctx.game_config
    ctx.game_config = GameConfig(2)
    ctx.macos_config = MacOsConfig(2)
    widget.on_interface_shown()
    for _ in range(3):
        QApplication.processEvents()
    card = widget.key_cards['normal_attack'].combo_box
    card.setCurrentIndex(card.findData('xbox_y'))
    assert GameConfig(2).xbox_key_normal_attack == 'xbox_y'
    assert old.xbox_key_normal_attack != 'xbox_y'
    ctx.init_controller.assert_called_once()


def test_buttons_sticks_focus_and_page_leave(
    page: tuple[SettingGamepadInterface, SimpleNamespace],
) -> None:
    """控件发送实际按下/释放，失焦归零、离页停止，运行时映射锁定。"""
    widget, ctx = page
    activate(ctx)
    widget.manual.refresh()
    widget._refresh_editable()
    assert not widget.mapping_group.isEnabled()
    assert not widget.service_group.isEnabled()
    button = widget.manual.buttons['xbox_a']
    button.pressed.emit()
    button.released.emit()
    ctx.controller.btn_press.assert_called_once_with('xbox_a')
    ctx.controller.btn_release.assert_called_once_with('xbox_a')
    ctx.manual_gamepad.set_action('compendium', True)
    ctx.manual_gamepad.set_action('compendium', False)
    assert [call.args[0] for call in ctx.controller.btn_press.call_args_list][-2:] == ['xbox_lt', 'xbox_a']
    assert [call.args[0] for call in ctx.controller.btn_release.call_args_list][-2:] == ['xbox_a', 'xbox_lt']
    stick = widget.manual.left_stick
    stick._move(QPointF(500, stick.height() / 2))
    ctx.controller.set_gamepad_stick.assert_called_with('left', 1.0, 0.0)
    widget.manual._application_state(Qt.ApplicationState.ApplicationInactive)
    assert stick.value == QPointF()
    ctx.controller.reset_input.assert_called_once()
    widget.on_interface_hidden()
    assert not ctx.manual_gamepad.requested.is_set()
    ctx.run_context.stop_running.assert_called_once()


def test_xbox_layout_and_stick_click_follow_visible_controls(
    page: tuple[SettingGamepadInterface, SimpleNamespace],
) -> None:
    """标准非对称位置与点击区域一起缩放，右键摇杆发送L3而不是方向。"""
    widget, ctx = page
    widget.resize(1000, 800)
    widget.show()
    QApplication.processEvents()
    activate(ctx)
    widget.manual.refresh()
    manual = widget.manual
    assert manual.left_stick.y() < manual.right_stick.y()
    assert manual.buttons['xbox_dpad_up'].y() > manual.left_stick.y()
    assert manual.buttons['xbox_y'].x() > manual.right_stick.x()
    assert manual.buttons['xbox_x'].x() < manual.buttons['xbox_b'].x()
    QTest.mousePress(manual.left_stick, Qt.MouseButton.RightButton)
    QTest.mouseRelease(manual.left_stick, Qt.MouseButton.RightButton)
    ctx.controller.btn_press.assert_called_once_with('xbox_l_thumb')
    ctx.controller.btn_release.assert_called_once_with('xbox_l_thumb')
    assert not manual.left_stick.click_held
    widget.resize(800, 800)
    QApplication.processEvents()
    for control, _, _, _ in manual.surface.placements:
        assert manual.surface.rect().contains(control.geometry())
