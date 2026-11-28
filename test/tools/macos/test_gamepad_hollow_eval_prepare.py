"""核对固定难度与出战准备的手柄操作。"""

from types import SimpleNamespace
from unittest.mock import Mock, call

from zzz_od.operation.gamepad.hollow_eval_speed import (
    GamepadHollowEvalDeploy,
    GamepadHollowEvalPrepare,
)


def test_prepare_moves_to_fixed_mission_and_stops_without_deploying() -> None:
    op = GamepadHollowEvalPrepare(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op._is_ready = Mock(return_value=False)
    op._selected_mission = Mock(side_effect=[
        '施工废墟-核心', '施工废墟-腹地', '施工废墟-内部', '施工废墟-内部',
    ])
    op.save_screenshot = Mock(return_value='出战准备页')
    for _ in range(4):
        assert not op.prepare().is_success
    op._is_ready.return_value = True
    result = op.prepare()
    assert result.is_success
    assert result.data == {'screenshot': '出战准备页'}
    assert op.ctx.controller.btn_tap.call_args_list == [call('dpad_up'), call('dpad_up'), call('start')]


def test_unknown_preparation_origin_cannot_trigger_deploy() -> None:
    op = GamepadHollowEvalPrepare(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op.transport._at_hollow_hub = Mock(return_value=False)
    op._zone_screen = Mock(return_value=False)
    op._selected_mission = Mock(return_value=None)
    op._is_ready = Mock(return_value=True)
    assert op.reach().is_fail
    assert not op.prepare().is_success
    op.ctx.controller.btn_tap.assert_not_called()


def test_deploy_from_known_ready_sends_start_once_and_requires_board() -> None:
    op = GamepadHollowEvalDeploy(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op._is_ready = Mock(return_value=True)
    op.navigation._read_area = Mock(return_value=None)
    op.save_screenshot = Mock(return_value='已确认局内')
    assert not op.deploy().is_success
    assert not op.deploy().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('start')
    op.navigation._read_area.side_effect = lambda _, area: (
        (None, {'请领取鸣徽': object(), 'A': object(), '选择': object()}) if area == '手柄-速刷鸣徽' else None
    )
    assert op.deploy().data == {'screenshot': '已确认局内'}


def test_resume_only_accepts_the_fixed_ongoing_mission_and_confirmation_focus() -> None:
    op = GamepadHollowEvalDeploy(SimpleNamespace(controller=Mock()))
    op._after_round_wait = Mock()
    op._resume_prompt = Mock(side_effect=[(False, True), (True, False), (True, True)])
    assert op.deploy().is_fail
    assert not op.deploy().is_success
    op.ctx.controller.btn_tap.assert_not_called()
    assert not op.deploy().is_success
    op.ctx.controller.btn_tap.assert_called_once_with('south')
