"""回放输入模式与画面变化，验证启动点击边界；不连接真实游戏。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest
import yaml

from one_dragon.base.geometry.rectangle import Rect
from one_dragon.base.matcher.match_result import MatchResult, MatchResultList
from one_dragon.base.matcher.template_matcher import TemplateMatcher
from one_dragon.base.screen.screen_info import ScreenInfo
from one_dragon.base.screen.template_loader import TemplateLoader
from one_dragon.utils import cv2_utils
from zzz_od.operation.enter_game.mac_bootstrap_game_session import (
    MacBootstrapGameSession,
)

SCREENS = Path(__file__).resolve().parents[3] / 'screens' / 'Mac启动'


class RecordedOcr:
    """按真实 OCR 框及平台区域回放，保留裁图后的局部坐标。"""

    def __init__(self) -> None:
        """读取同批实拍快照，不初始化 OCR 模型或游戏服务。"""
        self.metadata: dict[str, list[dict[str, str | int]]] = json.loads(
            (SCREENS / 'ios_bootstrap_ocr.json').read_text(encoding='utf-8'),
        )
        self.state: str = ''

    def crop_and_run_ocr(
        self, image: np.ndarray, rect: Rect,
    ) -> dict[str, MatchResultList]:
        """只回放完整落入请求区域的文字。"""
        results: dict[str, MatchResultList] = {}
        for item in self.metadata[self.state]:
            x, y = int(item['x']), int(item['y'])
            width, height = int(item['width']), int(item['height'])
            if not (rect.x1 <= x < x + width <= rect.x2 and rect.y1 <= y < y + height <= rect.y2):
                continue
            matches = MatchResultList()
            matches.append(MatchResult(1, x - rect.x1, y - rect.y1, width, height))
            results[str(item['text'])] = matches
        return results


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """只提供独立指针、手柄短按和带采集时间的截图接口。"""
    replay = SimpleNamespace(now=100.0, state='', texts={})
    controller = Mock(spec=['screenshot', 'btn_tap', 'gamepad'])
    controller.gamepad.is_connected = True
    controller.screenshot.side_effect = lambda: (
        replay.now, np.zeros((1080, 1920, 3), dtype=np.uint8),
    )
    loader = Mock()
    loader.get_area.side_effect = lambda screen, area: SimpleNamespace(
        rect=Rect(100, 200, 300, 400), x1=100, y1=200,
    )
    pointer = Mock(spec=['click'])
    pointer.click.return_value = True
    ctx = SimpleNamespace(
        is_game_window_ready=True, controller=controller, screen_loader=loader,
        run_context=SimpleNamespace(is_context_running=True),
    )
    operation = MacBootstrapGameSession(ctx, pointer=pointer)
    monkeypatch.setattr(operation, '_after_round_wait', Mock())
    monkeypatch.setattr('zzz_od.operation.enter_game.mac_bootstrap_game_session.time.time', lambda: replay.now)
    monkeypatch.setattr(operation, '_has_text', lambda area, text: text in replay.texts.get(area, ''))
    monkeypatch.setattr(operation, 'round_by_find_area', lambda image, screen, area: (
        operation.round_success() if (
            screen == '大世界-普通' and replay.state.startswith('world')
            or area in ('大世界-触屏操作', '大世界-菜单') and replay.state == 'world-touch'
        ) else operation.round_retry()
    ))
    replay.operation = operation
    replay.pointer = pointer
    replay.controller = controller
    return replay


def show(session: SimpleNamespace, state: str, texts: dict[str, str]) -> None:
    """每次切帧推进采集时间，动作后的旧截图不能冒充新帧。"""
    session.now += 1
    session.state = state
    session.texts = texts


def test_existing_gamepad_world_needs_no_input(session: SimpleNamespace) -> None:
    """有大世界和手柄提示时直接成功，不必打开菜单。"""
    show(session, 'world-gamepad', {'大世界-手柄提示': 'LT'})
    assert session.operation.prepare_session().is_success
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize('close_found, labels, expected', [
    (True, '目标 日常 训练 作战 战术', 1),
    (False, '目标 日常 训练 作战 战术', 0),
    (True, '目标', 0),
])
def test_touch_compendium_requires_close_and_tabs(
    session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    close_found: bool, labels: str, expected: int,
) -> None:
    """触屏关闭模板和多个手册标签必须同时存在；同一步不连点。"""
    monkeypatch.setattr(session.operation, '_area_found', lambda name: (
        name == '快捷手册-触屏关闭' and close_found
    ))
    show(session, 'handbook', {'快捷手册-顶部标签': labels})
    session.operation.prepare_session()
    session.operation.prepare_session()
    assert session.pointer.click.call_count == expected
    session.controller.btn_tap.assert_not_called()


def test_touch_switch_requires_new_frame_and_gamepad_world(
    session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """触屏路径逐帧推进；选择布局并不等于成功，返回后仍须确认大世界。"""
    monkeypatch.setattr(session.operation, '_text_rect', lambda area, target: Rect(120, 220, 180, 260))
    frames = [
        ('world-touch', {}),
        ('menu-touch', {'菜单-底部': '仓库 更多'}),
        ('settings-touch', {'设置-侧栏': '声音/触觉'}),
        ('input-touch', {'输入-UI布局': 'UI布局', '输入-当前布局': '触屏'}),
        ('input-options', {'输入-UI布局': 'UI布局', '输入-当前布局': '触屏', '输入-布局选项': '触屏 手柄'}),
        ('input-gamepad', {'输入-UI布局': 'UI布局', '输入-当前布局': '手柄'}),
        ('menu-gamepad', {'菜单-底部': '仓库 更多', '手柄-返回提示': 'B'}),
    ]
    for state, texts in frames:
        show(session, state, texts)
        assert not session.operation.prepare_session().is_success
        call_count = session.pointer.click.call_count
        assert not session.operation.prepare_session().is_success
        assert session.pointer.click.call_count == call_count
    assert session.pointer.click.call_count == 5
    assert session.controller.btn_tap.call_args_list == [call('east'), call('east')]
    show(session, 'world-gamepad', {'大世界-手柄提示': 'LT'})
    assert session.operation.prepare_session().is_success


def test_unknown_screen_and_absent_gamepad_option_fail_without_input(
    session: SimpleNamespace,
) -> None:
    """未知页最多观察八帧；没有手柄选项时不猜点击。"""
    for _ in range(7):
        show(session, 'unknown', {})
        assert not session.operation.prepare_session().is_fail
    show(session, 'unknown', {})
    assert session.operation.prepare_session().is_fail
    show(session, 'input-touch-only', {
        '输入-UI布局': 'UI布局', '输入-当前布局': '触屏', '输入-布局选项': '触屏',
    })
    assert '没有手柄选项' in session.operation.prepare_session().status
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


def test_cold_start_waits_at_most_sixty_seconds_without_input(session: SimpleNamespace) -> None:
    """只有本次真实新启动标记允许更久被动等待，超时不点击未知页面。"""
    session.controller.started_game_this_run = True
    session.operation.handle_init()
    for _ in range(9):
        show(session, 'unknown', {})
        assert not session.operation.prepare_session().is_fail
    session.now = 159.9
    assert not session.operation.prepare_session().is_fail
    session.now = 160
    result = session.operation.prepare_session()
    assert result.is_fail
    assert '等待60秒' in result.status
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


def test_posted_click_without_ui_change_fails_after_five_seconds(session: SimpleNamespace) -> None:
    """定向投递返回成功不能代替截图确认，也不能重复连点。"""
    show(session, 'world-touch', {})
    assert not session.operation.prepare_session().is_success
    session.now += 6
    result = session.operation.prepare_session()
    assert result.is_fail
    assert '没有按预期变化' in result.status
    session.pointer.click.assert_called_once()


def test_ui_frame_during_click_is_valid_after_cursor_restore(session: SimpleNamespace) -> None:
    """UI 在鼠标恢复前已更新后进入静态 Idle，仍须接受这张实际新像素帧。"""
    def post(x: float, y: float) -> bool:
        """模拟事件已生效但前台恢复还占用三百毫秒。"""
        session.now += 0.3
        return True

    session.pointer.click.side_effect = post
    show(session, 'world-touch', {})
    started_at = session.now
    assert not session.operation.prepare_session().is_success
    session.state = 'input-gamepad'
    session.texts = {'输入-UI布局': 'UI布局', '输入-当前布局': '手柄'}
    session.controller.screenshot.side_effect = lambda: (
        started_at + 0.1, np.zeros((1080, 1920, 3), dtype=np.uint8),
    )
    assert not session.operation.prepare_session().is_fail
    session.controller.btn_tap.assert_called_once_with('east')


def test_unavailable_session_or_paused_run_sends_no_input(session: SimpleNamespace) -> None:
    """窗口和连接未就绪或运行已停止时，独立指针也不能发送输入。"""
    operation = session.operation
    operation.ctx.is_game_window_ready = False
    assert operation.prepare_session().is_fail
    session.controller.screenshot.assert_not_called()
    operation.ctx.is_game_window_ready = True
    session.controller.gamepad.is_connected = False
    assert operation.prepare_session().is_fail
    session.controller.gamepad.is_connected = True
    operation.ctx.run_context.is_context_running = False
    show(session, 'world-touch', {})
    assert operation.prepare_session().is_fail
    session.pointer.click.assert_not_called()


def test_ocr_click_uses_offset_of_actual_text_box(
    session: SimpleNamespace,
) -> None:
    """文字点击使用当帧 OCR 框中心和区域偏移，不能点击整块列表中心。"""
    matches = MatchResultList()
    matches.append(MatchResult(1, 20, 30, 60, 40))
    session.operation.ctx.ocr = Mock()
    session.operation.ctx.ocr.crop_and_run_ocr.return_value = {'手柄': matches}
    session.operation.last_screenshot = np.zeros((1080, 1920, 3), dtype=np.uint8)
    rect = session.operation._text_rect('输入-布局选项', '手柄')
    assert rect == Rect(120, 230, 180, 270)


def test_real_frames_prepare_gamepad_without_assuming_pc_touch_layout(
    session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用真实模板、平台区域和 OCR 框回放触屏路径，最后确认手柄大世界。"""
    root = Path(__file__).resolve().parents[4]
    patch_path = root / (
        'assets/game_data/platform/ios_gamepad/screen_patches/macos_bootstrap.yml'
    )
    screen = ScreenInfo(yaml.safe_load(patch_path.read_text(encoding='utf-8'))['screen'])
    world = ScreenInfo(yaml.safe_load(
        (root / 'assets/game_data/screen_info/normal_world_basic.yml').read_text(encoding='utf-8'),
    ))
    areas = {
        (item.screen_name, area.area_name): area
        for item in (screen, world) for area in item.area_list
    }
    session.operation.ctx.screen_loader.get_area.side_effect = lambda name, area: areas.get((name, area))
    session.operation.ctx.tm = TemplateMatcher(TemplateLoader())
    recorded_ocr = RecordedOcr()
    session.operation.ctx.ocr = recorded_ocr
    monkeypatch.setattr(
        session.operation, '_has_text',
        MacBootstrapGameSession._has_text.__get__(session.operation),
    )
    monkeypatch.setattr(
        session.operation, 'round_by_find_area',
        MacBootstrapGameSession.round_by_find_area.__get__(session.operation),
    )
    session.controller.screenshot.side_effect = lambda: (
        session.now, cv2_utils.read_image(str(SCREENS / f'{recorded_ocr.state}.webp')),
    )
    for state, expected_point in (
        ('ios_world_touch', (163, 91)),
        ('ios_menu_touch', (600, 950)),
        ('ios_settings_touch', None),
        ('ios_input_touch', (1372, 286)),
        ('ios_input_options_touch', (1543, 464)),
    ):
        recorded_ocr.state = state
        show(session, state, {})
        result = session.operation.prepare_session()
        assert not result.is_success and not result.is_fail, result.status
        if expected_point is not None:
            session.pointer.click.assert_called_with(*expected_point)
        session.controller.btn_tap.assert_not_called()

    recorded_ocr.state = 'ios_input_gamepad'
    show(session, recorded_ocr.state, {})
    result = session.operation.prepare_session()
    assert not result.is_success and not result.is_fail, result.status
    session.controller.btn_tap.assert_called_once_with('east')
    assert session.pointer.click.call_count == 5

    recorded_ocr.state = 'ios_world_gamepad'
    show(session, recorded_ocr.state, {})
    assert session.operation.prepare_session().is_success
    assert not session.operation._area_found('大世界-触屏操作')
    assert not session.operation._area_found('大世界-菜单')


@pytest.mark.parametrize('already_gamepad', [True, False])
def test_real_login_frames_use_gamepad_first_and_enter_saved_account(
    session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, already_gamepad: bool,
) -> None:
    """两种实拍登录路径都只进入一次；已是手柄时不发送鼠标输入。"""
    root = Path(__file__).resolve().parents[4]
    patch = yaml.safe_load((root / (
        'assets/game_data/platform/ios_gamepad/screen_patches/macos_bootstrap.yml'
    )).read_text(encoding='utf-8'))
    screen = ScreenInfo(patch['screen'])
    world = ScreenInfo(yaml.safe_load(
        (root / 'assets/game_data/screen_info/normal_world_basic.yml').read_text(encoding='utf-8'),
    ))
    areas = {
        (item.screen_name, area.area_name): area
        for item in (screen, world) for area in item.area_list
    }
    operation = session.operation
    operation.ctx.screen_loader.get_area.side_effect = lambda name, area: areas.get((name, area))
    operation.ctx.tm = TemplateMatcher(TemplateLoader())
    recorded_ocr = RecordedOcr()
    operation.ctx.ocr = recorded_ocr
    session.controller.started_game_this_run = True
    operation.handle_init()
    for method in ('_has_text', 'round_by_find_area'):
        monkeypatch.setattr(operation, method, getattr(MacBootstrapGameSession, method).__get__(operation))
    session.controller.screenshot.side_effect = lambda: (
        session.now, cv2_utils.read_image(str(SCREENS / f'{recorded_ocr.state}.webp')),
    )
    if not already_gamepad:
        for state, expected_point in (
            ('ios_login_touch', (1797, 761)),
            ('ios_login_settings_touch', (263, 375)),
            ('ios_login_input_touch', (1373, 319)),
            ('ios_login_input_options_touch', (1543, 495)),
            ('ios_login_input_gamepad', None),
        ):
            recorded_ocr.state = state
            show(session, state, {})
            result = operation.prepare_session()
            assert not result.is_success and not result.is_fail, result.status
            if expected_point is not None:
                session.pointer.click.assert_called_with(*expected_point)

    recorded_ocr.state = 'ios_login_gamepad'
    show(session, recorded_ocr.state, {})
    assert not operation.prepare_session().is_fail
    assert not operation.prepare_session().is_fail
    recorded_ocr.state = 'ios_cold_login_world'
    show(session, recorded_ocr.state, {})
    assert operation.prepare_session().is_success
    assert session.controller.btn_tap.call_args_list == (
        [call('south')] if already_gamepad else [call('east'), call('south')]
    )
    assert session.pointer.click.call_count == (0 if already_gamepad else 4)


def test_login_wait_is_bounded_and_credentials_require_paired_prompts(
    session: SimpleNamespace,
) -> None:
    """普通字幕里的单词不会误拦；明确凭据组合零输入停止，加载不重复进入。"""
    show(session, 'unknown', {'登录-凭据提示': '验证码'})
    assert not session.operation.prepare_session().is_fail
    show(session, 'unknown', {'登录-凭据提示': '输入手机号注册/登录 验证码'})
    assert session.operation.prepare_session().is_fail
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()

    session.texts = {}
    session.operation._login_wait_until = session.now + 60
    session.now += 59
    assert not session.operation.prepare_session().is_fail
    session.now += 1
    assert '等待60秒' in session.operation.prepare_session().status



def test_optional_login_event_claims_confirms_then_returns(session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """可选活动依次核对领取页、获得弹窗、返回页，未出现时不发按键。"""
    monkeypatch.setattr(session.operation, 'save_screenshot', Mock())
    match = MatchResultList()
    match.append(MatchResult(1, 30, 40, 60, 30))
    monkeypatch.setattr(session.operation, '_read_area', lambda name: {'领取×01': match, '确认': match})
    monkeypatch.setattr('zzz_od.operation.enter_game.mac_bootstrap_game_session.has_filled_highlight', lambda *args: True)
    session.operation.ctx.screen_loader.get_area.side_effect = lambda *args: SimpleNamespace(
        rect=Rect(100, 200, 300, 400), x1=100, y1=200, x2=300, y2=400,
    )
    show(session, 'unknown', {})
    session.operation.prepare_session()
    session.controller.btn_tap.assert_not_called()
    event = {'登录后-活动说明': '全新放送 累计登录7天', '登录后-活动按键': 'A 选择 B 返回'}
    for _ in range(2):
        show(session, 'event', event)
        session.operation.prepare_session()
    session.controller.btn_tap.assert_called_once_with('south')
    show(session, 'reward', {'登录后-获得奖励': '获得 确认 选择'})
    session.operation.prepare_session()
    show(session, 'event', event)
    session.operation.prepare_session()
    assert session.controller.btn_tap.call_args_list == [call('south'), call('south'), call('east')]
    session.pointer.click.assert_not_called()


def test_world_lt_template_confirms_without_ocr(session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """小提示 OCR 缺失时，明确 LT 图标和大世界证据一起确认手柄。"""
    show(session, 'world-gamepad', {})
    monkeypatch.setattr(session.operation, '_area_found', lambda name: name == '大世界-手柄LT图标')
    assert session.operation.prepare_session().is_success
    session.pointer.click.assert_not_called()
    session.controller.btn_tap.assert_not_called()


@pytest.mark.parametrize(('state', 'expected'), [('ios_world_gamepad_lt_small', True), ('ios_world_touch', False)])
def test_world_lt_template_matches_only_gamepad(state: str, expected: bool) -> None:
    """实拍手柄提示命中，触屏大世界不误判。"""
    matcher = TemplateMatcher(TemplateLoader())
    screen = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
    part = cv2_utils.crop_image_only(screen, Rect(1798, 104, 1853, 154))
    matches = matcher.match_template(part, 'ios_gamepad', 'bootstrap_world_lt', threshold=0.9)
    assert (matches.max is not None) is expected


def test_real_touch_compendium_close_template() -> None:
    """触屏手册关闭图标须来自实拍匹配，其他启动画面不能误命中。"""
    matcher = TemplateMatcher(TemplateLoader())
    for state, expected in [('ios_touch_compendium', True), ('ios_world_gamepad_lt_small', False)]:
        screen = cv2_utils.read_image(str(SCREENS / f'{state}.webp'))
        part = cv2_utils.crop_image_only(screen, Rect(1775, 210, 1855, 290))
        matches = matcher.match_template(part, 'ios_gamepad', 'bootstrap_touch_compendium_close', threshold=0.9)
        assert (matches.max is not None) is expected
