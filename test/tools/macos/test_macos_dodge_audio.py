"""验证 Mac 战斗不使用 Windows 声音采集，Windows 行为保留。"""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from zzz_od.auto_battle import auto_battle_dodge_context as dodge_module


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_dodge_audio_only_runs_on_windows(
    monkeypatch: pytest.MonkeyPatch, platform: str,
) -> None:
    """Mac 不加载音频模板、不录音、不返回声音事件。"""
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

    if platform == 'win32':
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
