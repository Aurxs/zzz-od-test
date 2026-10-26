"""用真实手册截图验证培养头像与副本标题关联。"""

from pathlib import Path
from types import SimpleNamespace

from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher, OnnxOcrParam
from one_dragon.base.screen.profile_screen_context import ProfileScreenContext
from one_dragon.utils import cv2_utils
from zzz_od.operation.gamepad.agent_training import marked_training_targets


def test_training_markers_exclude_unmarked_patrol() -> None:
    """前两行有培养头像，第三行普通副本不能被当成目标。"""
    ocr = OnnxOcrMatcher(OnnxOcrParam(use_gpu=False, det_limit_side_len=1920))
    assert ocr.init_model()
    loader = ProfileScreenContext(defer_missing_screens=True)
    loader.reload()
    loader.apply_profile_patches()
    ctx = SimpleNamespace(ocr=ocr, screen_loader=loader)
    screen = cv2_utils.read_image(str(Path(__file__).resolve().parents[3] / 'screens/快捷手册/macos_training_patrol_markers.webp'))
    try:
        assert marked_training_targets(ctx, screen, '区域巡防') == ['机师与叛甲', '怪兽与怪客']
    finally:
        ocr.cleanup()


def test_resolved_training_plan_preserves_original_identity() -> None:
    """具体副本供本场使用，原培养配置和已完成次数不会被替换。"""
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.operation.gamepad.agent_training import resolve_training_plan

    original = ChargePlanItem(category_name='区域巡防', mission_type_name='代理人方案培养', predefined_team_idx=6, plan_times=3, run_times=1)
    resolved = resolve_training_plan(original, '机师与叛甲')
    assert original.mission_type_name == '代理人方案培养'
    assert resolved.mission_type_name == '机师与叛甲'
    assert resolved.plan_id == original.plan_id
    assert (resolved.predefined_team_idx, resolved.plan_times, resolved.run_times) == (6, 3, 1)
