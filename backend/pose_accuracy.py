"""Manual visual audit status for built-in pose thumbnails."""
from __future__ import annotations

AUDIT_VERSION = 1

# These thumbnails were reviewed against the five criteria in the audit record.
# Deprecated is intentionally empty: none should be removed until replacement
# assets exist, because IDs may already be referenced by saved prompts.
DEPRECATED: dict[str, str] = {}

NEEDS_REWORK: dict[str, str] = {
    "group_mff_side_by_side": "人数不符：预设为 3 人，缩略图出现十余人。",
    "group_mmf_side_by_side": "人数不符：预设为 2 男 1 女，缩略图出现 2 男 2 女。",
    "group_observer_pair": "身体关系不符：三人并排，未形成一名主体与左右观察者。",
    "sm_wrist_raise_restraint": "构图不符：缩略图为多格人体展示，没有双人互动。",
    "sm_rope_frame_standing": "构图不符：缩略图为两个独立单人画面，没有两名角色。",
    "sm_wrist_cuffs_back": "构图不符：缩略图为四视图人体展示，没有双人互动。",
    "sm_kneeling_collar_display": "构图不符：缩略图为多个人体变体，没有引导角色。",
    "solo_speculum_close_view": "构图不符：特写展示脸部和手持物，未清楚呈现鸭嘴器。",
    "duo_side_by_side_contact": "构图不符：只显示躯干和大腿，未满足全身构图与两人轮廓。",
    "duo_back_to_back_seated": "构图不符：只显示上半身和臀部，未满足全身构图。",
    "partner_restraint_dilation_predicament": "人数/关系不符：画面只有一名角色和装置，没有伴侣操作。",
    "duo_ice_cube_body_trail": "人数/关系不符：画面只有一名角色，没有第二名角色滑动冰块。",
    "duo_cowgirl_piercing_control": "人数/关系不符：画面只有一名角色和饰品，没有伴侣控制。",
    "external_vibrator_control": "人数/关系不符：画面只有自我操作，没有第二名控制者。",
    "duo_multi_point_piercing_guided_release": "人数/关系不符：画面只有一名角色，没有伴侣分级解除。",
    "sensory_deprivation_blindfold_earplugs": "人数不清：玻璃反射与主体叠成多个人影，双人边界不可靠。",
    "impact_crop_inner_thigh_consensual": "接触关系不符：画面只有接受方持短鞭，没有主动方击打。",
    "wall_rear_lift": "构图不符：缩略图为两个独立画面，且第二格生殖器拼接异常。",
    "love_bite_neck_consensual": "构图不符：缩略图为两格拼图，不能作为单一连续场景。",
    "pose_slow_dance_embrace": "人数不清：前景两人后叠有重复人物，人数与身体边界混淆。",
    "hair_pull_arch_consensual": "构图不符：缩略图为两格拼图，没有单一连续动作。",
    "restraint_straps_side_lying_entry": "人数/构图不符：缩略图为同一角色的正背两视图，没有伴侣。",
    "feather_tease_sensation": "构图不符：只出现一只手，第二名角色和全身轮廓不可见。",
    "leather_paddle_short_flogger_play": "接触关系不符：两人仅并排站立，没有皮拍接触或击打关系。",
    "kneeling_face_to_face_oral": "构图不符：只显示一名角色和局部器官，未形成对跪双人体位。",
}


def audit_for(preset_id: str, *, has_image: bool) -> dict[str, str | None]:
    """Return the current audit status and actionable note."""
    if preset_id in DEPRECATED:
        return {
            "accuracy_status": "deprecated",
            "accuracy_notes": DEPRECATED[preset_id],
        }
    if not has_image:
        return {
            "accuracy_status": "needs_rework",
            "accuracy_notes": "缺少缩略图，无法完成五项视觉验收。",
        }
    if preset_id in NEEDS_REWORK:
        return {
            "accuracy_status": "needs_rework",
            "accuracy_notes": NEEDS_REWORK[preset_id],
        }
    return {
        "accuracy_status": "verified",
        "accuracy_notes": None,
    }
