"""验证 Mac 加速开关、CPU回退、编译缓存与跨模型串行执行。"""

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import FluentIcon

from one_dragon.base.config.yaml_operator import YamlOperator
from one_dragon.utils import gpu_executor
from one_dragon.yolo import onnx_model_loader
from one_dragon_qt.utils.config_utils import get_prop_adapter
from one_dragon_qt.view.resource_management_interface import ResourceManagementInterface
from one_dragon_qt.widgets.download_card.onnx_model_download_card import (
    OnnxModelDownloadCard,
)
from zzz_od.config import model_config
from zzz_od.gui.view.battle_assistant.battle_assistant_interface import (
    BattleAssistantInterface,
)


class Session:
    """只替代模型文件解析，保留真实provider选择及创建调度。"""

    def get_inputs(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name='images', shape=[1, 3, 640, 640])]

    def get_outputs(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name='output0')]

    def get_providers(self) -> list[str]:
        return ['CPUExecutionProvider']


def make_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> onnx_model_loader.OnnxModelLoader:
    """不下载、不读取用户设置，缓存仅写入临时目录。"""
    (tmp_path / 'model.onnx').write_bytes(b'original model')
    monkeypatch.setattr(onnx_model_loader.os_utils, 'get_path_under_work_dir',
                        lambda *parts: str(tmp_path.joinpath(*parts)))
    loader = object.__new__(onnx_model_loader.OnnxModelLoader)
    loader.model_dir_path = str(tmp_path)
    loader.gpu = True
    return loader


@pytest.mark.parametrize(('platform', 'enabled', 'available', 'expected'), [
    ('darwin', False, ['CoreMLExecutionProvider', 'CPUExecutionProvider'], 'CPUExecutionProvider'),
    ('darwin', True, ['CoreMLExecutionProvider', 'CPUExecutionProvider'], 'CoreMLExecutionProvider'),
    ('darwin', True, ['CPUExecutionProvider'], 'CPUExecutionProvider'),
    ('win32', True, ['CoreMLExecutionProvider', 'CUDAExecutionProvider'], 'CUDAExecutionProvider'),
    ('win32', True, ['DmlExecutionProvider'], 'DmlExecutionProvider'),
])
def test_backend_selection_preserves_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, enabled: bool,
    available: list[str], expected: str,
) -> None:
    loader = make_loader(tmp_path, monkeypatch)
    loader.gpu = enabled
    monkeypatch.setattr(onnx_model_loader, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(onnx_model_loader.ort, 'get_available_providers', lambda: available)
    factory = Mock(return_value=Session())
    monkeypatch.setattr(onnx_model_loader.ort, 'InferenceSession', factory)

    loader.load_model()

    providers = factory.call_args.kwargs['providers']
    first = providers[0]
    assert (first[0] if isinstance(first, tuple) else first) == expected
    if expected == 'CoreMLExecutionProvider':
        assert providers[1] == 'CPUExecutionProvider'
        assert first[1]['ModelFormat'] == 'MLProgram'
        assert first[1]['RequireStaticInputShapes'] == '1'


def test_coreml_cache_changes_when_model_content_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = make_loader(tmp_path, monkeypatch)
    path = tmp_path / 'model.onnx'
    first = Path(loader._get_coreml_options(path)['ModelCacheDirectory'])
    assert first.name == hashlib.sha256(b'original model').hexdigest()
    path.write_bytes(b'updated model')
    second = Path(loader._get_coreml_options(path)['ModelCacheDirectory'])
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert path.read_bytes() == b'updated model'


def test_coreml_initialization_failure_falls_back_to_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = make_loader(tmp_path, monkeypatch)
    monkeypatch.setattr(onnx_model_loader, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(onnx_model_loader.ort, 'get_available_providers',
                        lambda: ['CoreMLExecutionProvider', 'CPUExecutionProvider'])
    factory = Mock(side_effect=[RuntimeError('Core ML compile failed'), Session()])
    monkeypatch.setattr(onnx_model_loader.ort, 'InferenceSession', factory)

    loader.load_model()

    assert factory.call_count == 2
    assert factory.call_args.kwargs['providers'] == ['CPUExecutionProvider']
    assert loader.input_names == ['images']


def test_coreml_sessions_serialize_and_allow_nested_calls() -> None:
    lock = threading.Lock()
    active = 0
    maximum = 0

    def operation(*args: object, **kwargs: object) -> Session:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(.01)
        with lock:
            active -= 1
        return Session()

    session = SimpleNamespace(get_providers=lambda: ['CoreMLExecutionProvider'], run=operation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(gpu_executor.create_onnx_session, operation, ['CoreMLExecutionProvider'])
                       for _ in range(2)]:
            future.result(timeout=2)
        for future in [pool.submit(gpu_executor.run_session, session, None) for _ in range(2)]:
            future.result(timeout=2)
    gpu_executor.submit(gpu_executor.run_session, session, None).result(timeout=2)
    assert maximum == 1


@pytest.fixture(scope='module')
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_one_switch_binds_config_and_unsupported_macos_options_are_hidden(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    monkeypatch.setattr(model_config, 'sys', SimpleNamespace(platform=platform))
    config = object.__new__(model_config.ModelConfig)
    YamlOperator.__init__(config)
    ctx = SimpleNamespace(model_config=config)
    interface = SimpleNamespace(ctx=ctx)
    for key in ('flash_classifier_gpu', 'lost_void_det_gpu', 'hollow_zero_event_gpu'):
        card = OnnxModelDownloadCard(ctx=ctx, icon=FluentIcon.GAME, title='模型')
        ResourceManagementInterface._bind_model_gpu_option(
            interface, card, SimpleNamespace(gpu_config_key=key),
        )
        supported = platform != 'darwin' or key != 'hollow_zero_event_gpu'
        assert card.gpu_opt.isHidden() is not supported
        assert config.data == {}
        if supported:
            card.gpu_opt.setChecked(True)
            assert card.gpu_opt.label.text() == ('Core ML' if platform == 'darwin' else 'GPU')
            assert config.get(key) is True
            card.gpu_opt.setChecked(False)
            assert card.gpu_opt.label.text() == 'CPU'
            assert config.get(key) is False
            config.data.clear()
        card.close()
    ocr_key, _ = config.get_model_acceleration_config('ocr_use_gpu')
    assert ocr_key == (None if platform == 'darwin' else 'ocr_use_gpu')


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_battle_assistant_replaces_the_shared_gpu_card_on_macos(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """只构造普通控件，验证原共用开关的文案与持久配置绑定。"""
    monkeypatch.setattr(model_config, 'sys', SimpleNamespace(platform=platform))
    config = object.__new__(model_config.ModelConfig)
    YamlOperator.__init__(config)
    interface = BattleAssistantInterface(SimpleNamespace(model_config=config))
    monkeypatch.setattr(interface, '_build_auto_battle_page', QWidget)
    monkeypatch.setattr(interface, '_build_dodge_page', QWidget)
    monkeypatch.setattr(interface, '_apply_mode', lambda mode: None)
    top = interface.get_widget_at_top()
    assert interface.gpu_opt.titleLabel.text() == ('使用 Core ML' if platform == 'darwin' else 'GPU运算')
    interface.gpu_opt.init_with_adapter(get_prop_adapter(config, 'flash_classifier_gpu'))
    assert config.data == {}
    interface.gpu_opt.btn.setChecked(True)
    assert config.flash_classifier_gpu is True
    interface.gpu_opt.btn.setChecked(False)
    assert config.flash_classifier_gpu is False
    top.close()
    interface.close()
