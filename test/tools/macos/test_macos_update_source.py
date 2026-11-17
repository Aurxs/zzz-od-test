"""验证 Mac 更新来源、旧配置兼容及资源页的平台入口，不联网或操作游戏。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pygit2 import init_repository
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon, SettingCard

from one_dragon.base.config.yaml_config import YamlConfig
from one_dragon.envs import env_config
from one_dragon.envs.git_service import GitService, GitSyncStatus
from one_dragon.envs.project_config import ProjectConfig
from one_dragon.envs.repo_config import RepoConfig
from one_dragon_qt.view import resource_management_interface

MAC_REPOSITORY = 'https://github.com/Aurxs/ZenlessZoneZero-OneDragon-MacOS.git'


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> env_config.EnvConfig:
    """读取项目的正式代码源，只将个人环境配置改为内存存储。"""
    repository = RepoConfig()
    original_paths = YamlConfig._get_yaml_file_paths

    def config_paths(config: YamlConfig) -> tuple[str | None, str | None, str | None]:
        if config.module_name == 'env':
            return None, None, None
        return original_paths(config)

    monkeypatch.setattr(YamlConfig, '_get_yaml_file_paths', config_paths)
    return env_config.EnvConfig(repository)


def test_project_sources_and_regions_only_select_mac_code(config: env_config.EnvConfig) -> None:
    """所有地区只选择 Mac 代码，模型的 CNB/Gitee 资源源仍保留。"""
    repository = config.repo_config
    assert [item.url for item in repository.repositories] == [MAC_REPOSITORY]
    assert ProjectConfig().github_homepage == MAC_REPOSITORY.removesuffix('.git')
    assert [item.branch_name for item in repository.branches] == ['main']
    for region in repository.regions:
        assert repository.find_repository(region.repository_id).url == MAC_REPOSITORY
    assert {item.source_id for item in repository.resource_sources} >= {'github', 'cnb', 'gitee'}


@pytest.mark.parametrize('old_source', [
    'https://github.com/Aurxs/ZenlessZoneZero-OneDragon.git',
    'https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon.git',
    'https://cnb.cool/OneDragon-Anything/ZenlessZoneZero-OneDragon.git',
    'https://gitee.com/OneDragon-Anything/ZenlessZoneZero-OneDragon.git',
])
def test_stale_source_cannot_fall_back_to_upstream(
    config: env_config.EnvConfig, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, old_source: str,
) -> None:
    """旧选择和成功源均失效时只尝试 Mac，失败也将 origin 恢复到 Mac。"""
    config.repository_url = old_source
    config.last_repository_url = old_source
    repository = init_repository(str(tmp_path))
    repository.remotes.create('origin', old_source)
    repository.remotes.create('upstream', old_source)
    service = GitService(config, config.repo_config, str(tmp_path))
    fetch = Mock(side_effect=TimeoutError('模拟 Mac 仓库不可达'))
    monkeypatch.setattr(service, '_fetch_remote_once', fetch)

    status, _ = service._fetch_remote()

    assert status is GitSyncStatus.REMOTE_UNAVAILABLE
    assert config.repository_url == 'auto'
    fetch.assert_called_once()
    assert fetch.call_args.args[0] == MAC_REPOSITORY
    assert service._open_repo().remotes['origin'].url == MAC_REPOSITORY
    assert service._open_repo().remotes['upstream'].url == old_source


@pytest.mark.parametrize(('branch', 'custom', 'expected'), [
    ('test', False, 'main'),
    ('main', False, 'main'),
    ('codex/macos-migration', True, 'codex/macos-migration'),
])
def test_removed_standard_branch_uses_main(
    config: env_config.EnvConfig, branch: str, custom: bool, expected: str,
) -> None:
    """旧标准 test 分支回到 main，显式自定义分支保持原值。"""
    config.git_branch = branch
    config.custom_git_branch = custom
    assert config.git_branch == expected
    assert config.get('git_branch') == branch


@pytest.mark.parametrize(('platform', 'expected'), [('darwin', False), ('win32', True)])
def test_force_update_default_preserves_explicit_setting(
    config: env_config.EnvConfig, monkeypatch: pytest.MonkeyPatch,
    platform: str, expected: bool,
) -> None:
    """Mac 新配置默认不强制更新，已有用户设置和 Windows 默认值保持原行为。"""
    monkeypatch.setattr(env_config, 'sys', SimpleNamespace(platform=platform))
    assert config.force_update is expected
    config.force_update = not expected
    assert config.force_update is not expected


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    """仅创建离屏普通 Qt 控件。"""
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_resource_page_only_offers_windows_launcher_on_windows(
    qapp: QApplication, config: env_config.EnvConfig,
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """真实资源页使用 Mac 源，并在 Mac 隐藏 EXE 自动更新及 Windows 启动器。"""
    monkeypatch.setattr(resource_management_interface, 'sys', SimpleNamespace(platform=platform))

    def make_card(title: str) -> SettingCard:
        card = SettingCard(FluentIcon.INFO, title)
        card.gpu_opt = Mock()
        card.use_download_queue = Mock()
        return card

    launcher = Mock(side_effect=lambda ctx: make_card('Windows 启动器'))
    monkeypatch.setattr(resource_management_interface, 'LauncherDownloadCard', launcher)
    monkeypatch.setattr(resource_management_interface, 'get_ocr_opts', lambda: [])
    monkeypatch.setattr(
        resource_management_interface.ResourceManagementInterface, '_create_model_card',
        lambda self, title, options, current_getter, config_key, resource_id: make_card(title),
    )
    ctx = SimpleNamespace(
        env_config=config, repo_config=config.repo_config, git_service=Mock(),
        model_config=SimpleNamespace(
            get_model_acceleration_config=lambda key: (None, None),
            get_model_resources=lambda: [],
        ),
    )
    interface = resource_management_interface.ResourceManagementInterface(ctx, Mock())
    content = interface.get_content_widget()

    assert interface.auto_update_code_opt.isHidden() is (platform == 'darwin')
    assert hasattr(interface, 'launcher_opt') is (platform == 'win32')
    assert launcher.call_count == (1 if platform == 'win32' else 0)
    assert interface.repository_url_opt.combo_box.count() == 2
    if platform == 'darwin':
        assert interface.code_card.titleLabel.text() == 'Mac 版代码同步'
    content.close()
    interface.close()
