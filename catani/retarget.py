"""모션 리그의 본 방향을 캐릭터 리그에 그대로 옮겨 키를 굽는다."""

import math
import re

import bpy
from mathutils import Matrix, Vector

Y_AXIS = Vector((0.0, 1.0, 0.0))
MIN_PAIRS = 3
# 뼈 하나에 프레임당 쿼터니언 4채널을 쓰므로 상한을 두어 굽기 폭주를 막는다.
MAX_KEYFRAMES = 2_000_000

SLOT_ORDER = (
    "hips", "spine_1", "spine_2", "spine_3", "neck", "head",
    "shoulder_l", "arm_l", "forearm_l", "hand_l",
    "shoulder_r", "arm_r", "forearm_r", "hand_r",
    "thigh_l", "shin_l", "foot_l", "toe_l",
    "thigh_r", "shin_r", "foot_r", "toe_r",
)

# 부위별 부모 슬롯. 별칭으로 빈칸을 메울 때 계층이 어긋난 후보를 걸러낸다.
PARENT_SLOT = {
    "spine_1": "hips", "spine_2": "spine_1", "spine_3": "spine_2", "neck": "spine_3", "head": "neck",
    "shoulder_l": "spine_3", "arm_l": "shoulder_l", "forearm_l": "arm_l", "hand_l": "forearm_l",
    "shoulder_r": "spine_3", "arm_r": "shoulder_r", "forearm_r": "arm_r", "hand_r": "forearm_r",
    "thigh_l": "hips", "shin_l": "thigh_l", "foot_l": "shin_l", "toe_l": "foot_l",
    "thigh_r": "hips", "shin_r": "thigh_r", "foot_r": "shin_r", "toe_r": "foot_r",
}

_LIMB_SLOTS = ("shoulder", "arm", "forearm", "hand", "thigh", "shin", "foot", "toe")

# 리그마다 접두사·구분자·대소문자가 다르므로 이름을 한 형태로 줄여 비교한다.
_STRIP_PREFIXES = ("mixamorig1:", "mixamorig:", "mixamorig1", "mixamorig", "def-", "org-", "mch-",
                   "ctrl-", "ctrl_", "bip001", "bip01", "biped", "b_", "j_", "jnt_", "bone_", "rig_")
# IK 컨트롤은 FK 본으로 착각하면 안 되므로 ik는 버리지 않는다.
_DROP_TOKENS = frozenset({"fk", "def", "org", "mch", "jnt", "bone", "rig", "ctrl", "twist", "deform"})


def normalize(name):
    """`mixamorig:LeftArm`, `upperarm_l`, `Bip01 L UpperArm`을 비교 가능한 형태로 줄인다."""
    text = str(name).strip().lower().split("|")[-1]
    for prefix in _STRIP_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    tokens = [token for token in re.split(r"[^a-z0-9]+", text) if token]
    return "".join([token for token in tokens if token not in _DROP_TOKENS] or tokens)


def _humanoid(hips, spines, neck, head, limbs, left, right):
    """표준 슬롯 이름을 리그별 실제 본 이름으로 잇는 표를 만든다."""
    mapping = {"hips": hips, "neck": neck, "head": head}
    for index, name in enumerate(spines, start=1):
        mapping[f"spine_{index}"] = name
    for suffix, token in (("l", left), ("r", right)):
        for slot, template in zip(_LIMB_SLOTS, limbs):
            mapping[f"{slot}_{suffix}"] = template.format(side=token)
    return mapping


_CMU_LIMBS = ("{side}Shoulder", "{side}Arm", "{side}ForeArm", "{side}Hand", "{side}UpLeg", "{side}Leg", "{side}Foot", "{side}ToeBase")
_ASF_LIMBS = ("{side}clavicle", "{side}humerus", "{side}radius", "{side}wrist", "{side}femur", "{side}tibia", "{side}foot", "{side}toes")
_RIGIFY_LIMBS = ("shoulder.{side}", "upper_arm.{side}", "forearm.{side}", "hand.{side}", "thigh.{side}", "shin.{side}", "foot.{side}", "toe.{side}")
_UNREAL_LIMBS = ("clavicle_{side}", "upperarm_{side}", "lowerarm_{side}", "hand_{side}", "thigh_{side}", "calf_{side}", "foot_{side}", "ball_{side}")
_BIPED_LIMBS = ("{side}Clavicle", "{side}UpperArm", "{side}Forearm", "{side}Hand", "{side}Thigh", "{side}Calf", "{side}Foot", "{side}Toe0")
_DAZ_LIMBS = ("{side}Collar", "{side}ShldrBend", "{side}ForearmBend", "{side}Hand", "{side}ThighBend", "{side}Shin", "{side}Foot", "{side}Toe")

# 알려진 리그 규격. 위에서부터 일치 개수를 세어 가장 잘 맞는 규격을 고른다.
PROFILES = {
    "cmu": ("CMU / cgspeed BVH", _humanoid("Hips", ("LowerBack", "Spine", "Spine1"), "Neck", "Head", _CMU_LIMBS, "Left", "Right")),
    "mixamo": ("Mixamo", _humanoid("Hips", ("Spine", "Spine1", "Spine2"), "Neck", "Head", _CMU_LIMBS, "Left", "Right")),
    "cmu_asf": ("CMU ASF/AMC 원본 이름", _humanoid("hip", ("lowerback", "upperback", "thorax"), "lowerneck", "head", _ASF_LIMBS, "l", "r")),
    "rigify": ("Rigify / Player v1", _humanoid("spine", ("spine.001", "spine.002", "spine.003"), "neck", "head", _RIGIFY_LIMBS, "L", "R")),
    "unreal": ("Unreal / UE 스켈레톤", _humanoid("pelvis", ("spine_01", "spine_02", "spine_03"), "neck_01", "head", _UNREAL_LIMBS, "l", "r")),
    "biped": ("3ds Max Biped", _humanoid("Pelvis", ("Spine", "Spine1", "Spine2"), "Neck", "Head", _BIPED_LIMBS, "L ", "R ")),
    "daz": ("Daz Genesis", _humanoid("hip", ("abdomenLower", "abdomenUpper", "chestLower"), "neckLower", "head", _DAZ_LIMBS, "l", "r")),
}

# 규격으로 못 채운 빈칸을 메울 별칭. 계층 검증을 통과한 후보만 받아들인다.
_CENTER_ALIASES = {
    "hips": ("hips", "hip", "pelvis", "root", "cog", "waist", "hipjoint"),
    "spine_1": ("spine", "spine1", "spine01", "lowerback", "backlower", "abdomen", "abdomenlower",
                "torso", "torsolower", "lowertorso", "spinelower", "lowerspine", "waistupper"),
    "spine_2": ("spine1", "spine2", "spine02", "upperback", "backupper", "chest", "chestlower",
                "abdomenupper", "torso1", "torsoupper", "uppertorso", "spinemid", "midspine"),
    "spine_3": ("spine2", "spine3", "spine03", "thorax", "chestupper", "upperchest", "ribcage", "torso2"),
    "neck": ("neck", "neck1", "neck01", "lowerneck", "necklower"),
    "head": ("head", "upperneck", "skull"),
}
_LIMB_ALIASES = {
    "shoulder": ("shoulder", "clavicle", "collar"),
    "arm": ("arm", "upperarm", "shldr", "shldrbend", "humerus", "armupper", "uparm"),
    "forearm": ("forearm", "lowerarm", "forearmbend", "radius", "armlower", "elbow"),
    "hand": ("hand", "wrist", "palm"),
    "thigh": ("upleg", "thigh", "thighbend", "femur", "legupper", "upperleg", "upperthigh"),
    "shin": ("leg", "shin", "calf", "tibia", "leglower", "lowerleg", "knee"),
    "foot": ("foot", "ankle"),
    "toe": ("toebase", "toe", "toe0", "toes", "ball", "football", "toe1"),
}
_SIDE_TOKENS = {"l": ("l", "left", "lt", "lf"), "r": ("r", "right", "rt", "rg")}


def _slot_aliases(slot):
    if slot in _CENTER_ALIASES:
        return _CENTER_ALIASES[slot]
    limb, _, side = slot.rpartition("_")
    stems = _LIMB_ALIASES.get(limb, ())
    tokens = _SIDE_TOKENS.get(side, ())
    return tuple(f"{token}{stem}" for stem in stems for token in tokens) + tuple(f"{stem}{token}" for stem in stems for token in tokens)


def _bone_index(armature):
    """정규화한 이름 → 실제 본. 같은 이름으로 줄어들면 장식이 가장 적은 본을 쓴다."""
    index = {}
    for bone in armature.data.bones:
        key = normalize(bone.name)
        previous = index.get(key)
        if previous is None or (len(bone.name), bone.name) < (len(previous), previous):
            index[key] = bone.name
    return index


def _is_descendant(armature, name, ancestor):
    bone = armature.data.bones.get(name)
    while bone is not None:
        if bone.name == ancestor:
            return True
        bone = bone.parent
    return False


def _nearest_assigned(slot, assigned):
    parent = PARENT_SLOT.get(slot)
    while parent is not None and parent not in assigned:
        parent = PARENT_SLOT.get(parent)
    return parent


def detect_profile(armature):
    """본 이름이 가장 많이 일치하는 리그 규격과 일치 개수를 돌려준다."""
    index = _bone_index(armature)
    best = (None, 0)
    for key, (_label, mapping) in PROFILES.items():
        score = sum(1 for bone in mapping.values() if bone in armature.data.bones or normalize(bone) in index)
        if score > best[1]:
            best = (key, score)
    return best


def profile_label(key):
    return PROFILES[key][0] if key in PROFILES else "이름 별칭 자동 인식"


def resolve_slots(armature):
    """(슬롯 → 실제 본 이름, 규격 키, 별칭으로 메운 슬롯 목록)."""
    index = _bone_index(armature)
    key, score = detect_profile(armature)
    assigned = {}
    if key and score >= MIN_PAIRS:
        for slot, bone in PROFILES[key][1].items():
            actual = bone if bone in armature.data.bones else index.get(normalize(bone))
            if actual is not None:
                assigned[slot] = actual
    used = set(assigned.values())
    guessed = []
    for slot in SLOT_ORDER:
        if slot in assigned:
            continue
        anchor = _nearest_assigned(slot, assigned)
        for alias in _slot_aliases(slot):
            candidate = index.get(alias)
            if candidate is None or candidate in used:
                continue
            if anchor is not None and not _is_descendant(armature, candidate, assigned[anchor]):
                continue
            assigned[slot] = candidate
            used.add(candidate)
            guessed.append(slot)
            break
    return assigned, (key if score >= MIN_PAIRS else None), guessed


def build_pairs(source, target):
    """(슬롯, 모션 본, 캐릭터 본) 목록과 규격 키, 건너뛴 슬롯, 추정 슬롯을 돌려준다."""
    source_slots, source_key, source_guessed = resolve_slots(source)
    target_slots, target_key, target_guessed = resolve_slots(target)
    pairs, skipped = [], []
    for slot in SLOT_ORDER:
        source_bone, target_bone = source_slots.get(slot), target_slots.get(slot)
        if source_bone and target_bone:
            pairs.append((slot, source_bone, target_bone))
        else:
            skipped.append(slot)
    if len(pairs) >= MIN_PAIRS:
        guessed = [f"모션:{slot}" for slot in source_guessed if slot in source_slots and any(p[0] == slot for p in pairs)]
        guessed += [f"캐릭터:{slot}" for slot in target_guessed if any(p[0] == slot for p in pairs)]
        return pairs, source_key, target_key, skipped, guessed
    # 규격도 별칭도 통하지 않으면 이름이 똑같은 본만 잇는다.
    shared = sorted({bone.name for bone in source.data.bones} & {bone.name for bone in target.data.bones})
    if len(shared) < MIN_PAIRS:
        supported = " / ".join(label for label, _ in PROFILES.values())
        sample = ", ".join(bone.name for bone in list(target.data.bones)[:8])
        raise ValueError(
            f"모션 리그와 캐릭터 리그의 본 이름을 맞출 수 없습니다. 지원 규격: {supported}. "
            f"캐릭터 본 예: {sample}. 두 리그의 본 이름을 같게 맞추거나 지원 규격 이름을 사용하세요."
        )
    return [(name, name, name) for name in shared], None, None, [], ["이름 완전 일치 대체"]


def _rotation(matrix):
    return matrix.to_3x3().normalized().to_quaternion()


def _rest_world(obj, bone):
    return obj.matrix_world @ bone.matrix_local


def _roll_correction(source, source_bone, target, target_bone):
    """레스트 자세가 달라도 본이 같은 방향을 보게 하는 축 회전 보정."""
    source_rest = _rotation(_rest_world(source, source_bone))
    target_rest = _rotation(_rest_world(target, target_bone))
    align = (source_rest @ Y_AXIS).rotation_difference(target_rest @ Y_AXIS)
    return (align @ source_rest).inverted() @ target_rest


def _hierarchy(armature):
    order = []
    stack = [bone for bone in armature.data.bones if bone.parent is None]
    while stack:
        bone = stack.pop()
        order.append(bone)
        stack.extend(reversed(bone.children))
    return order


def _height(obj, bones):
    """엉덩이에서 발까지의 레스트 길이. 없으면 엉덩이 높이로 대신한다."""
    hips = bones.get("hips")
    if hips is None:
        return 0.0
    origin = _rest_world(obj, hips).translation
    foot = bones.get("foot_l") or bones.get("foot_r")
    if foot is not None:
        return (origin - _rest_world(obj, foot).translation).length
    return abs(origin.z)


def action_frame_range(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        raise ValueError("모션 리그에 Action이 없습니다.")
    start, end = action.frame_range
    return int(math.floor(start)), max(int(math.ceil(end)), int(math.floor(start)) + 1)


def _clear_pose(target, quaternion=()):
    for bone in target.pose.bones:
        bone.location = (0.0, 0.0, 0.0)
        if bone.name in quaternion:
            bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def _lowest_rest(target, target_basis, ground_bones):
    """레스트 자세에서 발·발끝 본이 닿는 가장 낮은 세계 좌표 Z."""
    lowest = None
    for name in ground_bones:
        bone = target.data.bones[name]
        for point in (bone.matrix_local.to_translation(), bone.matrix_local @ Vector((0.0, bone.length, 0.0))):
            value = (target_basis @ point).z
            lowest = value if lowest is None else min(lowest, value)
    return lowest


def _dilate(values, window=5):
    """관통 보정량을 이웃 최대값으로 넓혀 한 프레임만 튀는 계단을 줄인다."""
    if len(values) < 3 or not any(values):
        return values
    half = max(1, window // 2)
    return [max(values[max(0, index - half):index + half + 1]) for index in range(len(values))]


def _sample(context, source, target, pairs, frames, corrections, translation_scale, ground=True):
    """프레임별로 캐릭터 본의 로컬 회전과 엉덩이 이동을 계산한다."""
    scene = context.scene
    order = _hierarchy(target)
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    parent_rest = {bone.name: bone.parent.matrix_local.inverted() if bone.parent else None for bone in target.data.bones}
    mapped = {target_bone: source_bone for _slot, source_bone, target_bone in pairs}
    hips = next((target_bone for slot, _source_bone, target_bone in pairs if slot == "hips"), None)
    rotations = {name: [] for name in mapped}
    locations = []
    ground_bones = [target_bone for slot, _source, target_bone in pairs if slot.startswith(("foot", "toe"))]
    hips_targets = []
    penetration = []
    target_basis = target.matrix_world.copy()
    target_inverse = target_basis.inverted()
    target_rotation = _rotation(target_basis).inverted()
    hips_rest_world = _rest_world(target, target.data.bones[hips]).translation if hips else None
    rest_floor = _lowest_rest(target, target_basis, ground_bones) if ground and ground_bones else 0.0
    # 모션의 루트 이동은 첫 프레임을 기준으로 재는다. 리그마다 레스트 높이가 다르므로
    # 레스트를 기준으로 삼으면 캐릭터가 공중에 뜨거나 바닥을 파고든다.
    origin = None
    for frame in frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()
        source_eval = source.evaluated_get(depsgraph)
        source_world = source_eval.matrix_world
        pose = {}
        for bone in order:
            inverse = parent_rest[bone.name]
            base = pose[bone.parent.name] @ inverse @ rest[bone.name] if inverse is not None else rest[bone.name]
            source_bone = mapped.get(bone.name)
            if source_bone is None:
                pose[bone.name] = base
                continue
            motion = _rotation(source_world @ source_eval.pose.bones[source_bone].matrix)
            desired = target_rotation @ motion @ corrections[bone.name]
            location = base.to_translation()
            if bone.name == hips:
                current = (source_world @ source_eval.pose.bones[source_bone].matrix).translation
                if origin is None:
                    origin = current.copy()
                world_target = hips_rest_world + (current - origin) * translation_scale
                hips_targets.append(world_target)
                location = target_inverse @ world_target
            matrix = Matrix.LocRotScale(location, desired, Vector((1.0, 1.0, 1.0)))
            pose[bone.name] = matrix
            basis = base.inverted() @ matrix
            rotations[bone.name].append(basis.to_quaternion())
        if ground and ground_bones:
            floor = min(
                (target_basis @ pose[name] @ offset).z
                for name in ground_bones
                for offset in (Vector((0.0, 0.0, 0.0)), Vector((0.0, target.data.bones[name].length, 0.0)))
            )
            penetration.append(max(0.0, rest_floor - floor))
    lift = _dilate(penetration) if ground and ground_bones else []
    for index, world_target in enumerate(hips_targets):
        raised = world_target.copy()
        if index < len(lift):
            raised.z += lift[index]
        locations.append((rest[hips].inverted() @ (target_inverse @ raised)))
    return rotations, locations, hips, (max(lift) if lift else 0.0), sum(1 for value in penetration if value > 1e-6)


def _write_curves(target, action, frames, rotations, locations, hips):
    slot = action.slots.new(id_type="OBJECT", name=target.name)
    layer = action.layers.new("CatAni 리타게팅")
    bag = layer.strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
    target.animation_data.action = action
    target.animation_data.action_slot = slot
    written = 0
    for name, values in rotations.items():
        bone = target.pose.bones[name]
        path = bone.path_from_id("rotation_quaternion")
        for index in range(4):
            written += _fill(bag, path, index, name, frames, [value[index] for value in values])
    if hips and locations:
        path = target.pose.bones[hips].path_from_id("location")
        for index in range(3):
            written += _fill(bag, path, index, hips, frames, [value[index] for value in locations])
    # IK가 켜져 있으면 구운 FK 키가 화면에 나타나지 않는다.
    disabled = []
    for bone in target.pose.bones:
        for constraint in bone.constraints:
            if constraint.type != "IK":
                continue
            constraint.influence = 0.0
            curve = bag.fcurves.new(data_path=constraint.path_from_id("influence"), index=0, group_name=bone.name)
            key = curve.keyframe_points.insert(frames[0], 0.0)
            key.interpolation = "CONSTANT"
            curve.update()
            written += 1
            disabled.append(f"{bone.name}/{constraint.name}")
    return written, disabled


def _fill(bag, path, index, group, frames, values):
    curve = bag.fcurves.new(data_path=path, index=index, group_name=group)
    curve.keyframe_points.add(len(frames))
    coordinates = []
    for frame, value in zip(frames, values):
        coordinates.extend((float(frame), float(value)))
    curve.keyframe_points.foreach_set("co", coordinates)
    curve.keyframe_points.foreach_set("interpolation", [1] * len(frames))
    curve.update()
    return len(frames)


def deepest_penetration(context, target, frames, floor):
    """검증 프레임에서 바닥보다 아래로 내려간 가장 깊은 본과 깊이."""
    scene = context.scene
    worst = (0.0, "")
    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()
        basis = target.matrix_world
        for bone in target.pose.bones:
            matrix = basis @ bone.matrix
            for point in (matrix.translation, matrix @ Vector((0.0, bone.bone.length, 0.0))):
                depth = floor - point.z
                if depth > worst[0]:
                    worst = (depth, bone.name)
    return worst


def verify(context, source, target, pairs, frames):
    """구운 결과에서 두 리그의 본 방향 차이를 도 단위 최대값으로 돌려준다."""
    scene = context.scene
    worst = 0.0
    for frame in frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()
        source_eval = source.evaluated_get(depsgraph)
        target_eval = target.evaluated_get(depsgraph)
        for _slot, source_bone, target_bone in pairs:
            from_source = _rotation(source_eval.matrix_world @ source_eval.pose.bones[source_bone].matrix) @ Y_AXIS
            from_target = _rotation(target_eval.matrix_world @ target_eval.pose.bones[target_bone].matrix) @ Y_AXIS
            worst = max(worst, math.degrees(from_source.angle(from_target, 0.0)))
    return worst


def apply_motion(context, source, target, *, step=1, use_location=True, ground=True, name="CatAni 모션"):
    """모션 리그의 동작을 캐릭터에 굽고 적용 결과 보고서를 돌려준다."""
    for obj in (source, target):
        if obj is None or obj.type != "ARMATURE":
            raise ValueError("모션 리그와 캐릭터 아마추어가 모두 필요합니다.")
    if source == target:
        raise ValueError("캐릭터와 모션 리그가 같은 오브젝트입니다.")
    if target.library or target.data.library:
        raise ValueError("링크된 캐릭터 리그에는 적용할 수 없습니다. 로컬 복사본을 사용하세요.")
    if context.mode != "OBJECT":
        raise ValueError("오브젝트 모드에서 적용하세요.")
    step = max(1, int(step))
    pairs, source_key, target_key, skipped, guessed = build_pairs(source, target)
    start, end = action_frame_range(source)
    frames = list(range(start, end + 1, step))
    if len(frames) < 2:
        frames = [start, end]
    if len(frames) * len(pairs) * 4 > MAX_KEYFRAMES:
        raise ValueError("키가 너무 많습니다. 상세 설정에서 프레임 간격을 늘리세요.")
    source_bones = {slot: source.data.bones[source_bone] for slot, source_bone, _target in pairs}
    target_bones = {slot: target.data.bones[target_bone] for slot, _source, target_bone in pairs}
    source_height = _height(source, source_bones)
    target_height = _height(target, target_bones)
    translation_scale = target_height / source_height if use_location and source_height > 1e-5 and target_height > 1e-5 else 0.0
    corrections = {target_bone: _roll_correction(source, source.data.bones[source_bone], target, target.data.bones[target_bone]) for _slot, source_bone, target_bone in pairs}
    scene = context.scene
    state = (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
    if target.animation_data and target.animation_data.use_tweak_mode:
        raise ValueError("NLA 트윅 모드를 끄고 다시 적용하세요.")
    previous = target.animation_data.action if target.animation_data else None
    if previous is not None:
        previous.use_fake_user = True
    action = bpy.data.actions.new(name[:60])
    succeeded = False
    muted = []
    try:
        if target.animation_data is None:
            target.animation_data_create()
        # 굽는 동안 프레임을 옮기므로, 기존 Action을 먼저 떼야 매핑하지 않은 본에
        # 이전 애니메이션의 포즈가 남지 않는다.
        target.animation_data.action = None
        # 살아 있는 NLA 트랙은 새로 구운 Action을 덮어써서 결과가 어긋나게 만든다.
        for track in target.animation_data.nla_tracks:
            if not track.mute:
                track.mute = True
                muted.append(track)
        _clear_pose(target, {target_bone for _slot, _source, target_bone in pairs})
        target.data.pose_position = "POSE"
        rotations, locations, hips, lift, lifted_frames = _sample(context, source, target, pairs, frames, corrections, translation_scale, ground=use_location and ground)
        written, disabled = _write_curves(target, action, frames, rotations, locations if use_location else [], hips)
        action["catani_motion_source"] = source.name
        action["catani_motion_pairs"] = len(pairs)
        action.use_fake_user = True
        scene.frame_start, scene.frame_end = frames[0], frames[-1]
        context.view_layer.update()
        # 키가 놓인 프레임만 재면 프레임 간격을 넓혔을 때의 보간 오차를 놓친다.
        # 구간 전체에 고르게 흩은 프레임으로 사용자가 실제로 보는 값을 잰다.
        span = frames[-1] - frames[0]
        samples = sorted({frames[0], frames[-1], *(frames[0] + round(span * index / 6) for index in range(1, 6))})
        error = verify(context, source, target, pairs, samples)
        floor_bones = [target_bone for slot, _source, target_bone in pairs if slot.startswith(("foot", "toe"))]
        rest_floor = _lowest_rest(target, target.matrix_world.copy(), floor_bones) if floor_bones else 0.0
        depth, deep_bone = deepest_penetration(context, target, samples, rest_floor)
        scene.frame_set(frames[0])
        succeeded = True
        return {
            "pairs": pairs, "skipped": skipped, "guessed": guessed, "keyframes": written,
            "coverage": len(pairs) / len(SLOT_ORDER),
            "frame_start": frames[0], "frame_end": frames[-1], "frame_count": len(frames), "step": step,
            "source_profile": profile_label(source_key), "target_profile": profile_label(target_key),
            "target_bone_total": len(target.data.bones), "translation_scale": translation_scale,
            "max_direction_error": error, "verified_frames": samples,
            "ground_lift": lift, "ground_frames": lifted_frames,
            "penetration": depth, "penetration_bone": deep_bone,
            "previous_action": previous.name if previous else "",
            "muted_tracks": [track.name for track in muted],
            "disabled_ik": disabled, "action": action,
        }
    finally:
        if not succeeded:
            for track in muted:
                track.mute = False
            if target.animation_data is not None:
                target.animation_data.action = None
            bpy.data.actions.remove(action)
            _clear_pose(target)
            if previous is not None and target.animation_data is not None:
                target.animation_data.action = previous
            scene.frame_start, scene.frame_end = state[2], state[3]
            scene.frame_set(state[0], subframe=state[1])


def format_report(asset, report):
    """상세 팝업에 그대로 뿌릴 수 있는 줄 목록."""
    lines = [
        f"모션: {asset.name}",
        f"파일: {asset.path or asset.source_id}",
        f"프레임: {report['frame_start']}~{report['frame_end']} · {report['frame_count']}개 · 간격 {report['step']}",
        f"본 매핑: {len(report['pairs'])} / 표준 부위 {len(SLOT_ORDER)} · 커버리지 {report['coverage'] * 100:.0f}% · 캐릭터 본 {report['target_bone_total']}",
        f"규격: {report['source_profile']} → {report['target_profile']}",
        f"생성 키: {report['keyframes']:,}개",
        f"이동 배율: {report['translation_scale']:.3f}" if report["translation_scale"] else "이동 적용: 없음(회전만)",
        f"검증: {', '.join(str(frame) for frame in report['verified_frames'])} 프레임 최대 방향 오차 {report['max_direction_error']:.3f}°"
        + (" · 키가 없는 프레임을 포함해 보간 오차까지 반영" if report["step"] > 1 else ""),
    ]
    if report["ground_lift"] > 1e-6:
        lines.append(f"발 바닥 관통 보정: 최대 {report['ground_lift']:.3f} · {report['ground_frames']}프레임")
    if report["penetration"] > 0.02:
        lines.append(
            f"남은 바닥 관통: {report['penetration_bone']} {report['penetration']:.3f} · "
            "손이나 머리가 바닥에 닿는 곡예 동작은 팔다리 비율 차이가 남습니다. 필요하면 캐릭터를 올리거나 IK로 보정하세요."
        )
    if report["previous_action"]:
        lines.append(f"이전 Action 보존: {report['previous_action']}")
    if report["muted_tracks"]:
        lines.append(f"NLA 트랙 음소거: {', '.join(report['muted_tracks'])} · NLA 편집기에서 되돌릴 수 있습니다")
    if report["disabled_ik"]:
        lines.append(f"IK 영향 0으로 고정: {', '.join(report['disabled_ik'])}")
    if report["guessed"]:
        lines.append(f"이름 별칭으로 추정한 부위: {', '.join(report['guessed'])}")
    if report["skipped"]:
        lines.append(f"짝이 없어 건너뛴 부위: {', '.join(report['skipped'])}")
    for slot, source_bone, target_bone in report["pairs"]:
        lines.append(f"  {slot}: {source_bone} → {target_bone}")
    return lines
