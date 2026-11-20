"""兑换码目录、CLI、一次性账户记录的纯本地测试。"""

from datetime import date
from pathlib import Path

import pytest

from zzz_od.application.redemption_code.redemption_code_run_record import (
    RedemptionCodeRunRecord,
)
from zzz_od.macos import cli, redemption_catalog


def test_only_explicit_unexpired_data() -> None:
    data = b'codes:\n  DAILY123: 20261121\n  Expired: 20261120\n  malformed: 20262301\n  close: true\n  BAD: 20990101\nother: ignore me'
    assert redemption_catalog.parse_cn_catalog(data, date(2026, 11, 21)) == [
        {'code': 'DAILY123', 'expiry_date_beijing': '2026-11-21'},
    ]


@pytest.mark.parametrize('bad', [b'codes: nope', b'danger: yes', b'\n' * 65537])
def test_untrusted_catalog_invalid(bad: bytes) -> None:
    with pytest.raises(ValueError):
        redemption_catalog.parse_cn_catalog(bad, date(2026, 11, 21))


@pytest.mark.parametrize('argv', [
    ['--app', 'redemption_code'], ['--redeem-code', 'CODE123'],
    ['--app', 'redemption_code', '--redeem-code', 'CODE!123'],
    ['--app', 'redemption_code', '--list-redeem-codes', '--redeem-code', 'CODE123'],
    ['--app', 'redemption_code', '--dry-run', '--redeem-code', 'CODE123'],
    ['--app', 'redemption_code', '--claim-all', '--redeem-code', 'CODE123'],
    ['--list-redeem-codes'],
    ['--app', 'redemption_code', '--redeem-code', 'FIRST123', '--redeem-code', 'SECOND123'],
])
def test_cli_rejects_unscoped_invocations(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2


def test_attempt_is_exclusive_and_prior_usage_is_respected(tmp_path: Path) -> None:
    record = RedemptionCodeRunRecord.__new__(RedemptionCodeRunRecord)
    record.file_path = str(tmp_path / 'redeem.yml')
    record.data = {'used_code_list': ['already']}
    assert record.macos_code_attempted('ALREADY')
    assert not record.macos_code_attempted('NEVER123')
    assert record.begin_macos_attempt('NEVER123') is True
    assert record.begin_macos_attempt('NEVER123') is False
    assert record.macos_code_attempted('NEVER123')



def test_mac_group_with_redemption_enabled_refuses_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from one_dragon.base.config.one_dragon_config import AfterDoneOpEnum, InstanceRun
    from zzz_od.macos import application_capabilities as capabilities

    monkeypatch.setattr(capabilities, 'sys', SimpleNamespace(platform='darwin'))
    group = SimpleNamespace(app_list=[SimpleNamespace(app_id='redemption_code', enabled=True)])
    ctx = SimpleNamespace(
        current_instance_idx=2,
        one_dragon_config=SimpleNamespace(
            instance_run=InstanceRun.CURRENT.value.value, after_done=AfterDoneOpEnum.NONE.value.value),
        app_group_manager=SimpleNamespace(get_one_dragon_group_config=lambda _: group),
    )
    assert '兑换码' in capabilities.get_macos_one_dragon_unavailable_reason(ctx)
    assert group.app_list[0].enabled


def test_mac_redemption_app_without_manual_code_cannot_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from zzz_od.application.redemption_code import redemption_code_app

    monkeypatch.setattr(redemption_code_app, 'sys', SimpleNamespace(platform='darwin'))
    app = redemption_code_app.RedemptionCodeApp.__new__(redemption_code_app.RedemptionCodeApp)
    app.ctx = SimpleNamespace()
    result = app.execute()
    assert not result.success and '--redeem-code' in result.status
