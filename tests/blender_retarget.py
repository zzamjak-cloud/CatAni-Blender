"""합성 CMU 규격 BVH를 캐릭터에 적용하고 결과가 실제로 맞는지 수치로 검사한다."""

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
from bvh_fixture import FRAMES, TREE, write_bvh

Y_AXIS = Vector((0.0, 1.0, 0.0))

def direction(obj, bone):
    return retarget._rotation(obj.matrix_world @ obj.pose.bones[bone].matrix) @ Y_AXIS


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
temporary = tempfile.TemporaryDirectory(prefix="catani-retarget-")
library = Path(temporary.name)
joints = write_bvh(library / "walk_synth.bvh")
(library / "motions.json").write_text(json.dumps({"motions": [{
    "file": "walk_synth.bvh", "name": "합성 전신 걷기", "tags": ["walk", "synthetic"],
    "description": "리타게팅 검사용 합성 CMU 규격 모션",
}]}, ensure_ascii=False), encoding="utf-8")

target = bpy.data.objects["Amature_Player"]
rest_hips = (target.matrix_world @ target.data.bones["spine"].matrix_local).translation.copy()
previous_action = target.animation_data.action
live_tracks = [track.name for track in target.animation_data.nla_tracks if not track.mute]
assert live_tracks, "NLA가 적용을 덮는 상황을 검사하려면 살아 있는 트랙이 필요합니다"

settings = bpy.context.scene.catani_settings
settings.motion_library_path = str(library)
settings.motion_query = "walk synthetic"
addon.refresh(bpy.context.scene)
assert len(settings.motions) == 1, [item.name for item in settings.motions]
assert settings.motions[0].name == "합성 전신 걷기"
settings.target_armature = target
settings.frame_step = 1
# 1~7번은 프레임마다 샘플값과 정확히 맞는지 보는 검사이므로 간소화를 끄고 잰다.
settings.simplify_error = 0.0

before = set(bpy.data.objects)
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
created = [obj for obj in bpy.data.objects if obj not in before]
source = next(obj for obj in created if obj.type == "ARMATURE")
# 첫 적용에서만 NLA를 음소거하므로 그때의 리포트를 따로 보관한다.
first_report = settings.apply_report

# 1. 22개 부위가 모두 짝지어졌는지.
pairs, source_key, target_key, _skipped, _guessed = retarget.build_pairs(source, target)
assert (source_key, target_key) == ("cmu", "rigify"), (source_key, target_key)
assert len(pairs) == 22, len(pairs)

# 2. 모든 프레임에서 캐릭터 본이 모션 본과 같은 방향을 보는지.
scene = bpy.context.scene
# BVH를 장면 FPS로 다시 샘플링하므로 원본 프레임 수보다 늘어날 수 있다.
assert scene.frame_start == 1 and scene.frame_end >= FRAMES, (scene.frame_start, scene.frame_end)
span = scene.frame_end - scene.frame_start + 1
worst = 0.0
moved = {name: 0.0 for _slot, _src, name in pairs}
first = {}
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for _slot, source_bone, target_bone in pairs:
        from_source, from_target = direction(source, source_bone), direction(target, target_bone)
        worst = max(worst, math.degrees(from_source.angle(from_target, 0.0)))
        first.setdefault(target_bone, from_target.copy())
        moved[target_bone] = max(moved[target_bone], math.degrees(first[target_bone].angle(from_target, 0.0)))
assert worst < 0.5, f"본 방향이 모션과 어긋났습니다: 최대 {worst:.3f}°"
assert sum(1 for value in moved.values() if value > 3.0) >= 6, f"실제로 움직인 본이 너무 적습니다: {moved}"

# 3. 캐릭터가 공중에 뜨거나 바닥을 파고들지 않는지.
foot_bones = [name for slot, _source, name in pairs if slot.startswith(("foot", "toe"))]
rest_floor = retarget._lowest_rest(target, target.matrix_world.copy(), foot_bones)
lowest = None
heights = []
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    heights.append((target.matrix_world @ target.pose.bones["spine"].matrix).translation.z)
    for name in foot_bones:
        matrix = target.matrix_world @ target.pose.bones[name].matrix
        for point in (matrix.translation, matrix @ Vector((0.0, target.pose.bones[name].bone.length, 0.0))):
            lowest = point.z if lowest is None else min(lowest, point.z)
assert lowest >= rest_floor - 1e-4, f"발이 바닥을 파고들었습니다: {lowest:.4f} < {rest_floor:.4f}"
assert max(abs(value - rest_hips.z) for value in heights) < 0.25, heights

# 접지 보정을 끄면 첫 프레임 엉덩이는 레스트 위치와 정확히 같아야 한다.
settings.ground_contact = False
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
scene.frame_set(scene.frame_start)
bpy.context.view_layer.update()
start_hips = (target.matrix_world @ target.pose.bones["spine"].matrix).translation
assert (start_hips - rest_hips).length < 1e-4, f"첫 프레임 엉덩이 위치가 레스트와 다릅니다: {(start_hips - rest_hips).length:.4f}"
settings.ground_contact = True
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status

# 4. 덮어쓰기 요인을 실제로 차단했는지.
assert all(track.mute for track in target.animation_data.nla_tracks), "NLA 트랙이 여전히 결과를 덮습니다"
for bone in target.pose.bones:
    for constraint in bone.constraints:
        if constraint.type == "IK":
            assert constraint.influence == 0.0, f"{bone.name} IK가 구운 FK를 덮습니다"
assert previous_action.use_fake_user, "이전 Action이 보존되지 않았습니다"
assert target.animation_data.action != previous_action
assert "NLA 트랙 음소거" in first_report, first_report
assert "방향 오차" in settings.motion_status and "적용됨" in settings.motion_status
for token in ("본 매핑: 22", "규격: CMU / cgspeed BVH → Rigify / Player v1", "검증:"):
    assert token in settings.apply_report, token

# 5. 같은 모션을 다시 적용해도 원본을 중복 가져오지 않는지.
count = len(bpy.data.objects)
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
assert len(bpy.data.objects) == count, "같은 모션을 다시 적용할 때 원본 리그가 중복되었습니다"

# 6. 짝지을 본이 없으면 장면을 바꾸지 않고 실패하는지.
lonely = bpy.data.objects.new("CatAni_검사_빈리그", bpy.data.armatures.new("CatAni_검사_빈리그"))
scene.collection.objects.link(lonely)
try:
    retarget.build_pairs(lonely, target)
except ValueError as error:
    assert "지원 규격" in str(error), str(error)
else:
    raise AssertionError("본 이름이 맞지 않는 리그가 통과했습니다")
try:
    retarget.apply_motion(bpy.context, source, source)
except ValueError as error:
    assert "같은 오브젝트" in str(error), str(error)
else:
    raise AssertionError("모션 리그를 자기 자신에 적용하는 경로가 통과했습니다")

# 7. 프레임 간격을 늘리면 키가 줄어드는지.
settings.frame_step = 4
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
sparse = target.animation_data.action
counts = {len(curve.keyframe_points) for layer in sparse.layers for strip in layer.strips
          for bag in strip.channelbags for curve in bag.fcurves if "rotation_quaternion" in curve.data_path}
expected = len(range(1, span + 1, 4))
assert counts == {expected}, (counts, expected, span)
assert expected < span, (expected, span)
assert f"간격 4" in settings.apply_report, settings.apply_report
assert "곡선 간소화: 없음" in settings.apply_report, settings.apply_report

# 8. 곡선 간소화를 켜면 키가 줄고 편집 가능한 베지어가 되며, 오차가 허용치 안에 머무는지.
settings.frame_step = 1
settings.simplify_error = math.radians(retarget.DEFAULT_SIMPLIFY)
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
simplified_action = target.animation_data.action
rotation_curves = [curve for layer in simplified_action.layers for strip in layer.strips
                   for bag in strip.channelbags for curve in bag.fcurves
                   if "rotation_quaternion" in curve.data_path]
assert len(rotation_curves) == len(pairs) * 4, len(rotation_curves)
simplified_keys = sum(len(curve.keyframe_points) for curve in rotation_curves)
dense_keys = span * len(rotation_curves)
assert simplified_keys < dense_keys * 0.5, f"키가 충분히 줄지 않았습니다: {simplified_keys} / {dense_keys}"
assert all(key.interpolation == "BEZIER" for curve in rotation_curves for key in curve.keyframe_points)
assert all(key.handle_left_type == "AUTO_CLAMPED" and key.handle_right_type == "AUTO_CLAMPED"
           for curve in rotation_curves for key in curve.keyframe_points)
# 한 부위의 쿼터니언 4채널은 키 위치가 같아야 중간 프레임에서 회전이 뒤틀리지 않는다.
channel_frames = {}
for curve in rotation_curves:
    channel_frames.setdefault(curve.data_path, set()).add(tuple(round(key.co.x, 4) for key in curve.keyframe_points))
mismatched = [path_name for path_name, keys in channel_frames.items() if len(keys) != 1]
assert not mismatched, f"4채널 키 위치가 어긋난 부위: {mismatched}"
worst_simplified = 0.0
lowest_simplified = None
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for _slot, source_bone, target_bone in pairs:
        gap = direction(source, source_bone).angle(direction(target, target_bone), 0.0)
        worst_simplified = max(worst_simplified, math.degrees(gap))
    for name in foot_bones:
        matrix = target.matrix_world @ target.pose.bones[name].matrix
        for point in (matrix.translation, matrix @ Vector((0.0, target.pose.bones[name].bone.length, 0.0))):
            lowest_simplified = point.z if lowest_simplified is None else min(lowest_simplified, point.z)
# 부위별 허용치는 0.25°지만 세계 방향 오차는 부모 체인을 따라 누적된다.
assert worst_simplified < 3.0, f"간소화 후 방향 오차가 너무 큽니다: {worst_simplified:.3f}°"
assert lowest_simplified >= rest_floor - 0.02, f"간소화가 발을 바닥 아래로 내렸습니다: {lowest_simplified:.4f} < {rest_floor:.4f}"
assert f"곡선 간소화: 허용 오차 {retarget.DEFAULT_SIMPLIFY:.2f}°" in settings.apply_report, settings.apply_report
assert "% 감소)" in settings.apply_report, settings.apply_report

addon.unregister()
addon.register()
temporary.cleanup()
print(f"CATANI_PASS 합성 CMU BVH 22부위 리타게팅·최대 방향 오차 {worst:.4f}°·접지·NLA/IK 차단·재적용·실패 경로·"
      f"간소화 키 {simplified_keys}/{dense_keys}개 방향 오차 {worst_simplified:.4f}°")
