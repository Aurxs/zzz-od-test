"""只构造普通 Qt 运行控件，验证 Mac 灰态与准备按钮，不构造 AppWindow。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from one_dragon.base.operation.application.application_group_config import (
    ApplicationGroupConfigItem,
)
from one_dragon.base.operation.operation_base import OperationResult
from one_dragon_qt.view import app_run_interface
from zzz_od.gui.view.one_dragon import zzz_one_dragon_run_interface
from zzz_od.gui.view.one_dragon.macos_game_preparation_runner import (
    MacGamePreparationRunner,
)
from zzz_od.gui.view.one_dragon.zzz_one_dragon_run_interface import (
    ZOneDragonRunInterface,
)
from zzz_od.macos import application_capabilities
from zzz_od.macos.application_capabilities import get_macos_app_unavailable_reason


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    """测试命令指定 offscreen，不操作本机游戏或窗口。"""
    return QApplication.instance() or QApplication([])


def test_original_task_list_keeps_order_and_settings_with_disabled_mac_run(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原列表完整保留，未适配按钮灰显，准备按钮不受任务限制影响。"""
    for module in (application_capabilities, zzz_one_dragon_run_interface, app_run_interface):
        monkeypatch.setattr(module, 'sys', SimpleNamespace(platform='darwin'))
    run_context = SimpleNamespace(
        is_context_stop=True, is_context_running=False, is_context_pause=False,
        run_status_text='空闲', get_run_record=Mock(return_value=None),
        default_group_apps=['charge_plan', 'email'],
    )
    context = SimpleNamespace(
        run_context=run_context, current_instance_idx=2,
        key_start_running='f9', key_stop_running='f10',
        notify_config=SimpleNamespace(app_map={}),
        get_application_unavailable_reason=get_macos_app_unavailable_reason,
    )
    tasks = [ApplicationGroupConfigItem('email', True), ApplicationGroupConfigItem('charge_plan', True)]
    tasks[0].app_name = '邮件'
    tasks[1].app_name = '体力计划'
    page = ZOneDragonRunInterface(context)
    page._init_layout()
    page.config = SimpleNamespace(app_list=tasks)
    page._init_app_list()
    page.on_context_state_changed()

    unsupported, supported = page.app_run_list._app_cards
    assert [card.app.app_id for card in page.app_run_list._app_cards] == ['email', 'charge_plan']
    assert not unsupported.run_btn.isEnabled()
    assert 'Mac暂未适配' in unsupported.content_widget.titleLabel.text()
    assert unsupported.setting_btn.isEnabled()
    assert unsupported.switch_btn.isEnabled()  # 用户仍可主动关闭已有启用项。
    assert supported.run_btn.isEnabled()
    assert page.start_btn.text() == '开始'
    assert page.stop_btn.text() == '停止'
    assert page.macos_prepare_btn.isEnabled()
    assert '短暂置前游戏并使用鼠标' in page.macos_prepare_btn.toolTip()
    assert all(task.enabled for task in tasks)
    page.app_id = 'email'
    page.on_context_state_changed()
    assert not page.start_btn.isEnabled()
    assert page.start_btn.text() == 'Mac暂未适配'
    assert page.macos_prepare_btn.isEnabled()
    page.close()


def test_preparation_runner_starts_and_stops_without_running_tasks(qapp: QApplication) -> None:
    """准备按钮后台任务只执行公共准备服务，不创建体力或其他应用。"""
    context = SimpleNamespace(
        ready_for_application=True, initialization_error=None,
        run_context=Mock(), macos_session_preparation=Mock(),
    )
    context.run_context.start_running.return_value = True
    context.macos_session_preparation.prepare.return_value = OperationResult(True, status='手柄大世界已确认')
    runner = MacGamePreparationRunner(context)

    runner.run()

    assert runner.result.success
    context.run_context.start_running.assert_called_once_with()
    context.macos_session_preparation.prepare.assert_called_once_with()
    context.run_context.stop_running.assert_called_once_with()
    context.run_context.run_application.assert_not_called()
