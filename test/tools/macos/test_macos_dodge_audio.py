"""验证平台声音后端和生产模板分类，原 Windows 路径保持可用。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from zzz_od.auto_battle import auto_battle_dodge_context as dodge_module


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_supported_platforms_use_production_audio_matching(
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 与 Windows 共用原模板，其他平台只保留画面识别。"""
    monkeypatch.setattr(dodge_module, 'sys', SimpleNamespace(platform=platform))
    executor = Mock()
    monkeypatch.setattr(dodge_module, '_dodge_check_executor', executor)
    context = dodge_module.AutoBattleDodgeContext(Mock())
    recorder = Mock(trigger_threshold=0.1)
    recorder.get_latest_audio.return_value = np.ones(8)
    context._audio_recorder = recorder
    context._audio_template_fft = np.ones((3, 8))
    context.get_max_corr = Mock(return_value=np.array([0.2, 0.05, 0.01]))

    context.init_battle_dodge_context()
    context.start_context_async()
    detected = context.check_dodge_audio(1)

    if platform in ('win32', 'darwin'):
        executor.submit.assert_called_once_with(context.init_audio_template)
        recorder.start_running_async.assert_called_once_with()
        context.get_max_corr.assert_called_once()
        recorder.clear_audio.assert_called_once_with()
        assert detected is dodge_module.AudioTemplateEnum.NORMAL_DODGE
    else:
        executor.submit.assert_not_called()
        recorder.start_running_async.assert_not_called()
        recorder.get_latest_audio.assert_not_called()
        context.get_max_corr.assert_not_called()
        assert detected is False


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_recorder_backend_does_not_import_other_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 构造原生窗口订阅器，Windows 仍使用原录音类。"""
    monkeypatch.setattr(dodge_module, 'sys', SimpleNamespace(platform=platform))
    context = dodge_module.AutoBattleDodgeContext(Mock())
    assert isinstance(context._audio_recorder, dodge_module.MacAudioRecorder) == (platform == 'darwin')


@pytest.mark.parametrize('template, should_dodge', [
    (dodge_module.AudioTemplateEnum.NORMAL_DODGE, True),
    (dodge_module.AudioTemplateEnum.PURPLE_DODGE, False),
    (dodge_module.AudioTemplateEnum.X_DODGE, True),
    (False, False),
])
def test_audio_classification_keeps_original_dodge_rules(template: object, should_dodge: bool) -> None:
    """只有普通和 X 提示触发声音状态；音频失效时红黄光仍可识别。"""
    from concurrent.futures import Future

    context = dodge_module.AutoBattleDodgeContext(Mock())
    context._flash_model = Mock()
    context._flash_model.run.return_value = SimpleNamespace(class_idx=0)
    result = Future()
    result.set_result(template)
    assert context.check_dodge_flash(np.zeros((2, 2, 3)), 1, result) is should_dodge
    context._flash_model.run.return_value = SimpleNamespace(class_idx=1)
    assert context.check_dodge_flash(np.zeros((2, 2, 3)), 2, result) is True
