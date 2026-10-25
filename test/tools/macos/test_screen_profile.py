"""平台画面差异必须隔离保存，并继续继承公共画面的更新。"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.base.screen.screen_area import ScreenArea
from one_dragon.base.screen.screen_info import ScreenInfo
from one_dragon.base.screen.screen_loader import ScreenContext
from one_dragon.utils import os_utils
from zzz_od.context import zzz_context


def _write_yaml(path: Path, data: Any) -> None:
    """写入当前测试的临时配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')


@pytest.fixture
def screens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """准备两个公共画面，所有文件读写限制在临时目录。"""
    monkeypatch.setattr(os_utils, '_work_dir', tmp_path)
    data = [
        {
            'screen_id': 'main', 'screen_name': '主画面', 'pc_alt': False,
            'area_list': [
                {'area_name': '前往', 'area_type': 'text', 'pc_rect': [0, 0, 20, 20],
                 'text': '前往', 'lcs_percent': 0.5, 'id_mark': True, 'goto_list': ['详情']},
                {'area_name': '删除项', 'area_type': 'none', 'pc_rect': [20, 20, 40, 40]},
            ],
        },
        {'screen_id': 'detail', 'screen_name': '详情', 'area_list': []},
    ]
    directory = tmp_path / 'assets/game_data/screen_info'
    for screen in data:
        _write_yaml(directory / f'{screen["screen_id"]}.yml', screen)
    _write_yaml(directory / '_od_merged.yml', data)
    return data


def test_save_isolated_delta_inherits_updated_upstream(screens: list[dict[str, Any]]) -> None:
    """保存只写变化字段；公共文件不变，未改字段继承后续上游更新。"""
    loader = ProfileScreenContext()
    loader.reload()
    original_files = {path: path.read_bytes() for path in loader.yml_file_dir.glob('*.yml')}
    area = loader.get_area('主画面', '前往')
    area.pc_rect = Rect(100, 100, 120, 120)
    loader.save_screen(loader.get_screen('主画面'))

    patch = yaml.safe_load((loader.patch_dir / 'main.yml').read_text(encoding='utf-8'))
    assert patch == {'screen_id': 'main', 'area_patches': {'前往': {'pc_rect': [100, 100, 120, 120]}}}
    assert all(path.read_bytes() == content for path, content in original_files.items())
    updated = deepcopy(screens)
    updated[0]['area_list'][0]['text'] = '新版前往'
    updated[0]['area_list'][0]['lcs_percent'] = 0.8
    _write_yaml(loader.merge_yml_file_path, updated)
    loader.reload()
    assert loader.get_area('主画面', '前往').text == '新版前往'
    assert loader.get_area('主画面', '前往').lcs_percent == 0.8
    assert loader.get_area('主画面', '前往').pc_rect.x1 == 100
    windows_loader = ScreenContext()
    windows_loader.reload()
    assert windows_loader.get_area('主画面', '前往').pc_rect.x1 == 0


def test_area_add_delete_and_clear_refresh_indices(screens: list[dict[str, Any]]) -> None:
    """新增区域完整保存，删除与清除字段即时更新区域索引和画面路由。"""
    loader = ProfileScreenContext()
    loader.reload()
    screen = loader.get_screen('主画面')
    screen.remove_area_by_name('删除项')
    screen.area_list[0].id_mark = False
    screen.area_list[0].goto_list = []
    screen.upsert_area(ScreenArea('新增', pc_rect=Rect(50, 50, 60, 60), goto_list=['详情']))
    loader.save_screen(screen)

    assert loader.get_area('主画面', '删除项') is None
    assert loader.get_screen_route('主画面', '详情').node_list[0].from_area == '新增'
    patch = yaml.safe_load((loader.patch_dir / 'main.yml').read_text(encoding='utf-8'))
    assert patch['deleted_areas'] == ['删除项']
    assert patch['area_patches'] == {'前往': {'id_mark': None, 'goto_list': None}}
    assert patch['added_areas'][0]['pc_rect'] == [50, 50, 60, 60]
    loader.reload()
    assert loader.get_area('主画面', '前往').id_mark is False
    assert loader.get_area('主画面', '前往').goto_list == []
    assert loader.get_area('主画面', '新增') is not None
    assert loader.get_area('主画面', '删除项') is None


def test_plugin_and_new_screens_keep_public_files_and_reject_rename(
    screens: list[dict[str, Any]], tmp_path: Path,
) -> None:
    """插件差异和新增独立画面也写平台目录，改名和整画面删除明确失败。"""
    plugin_file = tmp_path / 'plugin/screen_info/plugin.yml'
    _write_yaml(plugin_file, {'screen_id': 'plugin', 'screen_name': '插件画面', 'area_list': []})
    original = plugin_file.read_bytes()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.load_extra_screen_dir(str(plugin_file.parent), 'plugin_app')
    loader.apply_profile_patches()
    plugin = loader.get_screen('插件画面')
    plugin.upsert_area(ScreenArea('按钮', pc_rect=Rect(1, 2, 3, 4)))
    loader.save_screen(plugin)
    assert plugin_file.read_bytes() == original
    loader.save_screen(ScreenInfo({'screen_id': 'ios_only', 'screen_name': '平台画面', 'area_list': []}))
    loader.reload()
    loader.load_extra_screen_dir(str(plugin_file.parent), 'plugin_app')
    loader.apply_profile_patches()
    assert loader.get_area('插件画面', '按钮') is not None
    assert loader.get_screen('平台画面').screen_id == 'ios_only'
    renamed = loader.get_screen('主画面', copy=True)
    renamed.screen_name = '改名'
    with pytest.raises(ValueError, match='修改画面名称'):
        loader.save_screen(renamed)
    renamed = loader.get_screen('主画面', copy=True)
    renamed.screen_id = 'renamed'
    with pytest.raises(ValueError, match='修改画面 ID'):
        loader.save_screen(renamed)
    with pytest.raises(ValueError, match='整画面删除'):
        loader.delete_screen('main')
    with pytest.raises(ValueError, match='不支持的画面资源配置'):
        ProfileScreenContext('../screen_info')


def test_instance_refresh_reloads_profile_and_cached_areas(
    screens: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """实例刷新重新读取平台文件并清旧索引和服务缓存，Windows 保持原行为。"""
    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(zzz_context.ZContext, 'macos_config', property(lambda self: SimpleNamespace(resource_profile='ios_gamepad')))
    context = zzz_context.ZContext.__new__(zzz_context.ZContext)
    context.controller = None
    context.current_instance_idx = 1
    context.factory_manager = SimpleNamespace(plugin_infos=[])
    context.template_loader = SimpleNamespace(template={'旧模板': object()})
    context.auto_battle_context = SimpleNamespace(init_screen_area=Mock())
    context.cv_service = object()
    context.screen_loader = ProfileScreenContext()
    context.screen_loader.reload()
    context.screen_loader.update_current_screen_name('主画面')
    old_loader = context.screen_loader
    _write_yaml(old_loader.patch_dir / 'main.yml', {'screen_id': 'main', 'area_patches': {'前往': {'pc_rect': [2, 2, 8, 8]}}})

    context.reload_instance_config()

    assert context.screen_loader is not old_loader
    assert context.screen_loader.current_screen_name is None
    assert context.screen_loader.get_area('主画面', '前往').pc_rect.x1 == 2
    assert context.template_loader.template == {}
    assert 'cv_service' not in context.__dict__
    context.auto_battle_context.init_screen_area.assert_called_once_with()
    monkeypatch.setattr(zzz_context, 'sys', SimpleNamespace(platform='win32'))
    windows_loader = ScreenContext()
    context.screen_loader = windows_loader
    context.reload_instance_config()
    assert context.screen_loader is windows_loader
