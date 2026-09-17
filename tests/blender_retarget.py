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
# 1~8번은 FK 경로를 검사한다. IK 전환은 9번에서 따로 본다.
settings.use_ik = False
settings.smooth_window = 0

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
# 모션 파일이 길이를 담고 있지 않아 가져오기가 방향을 지어낸 본은 그 방향에 맞추지
# 않으므로 비교에서 뺀다. 굽기 쪽 verify()도 같은 기준으로 센다.
aimed = [item for item in pairs if not retarget._invented_direction(source, source.data.bones[item[1]])]
assert len(aimed) < len(pairs), "검사용 BVH에 방향을 알 수 없는 관절이 있어야 한다"
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for _slot, source_bone, target_bone in pairs:
        from_target = direction(target, target_bone)
        first.setdefault(target_bone, from_target.copy())
        moved[target_bone] = max(moved[target_bone], math.degrees(first[target_bone].angle(from_target, 0.0)))
    for _slot, source_bone, target_bone in aimed:
        from_source, from_target = direction(source, source_bone), direction(target, target_bone)
        worst = max(worst, math.degrees(from_source.angle(from_target, 0.0)))
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
assert simplified_keys < dense_keys * 0.25, f"키가 충분히 줄지 않았습니다: {simplified_keys} / {dense_keys}"
assert all(key.interpolation == "BEZIER" for curve in rotation_curves for key in curve.keyframe_points)
# 최소제곱으로 접선을 직접 맞추므로 자동 핸들이 아니라 자유 핸들을 쓴다.
assert all(key.handle_left_type == "FREE" and key.handle_right_type == "FREE"
           for curve in rotation_curves for key in curve.keyframe_points)
# 핸들 x는 구간의 1/3 지점이어야 x(t)가 선형이고 우리 계산과 Blender 평가가 일치한다.
for curve in rotation_curves:
    points = curve.keyframe_points
    for position in range(len(points) - 1):
        width = points[position + 1].co.x - points[position].co.x
        assert abs(points[position].handle_right.x - (points[position].co.x + width / 3.0)) < 1e-3
        assert abs(points[position + 1].handle_left.x - (points[position + 1].co.x - width / 3.0)) < 1e-3
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
    for _slot, source_bone, target_bone in aimed:
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

# 9. IK로 전환하면 리그의 컨스트레인트에서 체인을 읽어 IK 컨트롤 본을 굽는지.
setups = retarget.ik_setups(target)
assert len(setups) == 4, [s["control"] for s in setups]
assert {s["control"] for s in setups} == {"IK_Arm.L", "IK_Arm.R", "IK_Target.L", "IK_Target.R"}
for setup in setups:
    # 컨트롤 본이 체인 아래에 있으면 값을 쓰는 순간 순환이 되므로 걸러져야 한다.
    lineage = {p.name for p in target.pose.bones[setup["control"]].parent_recursive} | {setup["control"]}
    assert not (lineage & set(setup["chain"])), setup
chain_bones = {name for setup in setups for name in setup["chain"]}

settings.use_ik = True
settings.simplify_error = 0.0
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
ik_action = target.animation_data.action
paths = {curve.data_path for layer in ik_action.layers for strip in layer.strips
         for bag in strip.channelbags for curve in bag.fcurves}
for setup in setups:
    assert f'pose.bones["{setup["control"]}"].location' in paths, setup["control"]
    assert f'pose.bones["{setup["pole"]}"].location' in paths, setup["pole"]
# IK가 직접 푸는 체인 본에는 FK 회전 키를 남기지 않는다.
for name in chain_bones:
    assert f'pose.bones["{name}"].rotation_quaternion' not in paths, name
# IK 영향은 1로 되돌려야 컨트롤 본이 실제로 동작한다.
for bone in target.pose.bones:
    for constraint in bone.constraints:
        if constraint.type == "IK":
            assert constraint.influence == 1.0, f"{bone.name} IK 영향이 켜지지 않았습니다"

# 간소화를 끈 IK 결과는 FK와 같은 자리에 놓여야 한다. 발 고정은 원본 발이 멈춘 구간에서
# 발을 FK와 다른 자리에 붙잡으므로, 이 정확 재현 검사는 발 고정을 끄고 잰다.
if bpy.ops.object.mode_set.poll():
    bpy.ops.object.mode_set(mode="OBJECT")
retarget.apply_motion(bpy.context, source, target, use_ik=True, simplify=0.0, anchor_feet=False, name="IK 발 고정 끔")
ik_worst = 0.0
ik_lowest = None
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for _slot, source_bone, target_bone in aimed:
        gap = direction(source, source_bone).angle(direction(target, target_bone), 0.0)
        ik_worst = max(ik_worst, math.degrees(gap))
    for name in foot_bones:
        matrix = target.matrix_world @ target.pose.bones[name].matrix
        for point in (matrix.translation, matrix @ Vector((0.0, target.pose.bones[name].bone.length, 0.0))):
            ik_lowest = point.z if ik_lowest is None else min(ik_lowest, point.z)
# 거의 펴진 관절(합성 걷기의 다리·오른팔은 굽힘 0, 왼팔은 최소 1.7°)에서는 폴이 실측 무릎
# 방향 대신 루트 본의 비틀림을 따르므로 FK와 정확히 같지 않다. 실측 1.19°(왼팔, 굽힘 1.7°).
assert ik_worst < 2.0, f"IK 전환이 FK와 어긋났습니다: 최대 {ik_worst:.3f}°"
assert ik_lowest >= rest_floor - 1e-3, f"IK 전환에서 발이 바닥을 파고들었습니다: {ik_lowest:.4f}"
for token in ("IK로 전환", "목표 위치 오차", "중간 관절 오차", "폴 각도 실측 보정"):
    assert token in settings.apply_report, token

# IK 컨스트레인트가 없는 리그에서는 조용히 FK로 돌아가야 한다.
# 컨스트레인트는 아마추어 데이터가 아니라 오브젝트의 포즈 본에 붙으므로,
# 데이터를 복사해 만든 새 오브젝트에는 IK가 없다.
plain = bpy.data.objects.new("CatAni_검사_IK없음", target.data.copy())
scene.collection.objects.link(plain)
bpy.context.view_layer.update()
assert not any(c.type == "IK" for bone in plain.pose.bones for c in bone.constraints)
assert not retarget.ik_setups(plain), "IK가 없는 리그에서 구성이 잡혔습니다"
settings.target_armature = plain
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
assert "쓸 수 있는 IK 컨스트레인트가 없어" in settings.apply_report, settings.apply_report
settings.target_armature = target

# 10번: 정면 정렬. 캡처 방향이 90° 돌아간 모션도 첫 프레임은 캐릭터 정면을 봐야 한다.
write_bvh(library / "walk_yaw.bvh", yaw=90.0)
before_yaw = set(bpy.data.objects)
assert bpy.ops.import_anim.bvh(filepath=str(library / "walk_yaw.bvh"), target="ARMATURE", frame_start=1,
                               use_fps_scale=True, update_scene_fps=False, update_scene_duration=False) == {"FINISHED"}
yawed = next(obj for obj in bpy.data.objects if obj not in before_yaw and obj.type == "ARMATURE")
hips_bone = next(bone for slot, _source, bone in retarget.build_pairs(yawed, target)[0] if slot == "hips")
rest_side = retarget._rotation(target.matrix_world @ target.data.bones[hips_bone].matrix_local) @ Vector((1.0, 0.0, 0.0))


def facing_offset(frame):
    """캐릭터 엉덩이의 좌우 축이 레스트 대비 몇 도 돌아가 있는지 잰다."""
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    side = retarget._rotation(evaluated.matrix_world @ evaluated.pose.bones[hips_bone].matrix) @ Vector((1.0, 0.0, 0.0))
    turn = math.atan2(side.y, side.x) - math.atan2(rest_side.y, rest_side.x)
    return math.degrees((turn + math.pi) % math.tau - math.pi)


loose = retarget.apply_motion(bpy.context, yawed, target, use_ik=False, align_facing=False, name="정렬 끔")
skew = facing_offset(loose["frame_start"])
assert not loose["align_facing"] and abs(loose["facing_angle"]) < 1e-9, loose["facing_angle"]
assert abs(abs(skew) - 90.0) < 12.0, f"정렬을 끄면 모션의 캡처 방향이 그대로 남아야 합니다: {skew:.2f}°"
tight = retarget.apply_motion(bpy.context, yawed, target, use_ik=False, align_facing=True, name="정렬 켬")
aligned = facing_offset(tight["frame_start"])
assert tight["align_facing"], tight
assert abs(aligned) < 0.5, f"정면 정렬 뒤 첫 프레임이 캐릭터 정면을 봐야 합니다: {aligned:.2f}°"
assert abs(abs(tight["facing_angle"]) - abs(skew)) < 0.5, (tight["facing_angle"], skew)
# 정렬은 방위만 돌리므로 모션 충실도(검증 오차)를 흔들면 안 된다.
assert abs(tight["max_direction_error"] - loose["max_direction_error"]) < 0.01, (tight["max_direction_error"], loose["max_direction_error"])
bpy.data.objects.remove(yawed)

# 12번 준비: 지어낸 방향 판별기가 두 형태를 모두 잡고 진짜 짧은 본은 놓아주는지.
probe_armature = bpy.data.armatures.new("CatAni 판별 검사")
probe_object = bpy.data.objects.new("CatAni 판별 검사", probe_armature)
scene.collection.objects.link(probe_object)
bpy.context.view_layer.objects.active = probe_object
bpy.ops.object.mode_set(mode="EDIT")
long_bone = probe_armature.edit_bones.new("long")
long_bone.head, long_bone.tail = (0.0, 0.0, 0.0), (0.0, 10.0, 0.0)
stub = probe_armature.edit_bones.new("stub")           # End Site 없는 말단
stub.head, stub.tail, stub.parent = (0.0, 10.0, 0.0), (0.0, 10.05, 0.0), long_bone
short = probe_armature.edit_bones.new("short")         # 진짜 짧은 본(발끝)
short.head, short.tail, short.parent = (1.0, 10.0, 0.0), (1.0, 11.5, 0.0), long_bone
overlap = probe_armature.edit_bones.new("overlap")     # 자식이 제 머리에 겹친 관절
overlap.head, overlap.tail, overlap.parent = (2.0, 0.0, 0.0), (2.0, 0.1, 0.0), long_bone
twin = probe_armature.edit_bones.new("twin")
twin.head, twin.tail, twin.parent = (2.0, 0.0, 0.0), (5.0, 0.0, 0.0), overlap
bpy.ops.object.mode_set(mode="OBJECT")
assert retarget._invented_direction(probe_object, probe_armature.bones["stub"]), "End Site 없는 말단을 놓쳤습니다"
assert retarget._invented_direction(probe_object, probe_armature.bones["overlap"]), "겹친 자식 관절을 놓쳤습니다"
assert not retarget._invented_direction(probe_object, probe_armature.bones["short"]), "진짜 짧은 본을 잘못 걸렀습니다"
assert not retarget._invented_direction(probe_object, probe_armature.bones["long"])
bpy.data.objects.remove(probe_object)
bpy.data.armatures.remove(probe_armature)
bpy.context.view_layer.objects.active = target

# 12번: 모션 파일이 손 관절의 길이를 담고 있지 않을 때(CMU가 그렇다) 가져오기가 지어낸
# 방향에 캐릭터 손을 맞추면 손목이 통째로 꺾인다. 손목 굽힘이 원본과 같아야 한다.
hand_source, hand_target = next((s_bone, t_bone) for slot, s_bone, t_bone in pairs if slot == "hand_l")
fore_source, fore_target = next((s_bone, t_bone) for slot, s_bone, t_bone in pairs if slot == "forearm_l")
assert retarget._invented_direction(source, source.data.bones[hand_source]),     "검사용 BVH의 손 관절은 방향을 알 수 없어야 한다"
assert not retarget._invented_direction(source, source.data.bones[fore_source])


def wrist(armature, evaluated, child, parent):
    """부모 대비 자식 회전이 레스트에서 벗어난 각도(도). 리그 규격과 무관하게 비교된다."""
    rest = (retarget._rotation(armature.matrix_world @ armature.data.bones[parent].matrix_local).inverted()
            @ retarget._rotation(armature.matrix_world @ armature.data.bones[child].matrix_local))
    live = (retarget._rotation(evaluated.matrix_world @ evaluated.pose.bones[parent].matrix).inverted()
            @ retarget._rotation(evaluated.matrix_world @ evaluated.pose.bones[child].matrix))
    turn = (rest.inverted() @ live).angle
    return math.degrees(min(turn, math.tau - turn))


settings.use_ik = False
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
worst_wrist = 0.0
for frame in range(int(target.animation_data.action.frame_range[0]),
                   int(target.animation_data.action.frame_range[1]) + 1):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    worst_wrist = max(worst_wrist, abs(wrist(source, source.evaluated_get(depsgraph), hand_source, fore_source)
                                       - wrist(target, target.evaluated_get(depsgraph), hand_target, fore_target)))
assert worst_wrist < 2.0, f"손목 굽힘이 원본과 어긋납니다: 최대 {worst_wrist:.2f}°"
# 지어낸 방향은 맞출 수 없으므로 방향 오차 계산에서도 빠져야 한다.
assert "모션 본 방향 없음" in settings.apply_report, settings.apply_report
assert hand_target in settings.apply_report.split("모션 본 방향 없음")[1].splitlines()[0], settings.apply_report

# 11번: 구간 병합. 하향식 쪼개기가 남긴 매듭이 더 합칠 수 없는 상태까지 줄어야 한다.
probe_frames = list(range(1, 241))
probe = [[math.sin(value / 11.0) * math.cos(value / 29.0) for value in probe_frames]]
probe_tolerance = 0.01


def spread(actual, predicted):
    """검사용 스칼라 채널의 절대 오차."""
    return abs(actual[0] - predicted[0])


def worst_fit(low, high):
    """구간 하나를 적합했을 때의 최대 오차."""
    width = float(probe_frames[high] - probe_frames[low]) or 1.0
    spans = {point: (probe_frames[point] - probe_frames[low]) / width for point in range(low, high + 1)}
    controls = [retarget._solve_handles(spans, values, low, high) for values in probe]
    return max((spread(tuple(values[point] for values in probe),
                       tuple(retarget._evaluate(control, spans, values, low, high, point)
                             for control, values in zip(controls, probe)))
                for point in range(low + 1, high)), default=0.0)


merged_knots, merged_segments = retarget._fit_group(probe_frames, probe, probe_tolerance, spread)
keep = retarget._merge_segments
retarget._merge_segments = lambda segments, fit, tolerance: segments
try:
    split_knots, _split_segments = retarget._fit_group(probe_frames, probe, probe_tolerance, spread)
finally:
    retarget._merge_segments = keep
assert len(merged_knots) < len(split_knots), (len(merged_knots), len(split_knots))
for position in range(len(merged_segments) - 1):
    low, high = merged_segments[position][0], merged_segments[position + 1][1]
    assert worst_fit(low, high) > probe_tolerance, (position, worst_fit(low, high))
for low, high, _controls in merged_segments:
    assert worst_fit(low, high) <= probe_tolerance, (low, high, worst_fit(low, high))

# 다른 프로세스에서 재현을 확인할 예제 파일. 굽힌 포즈를 함께 적어 둔다.
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
baked = target.animation_data.action.frame_range
demo_frames = [round(baked[0] + (baked[1] - baked[0]) * i / 4) for i in range(5)]
poses = {}
for frame in demo_frames:
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    poses[str(frame)] = {bone.name: [v for row in bone.matrix for v in row] for bone in target.pose.bones}
scene["catani_verification"] = json.dumps({"rig": target.name, "poses": poses})
artifacts = root / "artifacts"
artifacts.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(artifacts / "CatAni_Motion_Demo.blend"))

addon.unregister()
assert not hasattr(bpy.types.Scene, "catani_settings")
addon.register()
assert hasattr(bpy.types.Scene, "catani_settings")
temporary.cleanup()
print(f"CATANI_PASS 합성 CMU BVH 22부위 리타게팅·최대 방향 오차 {worst:.4f}°·접지·NLA/IK 차단·재적용·실패 경로·"
      f"간소화 키 {simplified_keys}/{dense_keys}개 방향 오차 {worst_simplified:.4f}°·"
      f"IK 전환 {len(setups)}체인 방향 오차 {ik_worst:.4f}°·"
      f"정면 정렬 {skew:+.1f}° → {aligned:+.2f}°·"
      f"구간 병합 매듭 {len(split_knots)}→{len(merged_knots)}개·"
      f"손목 굽힘 오차 {worst_wrist:.2f}°")
