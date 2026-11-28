"""核对三个日常任务在新旧配置中的地点，不读取本机实例。"""

import sys

import pytest

from one_dragon.base.config.yaml_operator import YamlOperator
from zzz_od.application.coffee.coffee_config import CoffeeConfig, CoffeeTransportPoint
from zzz_od.application.daily_signin.daily_signin_config import DailySignInConfig
from zzz_od.application.random_play.random_play_config import (
    RandomPlayConfig,
    RandomPlayTransportPoint,
)


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_daily_defaults_and_saved_choices(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(sys, 'platform', platform)
    mac = platform == 'darwin'
    cases = (
        (DailySignInConfig, 'selected_sign', 'trigrams_collection' if mac else 'hou_hou_bakery'),
        (CoffeeConfig, 'transport_point', (CoffeeTransportPoint.POINT_2 if mac else CoffeeTransportPoint.POINT_1).value.value),
        (RandomPlayConfig, 'transport_point', (RandomPlayTransportPoint.POINT_2 if mac else RandomPlayTransportPoint.POINT_1).value.value),
    )
    for config_type, field, default in cases:
        config = config_type.__new__(config_type)
        YamlOperator.__init__(config)
        assert getattr(config, field) == default
        assert config.data == {}
        setattr(config, field, '已保存的其他选择')
        assert getattr(config, field) == '已保存的其他选择'
