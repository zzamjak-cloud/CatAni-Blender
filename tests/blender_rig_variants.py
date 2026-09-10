"""여러 리그 이름 규격의 캐릭터에 같은 모션이 오류 없이 적용되는지 검사한다."""

import json
import math
import sys
from pathlib import Path
import tempfile

import bpy
from mathutils import Vector

import bl_ext.user_default.catani as addon
from bl_ext.user_default.catani import retarget

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bvh_fixture import write_bvh

Y_AXIS = Vector((0.0, 1.0, 0.0))


def direction(obj, bone):
    return retarget._rotation(obj.matrix_world @ obj.pose.bones[bone].matrix) @ Y_AXIS

# 각 규격의 (엉덩이, 척추 3단, 목, 머리, 팔다리 템플릿, 좌, 우).
# 실제 리그가 쓰는 접두사·구분자·대소문자를 일부러 섞어 정규화 경로까지 검사한다.
VARIANTS = {
    "unreal": ("pelvis", ("spine_01", "spine_02", "spine_03"), "neck_01", "head",
               ("clavicle_{side}", "upperarm_{side}", "lowerarm_{side}", "hand_{side}", "thigh_{side}", "calf_{side}", "foot_{side}", "ball_{side}"), "l", "r"),
    "mixamo": ("mixamorig:Hips", ("mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2"), "mixamorig:Neck", "mixamorig:Head",
               ("mixamorig:{side}Shoulder", "mixamorig:{side}Arm", "mixamorig:{side}ForeArm", "mixamorig:{side}Hand",
                "mixamorig:{side}UpLeg", "mixamorig:{side}Leg", "mixamorig:{side}Foot", "mixamorig:{side}ToeBase"), "Left", "Right"),
    "biped": ("Bip01 Pelvis", ("Bip01 Spine", "Bip01 Spine1", "Bip01 Spine2"), "Bip01 Neck", "Bip01 Head",
              ("Bip01 {side} Clavicle", "Bip01 {side} UpperArm", "Bip01 {side} Forearm", "Bip01 {side} Hand",
               "Bip01 {side} Thigh", "Bip01 {side} Calf", "Bip01 {side} Foot", "Bip01 {side} Toe0"), "L", "R"),
    "daz": ("hip", ("abdomenLower", "abdomenUpper", "chestLower"), "neckLower", "head",
            ("{side}Collar", "{side}ShldrBend", "{side}ForearmBend", "{side}Hand", "{side}ThighBend", "{side}Shin", "{side}Foot", "{side}Toe"), "l", "r"),
    "cmu_asf": ("hip", ("lowerback", "upperback", "thorax"), "lowerneck", "head",
                ("{side}clavicle", "{side}humerus", "{side}radius", "{side}wrist", "{side}femur", "{side}tibia", "{side}foot", "{side}toes"), "l", "r"),
    "deform": ("DEF-spine", ("DEF-spine.001", "DEF-spine.002", "DEF-spine.003"), "DEF-neck", "DEF-head",
               ("DEF-shoulder.{side}", "DEF-upper_arm.{side}", "DEF-forearm.{side}", "DEF-hand.{side}",
                "DEF-thigh.{side}", "DEF-shin.{side}", "DEF-foot.{side}", "DEF-toe.{side}"), "L", "R"),
    # Unity 휴머노이드 계열. Bandai Namco Research 데이터셋이 이 이름을 쓴다.
    "generic": ("Hips", ("Spine", "Chest", "UpperChest"), "Neck", "Head",
                ("Shoulder_{side}", "UpperArm_{side}", "LowerArm_{side}", "Hand_{side}",
                 "UpperLeg_{side}", "LowerLeg_{side}", "Foot_{side}", "Toes_{side}"), "L", "R"),
    # 규격 표에 없는 이름. 별칭 + 계층 검증으로 메워야 한다.
    "custom": ("Waist", ("TorsoLower", "TorsoUpper", "RibCage"), "NeckLower", "Skull",
               ("{side}_Collar", "{side}_UpArm", "{side}_LowerArm", "{side}_Wrist",
                "{side}_UpperLeg", "{side}_LowerLeg", "{side}_Ankle", "{side}_Ball"), "Left", "Right"),
}

# 팔은 옆으로, 다리는 아래로 뻗은 A 자세 골격. 이름만 규격별로 바꾼다.
SKELETON = (
    ("hips", None, (0.0, 0.0, 1.00), (0.0, 0.0, 1.12)),
    ("spine_1", "hips", (0.0, 0.0, 1.12), (0.0, 0.0, 1.24)),
    ("spine_2", "spine_1", (0.0, 0.0, 1.24), (0.0, 0.0, 1.36)),
    ("spine_3", "spine_2", (0.0, 0.0, 1.36), (0.0, 0.0, 1.48)),
    ("neck", "spine_3", (0.0, 0.0, 1.48), (0.0, 0.0, 1.60)),
    ("head", "neck", (0.0, 0.0, 1.60), (0.0, 0.0, 1.78)),
)
for side, sign in (("l", 1.0), ("r", -1.0)):
    SKELETON += (
        (f"shoulder_{side}", "spine_3", (0.04 * sign, 0.0, 1.44), (0.16 * sign, 0.0, 1.46)),
        (f"arm_{side}", f"shoulder_{side}", (0.16 * sign, 0.0, 1.46), (0.44 * sign, 0.0, 1.32)),
        (f"forearm_{side}", f"arm_{side}", (0.44 * sign, 0.0, 1.32), (0.70 * sign, 0.0, 1.18)),
        (f"hand_{side}", f"forearm_{side}", (0.70 * sign, 0.0, 1.18), (0.84 * sign, 0.0, 1.10)),
        (f"thigh_{side}", "hips", (0.10 * sign, 0.0, 0.98), (0.11 * sign, 0.0, 0.54)),
        (f"shin_{side}", f"thigh_{side}", (0.11 * sign, 0.0, 0.54), (0.12 * sign, 0.0, 0.10)),
        (f"foot_{side}", f"shin_{side}", (0.12 * sign, 0.0, 0.10), (0.12 * sign, -0.10, 0.02)),
        (f"toe_{side}", f"foot_{side}", (0.12 * sign, -0.10, 0.02), (0.12 * sign, -0.20, 0.02)),
    )


def slot_names(variant):
    hips, spines, neck, head, limbs, left, right = VARIANTS[variant]
    names = {"hips": hips, "neck": neck, "head": head}
    for index, name in enumerate(spines, start=1):
        names[f"spine_{index}"] = name
    for side, token in (("l", left), ("r", right)):
        for slot, template in zip(retarget._LIMB_SLOTS, limbs):
            names[f"{slot}_{side}"] = template.format(side=token)
    return names


def build_rig(variant):
    names = slot_names(variant)
    armature = bpy.data.armatures.new(f"검사_{variant}")
    obj = bpy.data.objects.new(f"검사_{variant}", armature)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    for slot, parent, head, tail in SKELETON:
        bone = armature.edit_bones.new(names[slot])
        bone.head, bone.tail = head, tail
        bone.use_connect = False
        if parent:
            bone.parent = armature.edit_bones[names[parent]]
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj, names


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.read_homefile(use_empty=True)
temporary = tempfile.TemporaryDirectory(prefix="catani-variants-")
library = Path(temporary.name)
write_bvh(library / "walk_synth.bvh")
(library / "motions.json").write_text(json.dumps({"motions": [{
    "file": "walk_synth.bvh", "name": "합성 전신 걷기", "tags": ["walk", "synthetic"],
}]}, ensure_ascii=False), encoding="utf-8")

settings = bpy.context.scene.catani_settings
settings.motion_library_path = str(library)
settings.motion_query = "walk synthetic"
settings.frame_step = 1
# 이 검사의 대상은 본 이름 인식이므로, 곡선 간소화를 끄고 방향 오차를 그대로 잰다.
settings.simplify_error = 0.0
addon.refresh(bpy.context.scene)
assert len(settings.motions) == 1, [item.name for item in settings.motions]

summary = []
for variant in VARIANTS:
    target, names = build_rig(variant)
    settings.target_armature = target
    slots, profile, guessed = retarget.resolve_slots(target)
    assert len(slots) == 22, f"{variant}: 인식한 부위 {len(slots)}/22 · {sorted(set(retarget.SLOT_ORDER) - set(slots))}"
    for slot, expected in names.items():
        assert slots[slot] == expected, f"{variant}: {slot} → {slots[slot]} (기대 {expected})"
    assert bpy.ops.catani.motion_apply() == {"FINISHED"}, f"{variant}: {settings.motion_status}"
    pairs, _source_key, target_key, skipped, _guessed = retarget.build_pairs(
        next(obj for obj in bpy.data.objects if obj.get("catani_motion_source")), target)
    assert len(pairs) == 22 and not skipped, (variant, len(pairs), skipped)

    source = next(obj for obj in bpy.data.objects if obj.get("catani_motion_source"))
    scene = bpy.context.scene
    worst = 0.0
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for _slot, source_bone, target_bone in pairs:
            worst = max(worst, math.degrees(direction(source, source_bone).angle(direction(target, target_bone), 0.0)))
    assert worst < 0.5, f"{variant}: 본 방향 오차 {worst:.3f}°"
    assert "적용됨" in settings.motion_status, settings.motion_status
    summary.append((variant, retarget.profile_label(profile), len(guessed), round(worst, 4)))
    target.select_set(False)

for variant, label, guessed, worst in summary:
    print(f"  {variant:9s} 규격={label:22s} 별칭보완={guessed:2d} 최대오차={worst:.4f}°")
assert dict((row[0], row[2]) for row in summary)["custom"] >= 20, "규격 밖 리그를 별칭으로 메우지 못했습니다"

addon.unregister()
addon.register()
temporary.cleanup()
print(f"CATANI_PASS 리그 규격 {len(summary)}종 22부위 인식·적용·방향 오차 0.5° 미만")
