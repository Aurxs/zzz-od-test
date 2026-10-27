"""原应用连续调用 Mac 层间操作，悬赏只接受实际分数。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.application.hollow_zero.lost_void import lost_void_app as module
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
from zzz_od.operation.gamepad import lost_void_run_level as gamepad


def test_original_app_immediately_reuses_next_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    regions = []
    results = iter([
        SimpleNamespace(success=True, status=gamepad.LostVoidRunLevel.STATUS_NEXT_LEVEL, data='战斗-鸣徽'),
        SimpleNamespace(success=True, status='继续', data=None),
    ])
    def operation(ctx, region):
        regions.append(region)
        return SimpleNamespace(execute=lambda: next(results))
    monkeypatch.setattr(gamepad, 'GamepadLostVoidRunLevel', operation)
    app = object.__new__(module.LostVoidApp)
    app.ctx = SimpleNamespace(lost_void=SimpleNamespace(had_interacted_ophelia_on_current_level=True))
    app.next_region_type = LostVoidRegionType.ENTRY
    app.round_by_op_result = lambda result: result
    app.run_level()
    app.run_level()
    assert regions == [LostVoidRegionType.ENTRY, LostVoidRegionType.COMBAT_RESONIUM]
    assert not app.ctx.lost_void.had_interacted_ophelia_on_current_level


def test_combat_room_keeps_original_approach_before_battle() -> None:
    operation = object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.region_type = LostVoidRegionType.COMBAT_RESONIUM
    operation.click_challenge_confirm = False
    operation.round_success = Mock(return_value='approach')
    assert operation.init_for_region_type() == 'approach'
    operation.round_success.assert_called_once_with('非战斗区域')


@pytest.mark.parametrize(('text', 'complete'), [('8000/8000', True), ('0/8000', False), ('通关可获得8000', None)])
def test_bounty_uses_fraction_from_actual_progress_area(monkeypatch: pytest.MonkeyPatch, text: str, complete: bool | None) -> None:
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    app = object.__new__(module.LostVoidApp)
    app.last_screenshot = object()
    app.config = SimpleNamespace(is_bounty_commission_mode=True)
    app.run_record = SimpleNamespace(bounty_commission_complete=False)
    app.ctx = SimpleNamespace(screen_loader=SimpleNamespace(get_area=Mock(return_value=SimpleNamespace(rect=object()))),
                              ocr=SimpleNamespace(crop_and_run_ocr=Mock(return_value={text: object()})))
    app.save_screenshot = Mock()
    app.round_success = Mock(return_value='read')
    app.round_retry = Mock(return_value='retry')
    result = app.check_bounty_commission_before()
    if complete is None:
        assert result == 'retry'
        app.round_success.assert_not_called()
        assert not app.run_record.bounty_commission_complete
    else:
        assert result == 'read'
        assert app.run_record.bounty_commission_complete is complete
        app.ctx.screen_loader.get_area.assert_called_once_with('迷失之地-入口', '区域-悬赏委托-进度')


def test_next_region_keeps_waiting_through_black_loading() -> None:
    import numpy as np
    operation = object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.last_screenshot = np.zeros((1080,1920,3),dtype=np.uint8)
    operation.ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)))
    operation.round_retry = Mock(return_value='loading')
    operation.try_talk = Mock()
    assert operation.wait_loading() == 'loading'
    operation.round_retry.assert_called_once_with('等待区域加载', wait=1)
    operation.try_talk.assert_not_called()


def test_short_split_dialogue_requires_bottom_a_prompt() -> None:
    import numpy as np
    from one_dragon.base.geometry.rectangle import Rect
    from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
    ocr = {}
    for text,x,y,width in [('橘福福',540,25,80),('哇，',400,132,45),('来得正好！',460,132,170),('A',1080,207,25)]:
        matches = MatchResultList()
        matches.append(MatchResult(1,x,y,width,30))
        ocr[text] = matches
    operation = object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.ctx = SimpleNamespace(controller=Mock(), lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False)),
                                   screen_loader=SimpleNamespace(get_area=Mock(return_value=SimpleNamespace(rect=Rect(390,780,1530,1040)))),
                                   ocr=SimpleNamespace(crop_and_run_ocr=Mock(return_value=ocr)))
    operation._dialog_frame_time = -1
    operation._dialog_sent_at = 0
    operation._dialog_text = None
    operation._dialog_repeats = 0
    operation.last_screenshot_time = 100
    operation.round_by_find_area = Mock(return_value=SimpleNamespace(is_success=False))
    operation.round_wait = Mock(return_value='talk')
    frame=np.zeros((1080,1920,3),dtype=np.uint8)
    assert operation.try_talk(frame) == 'talk'
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    del ocr['A']
    assert operation.try_talk(frame) is None
    operation.ctx.controller.btn_tap.assert_called_once_with('south')


def test_finished_bounty_record_still_checks_actual_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.sys,'platform','darwin')
    app=object.__new__(module.LostVoidApp)
    app.config=SimpleNamespace(mission_name='战线肃清',is_bounty_commission_mode=True)
    app.run_record=SimpleNamespace(is_finished_by_day=True)
    app.ctx=SimpleNamespace(lost_void=SimpleNamespace(init_before_run=Mock()))
    app.round_success=Mock(return_value='continue')
    assert app.init_for_lost_void()=='continue'
    app.ctx.lost_void.init_before_run.assert_called_once_with()
    app.round_success.assert_called_once_with(app.STATUS_AGAIN)


def test_other_mission_stops_before_loading_or_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.sys,'platform','darwin')
    app=object.__new__(module.LostVoidApp)
    app.config=SimpleNamespace(mission_name='矩阵行动')
    app.round_fail=Mock(return_value='unsupported')
    app.ctx=SimpleNamespace(lost_void=SimpleNamespace(init_before_run=Mock()))
    assert app.init_for_lost_void()=='unsupported'
    app.ctx.lost_void.init_before_run.assert_not_called()


def test_return_to_world_does_not_hide_claim_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from zzz_od.operation.gamepad import lost_void
    monkeypatch.setattr(module.sys,'platform','darwin')
    fake=Mock()
    fake.execute.return_value=SimpleNamespace(success=True,status='已返回游戏主界面')
    monkeypatch.setattr(lost_void,'GamepadLostVoidBackToWorld',Mock(return_value=fake))
    app=object.__new__(module.LostVoidApp)
    app.ctx=object()
    app._macos_claim_error='奖励尚未确认'
    app.round_fail=Mock(return_value='failed')
    app.round_by_op_result=Mock()
    assert app.back_at_last()=='failed'
    app.round_fail.assert_called_once_with('奖励尚未确认')
    app.round_by_op_result.assert_not_called()


def test_challenge_description_confirms_once_and_starts_only_after_closing(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np
    from one_dragon.base.matcher.match_result import MatchResult,MatchResultList
    def words(*texts: str) -> dict[str,MatchResultList]:
        result={}
        for index,text in enumerate(texts):
            matches=MatchResultList()
            matches.append(MatchResult(1,40+index*100,20,80,25))
            result[text]=matches
        return result
    image=np.full((100,300,3),(190,215,0),dtype=np.uint8)
    fields={
        '手柄-挑战说明':words('「挑战」无伤：不被击退或击飞'),
        '手柄-挑战确认':words('确认'),
        '手柄-挑战选择提示':words('A','选择'),
    }
    monkeypatch.setattr(gamepad.GamepadTransportByCompendium,'_read_area',lambda self,screen,name:(image,fields[name]))
    operation=object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.ctx=SimpleNamespace(controller=Mock(),screen_loader=object())
    operation.last_screenshot=image
    operation.last_screenshot_time=100
    operation._challenge_confirm_attempts=0
    operation._challenge_confirm_sent_at=0
    operation._challenge_confirm_frame_time=0
    now=[100]
    monkeypatch.setattr(gamepad.time,'monotonic',lambda:now[0])
    operation.click_challenge_confirm=False
    operation.round_wait=Mock(return_value='wait')
    operation.round_fail=Mock(return_value='failed')
    operation.save_screenshot=Mock()
    operation.round_success=Mock(return_value='battle')
    assert operation._try_challenge_dialog()=='wait'
    assert operation._try_challenge_dialog()=='wait'
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    assert operation.region_type==LostVoidRegionType.CHANLLENGE_FLAWLESS
    now[0]=103
    assert operation._try_challenge_dialog()=='wait'
    operation.ctx.controller.btn_tap.assert_called_once_with('south')
    operation.last_screenshot_time=101
    assert operation._try_challenge_dialog()=='wait'
    assert operation.ctx.controller.btn_tap.call_count==2
    now[0]=106
    operation.last_screenshot_time=102
    assert operation._try_challenge_dialog()=='wait'
    assert operation.ctx.controller.btn_tap.call_count==3
    now[0]=109
    operation.last_screenshot_time=103
    assert operation._try_challenge_dialog()=='failed'
    assert operation.ctx.controller.btn_tap.call_count==3
    assert operation.init_for_region_type()=='battle'
    assert not operation.click_challenge_confirm
    fields['手柄-挑战说明']=words('是否确认退出战斗')
    assert operation._try_challenge_dialog() is None
    assert operation.ctx.controller.btn_tap.call_count==3


def test_boss_completion_banner_waits_without_input_but_has_a_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    operation=object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.last_screenshot=object()
    operation.ctx=SimpleNamespace(controller=SimpleNamespace(battle_input_blocked=True,btn_tap=Mock()))
    operation._battle_active=False
    operation.region_type=LostVoidRegionType.BOSS
    operation._boss_completion_seen=False
    operation._boss_result_wait_since=0
    operation.check_and_update_current_screen=Mock(return_value=None)
    operation.round_by_find_area=Mock(side_effect=lambda image, screen, area: SimpleNamespace(is_success=area=='手柄-调查完成'))
    operation.round_wait=Mock(return_value='wait')
    operation.round_fail=Mock(return_value='failed')
    operation.save_screenshot=Mock()
    now=[100]
    monkeypatch.setattr(gamepad.time,'monotonic',lambda:now[0])
    assert operation.in_battle()=='wait'
    now[0]=120
    assert operation.in_battle()=='wait'
    now[0]=141
    assert operation.in_battle()=='failed'
    operation.ctx.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('in_world','elapsed','expected'),[(False,0.5,'handled'),(True,0.5,'wait'),(True,3,'failed')])
def test_interaction_waits_for_menu_before_repeating_a(monkeypatch: pytest.MonkeyPatch,in_world: bool,elapsed: float,expected: str) -> None:
    operation=object.__new__(gamepad.GamepadLostVoidRunLevel)
    operation.ctx=SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=Mock(return_value=in_world)))
    operation.interact_attempted=True
    operation._interact_sent_at=100
    operation._interact_attempts=3
    operation.last_screenshot=object()
    operation.round_success=Mock(return_value='handled')
    operation.round_wait=Mock(return_value='wait')
    operation.round_fail=Mock(return_value='failed')
    operation.save_screenshot=Mock()
    base=Mock()
    monkeypatch.setattr(gamepad.LostVoidRunLevel,'try_interact',base)
    monkeypatch.setattr(gamepad.time,'monotonic',lambda:100+elapsed)
    assert operation.try_interact()==expected
    base.assert_not_called()
