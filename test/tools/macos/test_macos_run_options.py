"""单次 GUI/CLI 请求使用模拟调度与普通离屏控件，不连接设备。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from one_dragon.base.operation.application.application_run_context import (
    ApplicationRunResult,
    RunFinishReason,
)
from zzz_od.gui.view.macos_run_options import MacAppRunner, MacRunOptionsPanel
from zzz_od.macos import application_capabilities, run_request
from zzz_od.macos.run_request import MacRunOptions


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def make_context() -> SimpleNamespace:
    """允许单项调用；业务调度只返回内存结果。"""
    return SimpleNamespace(
        current_instance_idx=2,
        game_account_config=SimpleNamespace(platform='macos_playcover', game_region='cn'),
        one_dragon_config=SimpleNamespace(instance_run='仅运行当前', after_done='无'),
        get_application_unavailable_reason=Mock(return_value=None),
        app_group_manager=SimpleNamespace(get_one_dragon_group_config=Mock(return_value=SimpleNamespace(app_list=[
            SimpleNamespace(app_id='coffee', enabled=True),
            SimpleNamespace(app_id='email', enabled=False),
        ]))),
        run_context=SimpleNamespace(
            is_app_registered=Mock(return_value=True), is_app_standalone_available=Mock(return_value=True),
            event_bus=Mock(), get_application_name=Mock(side_effect=lambda item: item),
            get_run_record=Mock(return_value=SimpleNamespace(run_status=1)),
            last_application_result=SimpleNamespace(status='已完成'), run_application=Mock(),
        ),
    )


@pytest.mark.parametrize(('app_id', 'options', 'attr'), [
    ('email', MacRunOptions(claim_all_mail=True), 'macos_claim_all_mail'),
    ('redemption_code', MacRunOptions(redeem_code='abc123'), 'macos_redeem_code'),
    ('coffee', MacRunOptions(tinman_only=True), 'macos_tinman_only'),
    ('lost_void', MacRunOptions(resume_lost_void=True), 'macos_resume_lost_void'),
    ('lost_void', MacRunOptions(resume_lost_void=True, resume_store_refreshed=True), 'macos_resume_store_refreshed'),
    ('daily_signin', MacRunOptions(resume_signin_reward=True), 'macos_resume_signin_reward'),
])
def test_options_are_scoped_to_one_run(app_id: str, options: MacRunOptions, attr: str) -> None:
    """每个特殊选项进入生产应用可读；失败后全部临时字段移除。"""
    ctx = make_context()
    with pytest.raises(RuntimeError), options.scoped(ctx, app_id):
        assert getattr(ctx, attr) == ('ABC123' if attr == 'macos_redeem_code' else True)
        raise RuntimeError('模拟中断')
    assert not any(key.startswith('macos_') for key in vars(ctx))


@pytest.mark.parametrize(('app_id', 'options'), [
    ('email', MacRunOptions()),
    ('redemption_code', MacRunOptions()),
    ('redemption_code', MacRunOptions(redeem_code='too many codes')),
    ('one_dragon', MacRunOptions(claim_all_mail=True)),
    ('coffee', MacRunOptions(resume_signin_reward=True)),
    ('lost_void', MacRunOptions(resume_store_refreshed=True)),
])
def test_invalid_or_implicit_request_is_rejected(app_id: str, options: MacRunOptions) -> None:
    with pytest.raises(ValueError):
        options.validate(app_id, 'cn')


def test_scope_restores_existing_values_and_rejects_overseas_redemption() -> None:
    ctx = make_context()
    ctx.macos_tinman_only = True
    with MacRunOptions().scoped(ctx, 'daily_signin'):
        assert ctx.macos_tinman_only is False
    assert ctx.macos_tinman_only is True
    with pytest.raises(ValueError, match='国服'):
        MacRunOptions(redeem_code='ABC123').validate('redemption_code', 'global')


def test_gui_runner_reuses_original_dispatch_and_cleans_options(qapp: QApplication) -> None:
    ctx = make_context()
    runner = MacAppRunner(ctx)
    runner.app_id = 'email'
    runner.options = MacRunOptions(claim_all_mail=True)
    result = ApplicationRunResult(RunFinishReason.COMPLETED, 'email', 2, 'one_dragon')

    def run(app_id: str, instance_idx: int, group_id: str) -> ApplicationRunResult:
        assert ctx.macos_claim_all_mail is True
        assert (app_id, instance_idx, group_id) == ('email', 2, 'one_dragon')
        return result

    ctx.run_context.run_application.side_effect = run
    runner.run()

    assert runner.run_result is result
    assert runner.summary['success'] is True
    assert runner.options == MacRunOptions()
    assert not hasattr(ctx, 'macos_claim_all_mail')
    ctx.run_context.run_application.assert_called_once_with(app_id='email', instance_idx=2, group_id='one_dragon')


def test_runner_rejects_unconfirmed_mail_without_dispatch(qapp: QApplication) -> None:
    ctx = make_context()
    runner = MacAppRunner(ctx)
    runner.app_id = 'email'
    runner.run()
    ctx.run_context.run_application.assert_not_called()
    assert runner.summary['success'] is False
    assert '勾选' in runner.summary['status']
    assert not hasattr(ctx, 'macos_claim_all_mail')


def test_runner_exception_releases_options_and_event_subscriptions(qapp: QApplication) -> None:
    ctx = make_context()
    ctx.run_context.run_application.side_effect = RuntimeError('模拟调度异常')
    runner = MacAppRunner(ctx)
    runner.app_id = 'coffee'
    runner.options = MacRunOptions(tinman_only=True)
    runner.run()
    assert runner.summary['success'] is False
    assert '模拟调度异常' in runner.summary['status']
    assert runner.options == MacRunOptions()
    assert not hasattr(ctx, 'macos_tinman_only')
    ctx.run_context.event_bus.unlisten_all_event.assert_called_with(runner)


def test_panel_preview_is_read_only_and_selection_never_leaks(qapp: QApplication) -> None:
    ctx = make_context()
    panel = MacRunOptionsPanel(ctx, 'email')
    panel.show_preview()
    assert '运行前待设置' in panel.output.toPlainText()
    panel.claim_all.setChecked(True)
    assert panel.validate_options().claim_all_mail
    panel.set_app('redemption_code')
    assert not panel.claim_all.isChecked()
    panel.code.setText('ABC123')
    panel.show_preview()
    assert 'ABC123' not in panel.output.toPlainText()
    assert panel.validate_options().redeem_code == 'ABC123'
    panel.set_app('coffee')
    assert not panel.code.text()
    assert panel.options() == MacRunOptions()
    ctx.run_context.get_run_record.assert_not_called()
    ctx.run_context.run_application.assert_not_called()
    panel.close()


def test_resume_refreshed_store_depends_on_resume(qapp: QApplication) -> None:
    panel = MacRunOptionsPanel(make_context(), 'lost_void')
    assert not panel.store_refreshed.isEnabled()
    panel.resume_lost_void.setChecked(True)
    panel.store_refreshed.setChecked(True)
    assert panel.options().resume_store_refreshed
    panel.resume_lost_void.setChecked(False)
    assert not panel.options().resume_store_refreshed
    panel.close()


def test_catalog_read_only_result_does_not_fill_or_submit_code(qapp: QApplication) -> None:
    ctx = make_context()
    panel = MacRunOptionsPanel(ctx, 'redemption_code')
    panel._show_catalog([{'code': 'ABC123', 'expiry_date_beijing': '2099-01-01'}])
    assert 'ABC123' in panel.output.toPlainText()
    assert panel.code.text() == ''
    ctx.run_context.run_application.assert_not_called()
    panel.close()


def test_group_preview_shows_enabled_tasks_and_limit_without_records(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_context()
    monkeypatch.setattr(application_capabilities, 'sys', SimpleNamespace(platform='darwin'))
    ctx.app_group_manager.get_one_dragon_group_config.return_value.app_list[0].app_id = 'email'
    panel = MacRunOptionsPanel(ctx, 'one_dragon')
    panel.show_preview()
    assert '邮件只支持单项' in panel.output.toPlainText()
    assert panel.options() == MacRunOptions()
    ctx.run_context.get_run_record.assert_not_called()
    panel.close()


def test_finished_group_with_unconfirmed_child_is_incomplete() -> None:
    ctx = make_context()
    ctx.run_context.get_run_record.return_value = None
    summary, code = run_request.summarize_result(
        ctx, ApplicationRunResult(RunFinishReason.COMPLETED, 'one_dragon', 2, 'one_dragon'),
    )
    assert code == 0
    assert summary['success'] is True
    assert summary['all_tasks_finished'] is False
    assert summary['gaps'] == ['coffee：结果未确认']


def test_standalone_gui_passes_explicit_mail_options_to_original_runner(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """点击 GUI 开始只传本次选项，启动后立即清空控件；测试不启动线程。"""
    from zzz_od.gui.view.standalone import zzz_standalone_app_run_interface

    monkeypatch.setattr(zzz_standalone_app_run_interface, 'sys', SimpleNamespace(platform='darwin'))
    ctx = make_context()
    ctx.key_start_running = 'f9'
    ctx.key_stop_running = 'f10'
    ctx.run_context.run_status_text = '空闲'
    ctx.run_context.is_context_stop = True
    page = zzz_standalone_app_run_interface.ZStandaloneAppRunInterface(ctx)
    page._init_layout()
    page.app_id = 'email'
    page.macos_options.set_app('email')
    page.app_runner.start = Mock()
    page.run_app()
    page.app_runner.start.assert_not_called()
    page.macos_options.claim_all.setChecked(True)
    page.run_app()
    page.app_runner.start.assert_called_once()
    assert page.app_runner.app_id == 'email'
    assert page.app_runner.options.claim_all_mail is True
    assert page.macos_options.claim_all.isChecked() is False
    assert not hasattr(ctx, 'macos_claim_all_mail')
    page.close()


def test_one_dragon_card_runs_with_explicit_dialog_options(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """原一条龙卡片使用同一选项请求，取消不会启动应用。"""
    from one_dragon.base.operation.application.application_group_config import (
        ApplicationGroupConfigItem,
    )
    from zzz_od.gui.view.one_dragon import zzz_one_dragon_run_interface

    monkeypatch.setattr(zzz_one_dragon_run_interface, 'sys', SimpleNamespace(platform='darwin'))
    ctx = make_context()
    ctx.key_start_running = 'f9'
    ctx.key_stop_running = 'f10'
    ctx.run_context.run_status_text = '空闲'
    ctx.run_context.is_context_stop = True
    page = zzz_one_dragon_run_interface.ZOneDragonRunInterface(ctx)
    page._init_layout()
    page.app_runner.start = Mock()
    dialog = SimpleNamespace(exec=Mock(return_value=False), panel=SimpleNamespace(validate_options=Mock(
        return_value=MacRunOptions(resume_lost_void=True, resume_store_refreshed=True),
    )))
    monkeypatch.setattr(zzz_one_dragon_run_interface, 'MacTaskRunDialog', Mock(return_value=dialog))
    app = ApplicationGroupConfigItem('lost_void', True)
    page.run_app_by_item(app)
    page.app_runner.start.assert_not_called()
    dialog.exec.return_value = True
    page.run_app_by_item(app)
    page.app_runner.start.assert_called_once()
    assert page.app_runner.app_id == 'lost_void'
    assert page.app_runner.options.resume_lost_void is True
    assert page.app_runner.options.resume_store_refreshed is True
    ctx.run_context.run_application.assert_not_called()
    page.close()


def test_catalog_worker_reports_failure_without_game_or_input(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录失败传给页面；模拟固定目录服务，不发起网络请求。"""
    from zzz_od.gui.view.macos_run_options import MacCatalogRunner
    from zzz_od.macos import redemption_catalog

    monkeypatch.setattr(redemption_catalog, 'fetch_cn_catalog', Mock(side_effect=ValueError('模拟目录失败')))
    runner = MacCatalogRunner()
    failed = Mock()
    ready = Mock()
    runner.catalog_failed.connect(failed)
    runner.catalog_ready.connect(ready)
    runner.run()
    ready.assert_not_called()
    failed.assert_called_once_with('国服目录读取失败：模拟目录失败')


def test_late_catalog_result_does_not_overwrite_another_task(qapp: QApplication) -> None:
    panel = MacRunOptionsPanel(make_context(), 'redemption_code')
    panel.set_app('coffee')
    panel.output.setPlainText('咖啡结果')
    panel._show_catalog([{'code': 'ABC123', 'expiry_date_beijing': '2099-01-01'}])
    panel._show_catalog_error('目录失败')
    assert panel.output.toPlainText() == '咖啡结果'
    panel.close()


@pytest.mark.parametrize('app_id', ['one_dragon', 'charge_plan'])
def test_incomplete_charge_counts_remain_gaps_even_with_success_record(app_id: str) -> None:
    """资源不足或跳过培养项仍保留真实次数，组完成记录不能覆盖缺额。"""
    ctx = make_context()
    ctx.app_group_manager.get_one_dragon_group_config.return_value.app_list[0].app_id = 'charge_plan'
    ctx.run_context.get_config = Mock(return_value=SimpleNamespace(plan_list=[
        SimpleNamespace(mission_name='调查专项', mission_type_name='基础材料', category_name='实战模拟室',
                        run_times=1, plan_times=2, skipped=False),
        SimpleNamespace(mission_name=None, mission_type_name='代理人方案培养', category_name='实战模拟室',
                        run_times=0, plan_times=1, skipped=True),
    ]))
    summary, code = run_request.summarize_result(
        ctx, ApplicationRunResult(RunFinishReason.COMPLETED, app_id, 2, 'one_dragon'),
    )
    assert code == 0
    assert summary['success'] is True
    assert summary['all_tasks_finished'] is False
    assert len(summary['gaps']) == 2
    assert '1/2' in summary['gaps'][0]
    assert '本轮已跳过' in summary['gaps'][1]
    assert [plan['remaining'] for plan in summary['charge_plans']] == [1, 1]
    ctx.run_context.get_config.assert_called_once_with(app_id='charge_plan', instance_idx=2, group_id='one_dragon')


def test_charge_result_reports_unfinished_when_config_is_unavailable() -> None:
    ctx = make_context()
    ctx.run_context.last_application_result.data = {'plans_finished': False, 'completed_battles': 0}
    summary, code = run_request.summarize_result(
        ctx, ApplicationRunResult(RunFinishReason.COMPLETED, 'charge_plan', 2, 'one_dragon'),
    )
    assert code == 0
    assert summary['all_tasks_finished'] is False
    assert '体力计划仍有未完成次数' in summary['gaps'][0]


def test_charge_result_preserves_synthesis_shortage_for_this_run_only() -> None:
    """同一份 GUI 和 CLI 结果说明跳过原因，保存的计划仍可下次重试。"""
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem

    ctx = make_context()
    plan = ChargePlanItem(category_name='合成电池', mission_type_name='', mission_name=None)
    plan.mark_skipped('合成电池素材不足')
    ctx.run_context.get_config = Mock(return_value=SimpleNamespace(plan_list=[plan]))
    summary, code = run_request.summarize_result(
        ctx, ApplicationRunResult(RunFinishReason.COMPLETED, 'charge_plan', 2, 'one_dragon'),
    )
    assert code == 0 and not summary['all_tasks_finished']
    assert '合成电池素材不足' in summary['gaps'][0]
    reloaded = ChargePlanItem.from_dict(plan.to_dict())
    assert not reloaded.skipped and not reloaded.skip_reason
