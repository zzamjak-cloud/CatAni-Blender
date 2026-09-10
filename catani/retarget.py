"""모션 리그의 본 방향을 캐릭터 리그에 그대로 옮겨 키를 굽는다."""

import math
import re

import bpy
from mathutils import Matrix, Quaternion, Vector

Y_AXIS = Vector((0.0, 1.0, 0.0))
MIN_PAIRS = 3
# 뼈 하나에 프레임당 쿼터니언 4채널을 쓰므로 상한을 두어 굽기 폭주를 막는다.
MAX_KEYFRAMES = 2_000_000
# 곡선 간소화 기본 허용 오차(도). 0이면 모든 프레임에 키를 남긴다.
# 실측 CMU 걷기에서 이 값이면 키가 90% 줄고 방향 오차는 2.2° 안에 머문다.
DEFAULT_SIMPLIFY = 1.0
# 노이즈 완화 기본 창 크기(프레임). 0이나 1이면 완화하지 않는다.
# 실측에서 완화는 손익이 나빴다. 같은 키 수를 허용 오차로 얻는 편이 오차가 더 작다.
DEFAULT_SMOOTH = 0
# 되살리기를 몇 번까지 반복할지. 한 번에 위반 프레임을 모두 넣으므로 보통 1~2회에 끝난다.
TIGHTEN_ROUNDS = 3

# foreach_set은 enum을 정수로 받으므로 RNA에서 실제 번호를 읽어 캐시한다.
_KEY_ENUM = {}


def _key_enum(prop, identifier):
    if (prop, identifier) not in _KEY_ENUM:
        _KEY_ENUM[(prop, identifier)] = bpy.types.Keyframe.bl_rna.properties[prop].enum_items[identifier].value
    return _KEY_ENUM[(prop, identifier)]

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


def _kernel(window):
    """이항 계수 가중치. 가우시안에 가깝고 정수 연산만 쓴다."""
    size = max(1, int(window)) | 1
    row = [1]
    for _ in range(size - 1):
        row = [1] + [row[index] + row[index + 1] for index in range(len(row) - 1)] + [1]
    total = float(sum(row))
    return [value / total for value in row]


def _smooth_series(series, window, combine):
    """구간 양 끝은 창을 잘라 쓰고, 가중치를 다시 정규화해 값이 끌려가지 않게 한다."""
    weights = _kernel(window)
    if len(weights) < 3 or len(series) < 3:
        return series
    half = len(weights) // 2
    smoothed = []
    for index in range(len(series)):
        low = max(0, index - half)
        high = min(len(series), index + half + 1)
        picked = [(series[position], weights[position - index + half]) for position in range(low, high)]
        scale = sum(weight for _value, weight in picked)
        smoothed.append(combine([(value, weight / scale) for value, weight in picked]))
    return smoothed


def _blend_quaternions(picked):
    """부호를 맞춘 쿼터니언들의 가중 평균. 작은 각도에서는 선형 평균 후 정규화로 충분하다."""
    reference = max(picked, key=lambda item: item[1])[0]
    total = Quaternion((0.0, 0.0, 0.0, 0.0))
    for value, weight in picked:
        aligned = value.copy()
        if aligned.dot(reference) < 0.0:
            aligned.negate()
        total.w += aligned.w * weight
        total.x += aligned.x * weight
        total.y += aligned.y * weight
        total.z += aligned.z * weight
    if total.magnitude < 1e-9:
        return reference.copy()
    total.normalize()
    return total


def _blend_vectors(picked):
    total = Vector((0.0, 0.0, 0.0))
    for value, weight in picked:
        total += value * weight
    return total


def _dilate(values, window=5):
    """관통 보정량을 이웃 최대값으로 넓혀 한 프레임만 튀는 계단을 줄인다."""
    if len(values) < 3 or not any(values):
        return values
    half = max(1, window // 2)
    return [max(values[max(0, index - half):index + half + 1]) for index in range(len(values))]


def ik_setups(target):
    """리그가 선언한 IK 컨스트레인트에서 체인 구성을 읽는다.

    본 이름 규칙이 아니라 컨스트레인트가 직접 알려 주는 정보만 쓴다. 어떤 리그든
    IK를 제대로 걸어 두었으면 그대로 동작한다.
    """
    setups = []
    for bone in target.pose.bones:
        for constraint in bone.constraints:
            if constraint.type != "IK" or constraint.target is not target:
                continue
            control = constraint.subtarget
            if not control or control not in target.pose.bones:
                continue
            depth = constraint.chain_count or (len(bone.parent_recursive) + 1)
            chain = [bone.name] + [parent.name for parent in bone.parent_recursive[:max(0, depth - 1)]]
            # 컨트롤 본이 체인 안이나 그 아래에 있으면 우리가 값을 쓰는 순간 순환이 된다.
            control_bone = target.pose.bones[control]
            lineage = {parent.name for parent in control_bone.parent_recursive} | {control}
            if lineage & set(chain):
                continue
            pole = constraint.pole_subtarget if constraint.pole_target is target else ""
            if pole and pole not in target.pose.bones:
                pole = ""
            setups.append({
                "tip": bone.name, "root": chain[-1], "chain": chain,
                "control": control, "pole": pole, "constraint": constraint.name,
                "use_tail": constraint.use_tail,
            })
    return setups


def _plane_basis(root, mid, end):
    """삼각형(루트·중간관절·끝점)에 붙은 정규 직교 좌표계. 없으면 None."""
    axis = end - root
    if axis.length < 1e-6:
        return None
    axis = axis.normalized()
    arm = mid - root
    side = arm - axis * arm.dot(axis)
    if side.length < 1e-6:
        return None
    side = side.normalized()
    return Matrix((axis, side, axis.cross(side))).transposed()


def _pole_position(rest_frame, rest_offset, root, mid, end, fallback):
    """레스트에서 폴이 삼각형에 대해 갖던 관계를 현재 삼각형으로 옮긴다.

    이렇게 하면 리그의 pole_angle 규약이 무엇이든 레스트에서 성립하던 IK 해가 그대로
    재현된다. 규약을 추측하거나 부호를 맞춰 볼 필요가 없다.
    """
    if rest_frame is None:
        return fallback
    current = _plane_basis(root, mid, end)
    if current is None:
        return fallback
    return root + current @ rest_offset


def _leading_calibration(context, source, pairs, frames, limit=3):
    """맨 앞에 붙은 보정용 자세 프레임 수.

    CMU/cgspeed BVH는 첫 행의 회전 채널이 모두 0인 T포즈 보정 프레임으로 시작한다.
    그대로 구우면 1프레임짜리 T포즈 팝이 남고, 그 급점프가 노이즈 완화와 키 솎아내기를
    모두 망친다. 방향 변화가 평소의 몇 배로 튀는 선두 프레임만 걷어낸다.
    """
    if len(frames) < 6:
        return 0
    scene = context.scene
    bones = [source_bone for _slot, source_bone, _target in pairs]

    def directions(frame):
        scene.frame_set(frame)
        evaluated = source.evaluated_get(context.evaluated_depsgraph_get())
        world = evaluated.matrix_world
        return [_rotation(world @ evaluated.pose.bones[name].matrix) @ Y_AXIS for name in bones]

    def step(left, right):
        return max(math.degrees(a.angle(b, 0.0)) for a, b in zip(left, right))

    head = [directions(frame) for frame in frames[:limit + 2]]
    # 평소 변화량은 구간 전체에 흩은 인접 프레임 쌍에서 잰다. 선두만 보면 기준이 오염된다.
    span = len(frames)
    probes = sorted({span // 4 + index * span // 8 for index in range(5)})
    typical = sorted(step(directions(frames[position]), directions(frames[position + 1]))
                     for position in probes if position + 1 < span)
    if not typical:
        return 0
    middle = typical[len(typical) // 2]
    threshold = max(10.0, middle * 8.0)
    dropped = 0
    while dropped < limit and dropped + 1 < len(head) and step(head[dropped], head[dropped + 1]) > threshold:
        dropped += 1
    return dropped


def _sample(context, source, target, pairs, frames, corrections, translation_scale, ground=True, smooth=0):
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
    # 1단계: 프레임마다 캐릭터 본의 로컬 회전과 엉덩이의 세계 좌표 목표를 모은다.
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
            quaternion = basis.to_quaternion()
            # 부호가 인접 프레임에서 뒤집히면 키를 솎아낸 구간이 통째로 반대로 돈다.
            series = rotations[bone.name]
            if series:
                quaternion.make_compatible(series[-1])
            series.append(quaternion)
    # 2단계: 모캡 고주파 노이즈를 걷어낸다. 노이즈를 남긴 채 키를 솎아내면 오차 허용치
    # 안에 들어가려고 노이즈까지 충실히 보존하느라 키가 줄지 않는다.
    if smooth and smooth > 1:
        for name, series in rotations.items():
            rotations[name] = _smooth_series(series, smooth, _blend_quaternions)
        hips_targets = _smooth_series(hips_targets, smooth, _blend_vectors)
    # 3단계: 완화한 값으로 순운동학을 다시 풀어 발 관통량을 잰다. 1단계 포즈로 재면
    # 완화가 되돌려 놓은 발 높이를 놓친다.
    if ground and ground_bones:
        for index in range(len(frames)):
            offset = rest[hips].inverted() @ (target_inverse @ hips_targets[index]) if hips and hips_targets else None
            pose = _replay(order, rest, parent_rest, rotations, index, hips, offset)
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
    # 최종 포즈. IK 목표 위치와 끝본 보정은 완화와 접지 보정까지 반영한 값으로 잡아야
    # FK 결과와 같은 자리에 놓인다.
    final = [_replay(order, rest, parent_rest, rotations, index, hips,
                     locations[index] if hips and index < len(locations) else None)
             for index in range(len(frames))]
    return rotations, locations, hips, (max(lift) if lift else 0.0), sum(1 for value in penetration if value > 1e-6), final


def _replay(order, rest, parent_rest, rotations, index, hips=None, hips_offset=None):
    """로컬 회전 배열에서 프레임 하나의 본 오브젝트 공간 행렬을 되살린다.

    엉덩이 이동을 함께 넣어야 관통량이 맞는다. 몸이 내려가면 발도 같이 내려간다.
    """
    zero = Vector((0.0, 0.0, 0.0))
    scale = Vector((1.0, 1.0, 1.0))
    pose = {}
    for bone in order:
        inverse = parent_rest[bone.name]
        base = pose[bone.parent.name] @ inverse @ rest[bone.name] if inverse is not None else rest[bone.name]
        series = rotations.get(bone.name)
        if series is None:
            pose[bone.name] = base
            continue
        offset = hips_offset if (bone.name == hips and hips_offset is not None) else zero
        pose[bone.name] = base @ Matrix.LocRotScale(offset, series[index], scale)
    return pose


def _angle_error(actual, predicted):
    """샘플 회전과 곡선이 만든 회전 사이의 실제 각도 차이(도)."""
    interpolated = Quaternion(predicted)
    if interpolated.magnitude < 1e-9:
        return 180.0
    # 보간값은 길이가 1이 아니지만 Blender가 포즈를 만들 때 정규화하므로 같게 맞춘다.
    interpolated.normalize()
    difference = Quaternion(actual).normalized().rotation_difference(interpolated).angle
    return math.degrees(min(difference, math.tau - difference))


def _distance_error(actual, predicted):
    """샘플 이동과 곡선이 만든 이동 사이의 거리(블렌더 단위)."""
    return (Vector(actual) - Vector(predicted)).length


def _solve_handles(spans, values, low, high):
    """구간 [low, high]의 내부 표본에 가장 가까운 3차 베지어 제어점 두 개를 구한다.

    핸들의 x를 구간의 1/3 지점에 고정하면 x(t)가 t에 대해 선형이 되어 y(t)가 표준
    3차 베지어가 된다. 그러면 제어점 두 개만 최소제곱으로 풀면 되고, 우리가 계산한
    곡선이 Blender가 평가하는 곡선과 정확히 같아진다.
    """
    first, last = values[low], values[high]
    third = (last - first) / 3.0
    if high - low < 2:
        return first + third, last - third
    a11 = a12 = a22 = b1 = b2 = 0.0
    for position in range(low + 1, high):
        t = spans[position]
        one = 1.0 - t
        first_weight = 3.0 * one * one * t
        second_weight = 3.0 * one * t * t
        residual = values[position] - (one * one * one * first + t * t * t * last)
        a11 += first_weight * first_weight
        a12 += first_weight * second_weight
        a22 += second_weight * second_weight
        b1 += first_weight * residual
        b2 += second_weight * residual
    determinant = a11 * a22 - a12 * a12
    if abs(determinant) < 1e-12:
        return first + third, last - third
    return (a22 * b1 - a12 * b2) / determinant, (a11 * b2 - a12 * b1) / determinant


def _evaluate(controls, spans, values, low, high, position):
    """적합한 구간을 표본 위치에서 평가한다."""
    t = spans[position]
    one = 1.0 - t
    return (one * one * one * values[low] + 3.0 * one * one * t * controls[0]
            + 3.0 * one * t * t * controls[1] + t * t * t * values[high])


def _fit_group(frames, channels, tolerance, metric):
    """오차 허용치를 지키면서 매듭을 가장 적게 쓰는 베지어 구간들을 만든다.

    구간 하나로 맞춰 보고 오차가 넘으면 가장 어긋난 지점에서 쪼갠다. 키를 표본
    프레임에만 놓는 방식과 달리 구간이 데이터에 맞게 휘므로 같은 오차에서 매듭이
    훨씬 적게 남는다.

    돌려주는 값은 (매듭 인덱스, 채널별 구간 제어점)이다.
    """
    count = len(frames)
    if count < 2:
        return list(range(count)), []
    if tolerance <= 0.0:
        # 간소화를 끄면 모든 프레임을 매듭으로 남긴다.
        knots = list(range(count))
    else:
        knots = None

    def fit(low, high):
        """구간 하나를 적합해 (제어점들, 최대 오차, 최악 위치)를 돌려준다."""
        width = float(frames[high] - frames[low]) or 1.0
        spans = {position: (frames[position] - frames[low]) / width for position in range(low, high + 1)}
        controls = [_solve_handles(spans, values, low, high) for values in channels]
        worst, chosen = 0.0, -1
        for position in range(low + 1, high):
            predicted = tuple(_evaluate(control, spans, values, low, high, position)
                              for control, values in zip(controls, channels))
            actual = tuple(values[position] for values in channels)
            error = metric(actual, predicted)
            if error > worst:
                worst, chosen = error, position
        return controls, worst, chosen

    segments = []
    if knots is None:
        stack = [(0, count - 1)]
        while stack:
            low, high = stack.pop()
            controls, worst, chosen = fit(low, high)
            if worst <= tolerance or chosen < 0:
                segments.append((low, high, controls))
                continue
            stack.append((chosen, high))
            stack.append((low, chosen))
        segments.sort()
    else:
        for position in range(count - 1):
            controls, _worst, _chosen = fit(position, position + 1)
            segments.append((position, position + 1, controls))
    knots = [segments[0][0]] + [segment[1] for segment in segments]
    return knots, segments


def _write_group(bag, path, group, frames, channels, knots, segments):
    """적합 결과를 자유 핸들 베지어 곡선으로 쓴다."""
    curves = []
    # 직접 대입은 문자열 enum을 받는다. 정수는 foreach_set에서만 쓴다.
    for index, values in enumerate(channels):
        curve = bag.fcurves.new(data_path=path, index=index, group_name=group)
        curve.keyframe_points.add(len(knots))
        for position, knot in enumerate(knots):
            key = curve.keyframe_points[position]
            key.co = (float(frames[knot]), float(values[knot]))
            key.interpolation = "BEZIER"
            key.handle_left_type = "FREE"
            key.handle_right_type = "FREE"
            key.handle_left = key.co
            key.handle_right = key.co
        for position, (low, high, controls) in enumerate(segments):
            width = float(frames[high] - frames[low]) or 1.0
            left, right = controls[index]
            curve.keyframe_points[position].handle_right = (frames[low] + width / 3.0, left)
            curve.keyframe_points[position + 1].handle_left = (frames[high] - width / 3.0, right)
        curve.update()
        curves.append(curve)
    return curves


def _measure_group(curves, frames, channels, metric):
    """구운 곡선을 Blender가 평가한 값으로 모든 표본 프레임에서 오차를 잰다.

    적합 단계의 계산과 Blender의 평가가 어긋나면 여기서 드러난다.
    """
    worst = 0.0
    for position, frame in enumerate(frames):
        predicted = tuple(curve.evaluate(frame) for curve in curves)
        actual = tuple(values[position] for values in channels)
        worst = max(worst, metric(actual, predicted))
    return worst


def _bake_group(bag, path, group, frames, channels, tolerance, metric):
    """키 위치를 공유하는 채널 묶음을 최소 매듭 베지어 곡선으로 굽는다."""
    knots, segments = _fit_group(frames, channels, tolerance, metric)
    curves = _write_group(bag, path, group, frames, channels, knots, segments)
    error = _measure_group(curves, frames, channels, metric) if tolerance > 0.0 else 0.0
    return sum(len(curve.keyframe_points) for curve in curves), error


def _ik_channels(target, setups, poses, residuals=None):
    """프레임별 최종 포즈에서 IK 컨트롤과 폴 본의 로컬 이동값을 만든다.

    residuals는 컨스트레인트별 폴 각도 보정값(라디안)이다. 리그의 레스트 자세가 그
    리그의 IK 해와 정확히 일치하지 않으면 무릎이 일정 각도만큼 돌아간 채 풀리므로,
    실측한 상수 잔차를 여기서 되돌린다.
    """
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    tracks = []
    for setup in setups:
        tip, root, control, pole = setup["tip"], setup["root"], setup["control"], setup["pole"]
        length = target.data.bones[tip].length
        offset = Vector((0.0, length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
        rest_root = rest[root].to_translation()
        rest_mid = rest[tip].to_translation()
        rest_end = rest[tip] @ offset
        rest_frame = _plane_basis(rest_root, rest_mid, rest_end)
        rest_offset = None
        if rest_frame is not None and pole:
            rest_offset = rest_frame.transposed() @ (rest[pole].to_translation() - rest_root)
        control_track, pole_track = [], []
        for pose in poses:
            end = pose[tip] @ offset
            control_base = pose[control]
            control_local = control_base.inverted() @ end
            control_track.append(control_local)
            if not pole:
                continue
            # 컨트롤 본을 우리가 옮기므로, 그 아래에 붙은 폴의 기준 행렬도 옮긴 뒤에 잡는다.
            moved = control_base @ Matrix.LocRotScale(control_local, Quaternion(), Vector((1.0, 1.0, 1.0)))
            parent = target.data.bones[pole].parent
            if parent is not None and parent.name == control:
                pole_base = moved @ rest[control].inverted() @ rest[pole]
            else:
                pole_base = pose[pole]
            origin = pose[root].to_translation()
            wanted = _pole_position(rest_frame, rest_offset, origin,
                                    pose[tip].to_translation(), end, pole_base.to_translation())
            angle = (residuals or {}).get(setup["control"], 0.0)
            if angle:
                axis = end - origin
                if axis.length > 1e-6:
                    wanted = origin + Matrix.Rotation(angle, 3, axis.normalized()) @ (wanted - origin)
            pole_track.append(pole_base.inverted() @ wanted)
        tracks.append({"setup": setup, "control": control_track, "pole": pole_track})
    return tracks


def _write_curves(target, action, frames, rotations, locations, hips, simplify=0.0, scale=1.0,
                  ik_tracks=()):
    slot = action.slots.new(id_type="OBJECT", name=target.name)
    layer = action.layers.new("CatAni 리타게팅")
    bag = layer.strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
    target.animation_data.action = action
    target.animation_data.action_slot = slot
    written = 0
    angle_error = 0.0
    shift_error = 0.0
    for name, values in rotations.items():
        channels = [[value[index] for value in values] for index in range(4)]
        path = target.pose.bones[name].path_from_id("rotation_quaternion")
        count, error = _bake_group(bag, path, name, frames, channels, simplify, _angle_error)
        written += count
        angle_error = max(angle_error, error)
    if hips and locations:
        channels = [[value[index] for value in locations] for index in range(3)]
        path = target.pose.bones[hips].path_from_id("location")
        # 회전 오차 θ가 캐릭터 전체에 만드는 변위(키 × θ)를 이동 채널 허용치로 삼는다.
        tolerance = scale * math.radians(simplify)
        count, error = _bake_group(bag, path, hips, frames, channels, tolerance, _distance_error)
        written += count
        shift_error = error
    tolerance = scale * math.radians(simplify)
    for track in ik_tracks:
        for kind in ("control", "pole"):
            series = track[kind]
            if not series:
                continue
            name = track["setup"][kind]
            channels = [[value[index] for value in series] for index in range(3)]
            path = target.pose.bones[name].path_from_id("location")
            count, error = _bake_group(bag, path, name, frames, channels, tolerance, _distance_error)
            written += count
            shift_error = max(shift_error, error)
    # IK를 쓸 때는 영향을 1로 되돌려야 하고, FK로 구울 때는 0으로 눌러야 구운 키가 보인다.
    driven = {track["setup"]["constraint"] for track in ik_tracks}
    influence = 1.0 if ik_tracks else 0.0
    disabled = []
    for bone in target.pose.bones:
        for constraint in bone.constraints:
            if constraint.type != "IK":
                continue
            value = influence if constraint.name in driven or not ik_tracks else 0.0
            constraint.influence = value
            curve = bag.fcurves.new(data_path=constraint.path_from_id("influence"), index=0, group_name=bone.name)
            key = curve.keyframe_points.insert(frames[0], value)
            key.interpolation = "CONSTANT"
            curve.update()
            written += 1
            if value == 0.0:
                disabled.append(f"{bone.name}/{constraint.name}")
    return written, disabled, angle_error, shift_error, bag


def _fill(bag, path, index, group, frames, values):
    """키를 한 번에 넣고 오토 클램프 베지어로 만든다. 클램프는 발이 바닥을 뚫는 오버슈트를 막는다."""
    curve = bag.fcurves.new(data_path=path, index=index, group_name=group)
    curve.keyframe_points.add(len(frames))
    coordinates = []
    for frame, value in zip(frames, values):
        coordinates.extend((float(frame), float(value)))
    curve.keyframe_points.foreach_set("co", coordinates)
    curve.keyframe_points.foreach_set("interpolation", [_key_enum("interpolation", "BEZIER")] * len(frames))
    for side in ("handle_left_type", "handle_right_type"):
        curve.keyframe_points.foreach_set(side, [_key_enum(side, "AUTO_CLAMPED")] * len(frames))
    curve.update()
    return curve


def _pole_residuals(context, target, setups, poses, frames, probes=5):
    """구운 결과에서 무릎이 원하는 자리에서 얼마나 돌아갔는지 잰다.

    폴 각도 규약은 리그마다 다르고 컨스트레인트의 pole_angle과도 별개로 레스트 자세가
    어긋날 수 있다. 규약을 추측하는 대신 Blender가 실제로 푼 결과를 읽어 상수 오차를
    구한다. 구간에 흩은 몇 프레임의 중앙값을 쓴다.
    """
    scene = context.scene
    span = len(frames)
    picked = sorted({max(0, min(span - 1, span * (index + 1) // (probes + 1))) for index in range(probes)})
    gathered = {setup["control"]: [] for setup in setups if setup["pole"]}
    for index in picked:
        scene.frame_set(frames[index])
        context.view_layer.update()
        pose = poses[index]
        for setup in setups:
            if not setup["pole"]:
                continue
            tip, root = setup["tip"], setup["root"]
            offset = Vector((0.0, target.data.bones[tip].length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
            origin = target.pose.bones[root].matrix.to_translation()
            axis = (pose[tip] @ offset) - origin
            if axis.length < 1e-6:
                continue
            axis.normalize()
            wanted = pose[tip].to_translation() - origin
            solved = target.pose.bones[tip].matrix.to_translation() - origin
            wanted = wanted - axis * wanted.dot(axis)
            solved = solved - axis * solved.dot(axis)
            if wanted.length < 1e-5 or solved.length < 1e-5:
                continue
            wanted.normalize()
            solved.normalize()
            gathered[setup["control"]].append(
                math.atan2(axis.dot(solved.cross(wanted)), solved.dot(wanted)))
    residuals = {}
    for name, values in gathered.items():
        if values:
            residuals[name] = sorted(values)[len(values) // 2]
    return residuals


def _rewrite_poles(bag, target, frames, tracks, simplify, scale):
    """보정한 폴 값으로 기존 폴 곡선을 지우고 다시 쓴다."""
    tolerance = scale * math.radians(simplify)
    written = 0
    for track in tracks:
        name = track["setup"]["pole"]
        if not name or not track["pole"]:
            continue
        curve_path = target.pose.bones[name].path_from_id("location")
        for curve in [curve for curve in bag.fcurves if curve.data_path == curve_path]:
            bag.fcurves.remove(curve)
        channels = [[value[index] for value in track["pole"]] for index in range(3)]
        count, _error = _bake_group(bag, curve_path, name, frames, channels, tolerance, _distance_error)
        written += count
    return written


def _bake_followers(context, target, bag, frames, deferred, poses, simplify, setups):
    """IK가 정한 부모 방향 위에서 끝본의 세계 방향을 FK 결과와 같게 맞춘다.

    2본 IK는 팔뚝·정강이의 비틀림을 폴이 정하므로 FK와 다를 수 있다. 그대로 두면 손과
    발이 자기 축을 따라 돌아간다. Blender가 실제로 푼 결과를 읽어 그 위에서 보정한다.
    같은 순회에서 IK가 목표와 무릎을 얼마나 맞혔는지도 함께 잰다.
    """
    scene = context.scene
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    series = {name: [] for name in deferred}
    effector = 0.0
    middle = 0.0
    for index, frame in enumerate(frames):
        scene.frame_set(frame)
        context.view_layer.update()
        pose = poses[index]
        for name in series:
            parent = target.data.bones[name].parent
            base = target.pose.bones[parent.name].matrix @ rest[parent.name].inverted() @ rest[name]
            quaternion = _rotation(base).inverted() @ _rotation(pose[name])
            previous = series[name]
            if previous:
                quaternion.make_compatible(previous[-1])
            previous.append(quaternion)
        for setup in setups:
            tip = setup["tip"]
            offset = Vector((0.0, target.data.bones[tip].length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
            solved = target.pose.bones[tip].matrix
            effector = max(effector, ((solved @ offset) - (pose[tip] @ offset)).length)
            middle = max(middle, (solved.to_translation() - pose[tip].to_translation()).length)
    written = 0
    worst = 0.0
    for name, values in series.items():
        channels = [[value[index] for value in values] for index in range(4)]
        curve_path = target.pose.bones[name].path_from_id("rotation_quaternion")
        count, error = _bake_group(bag, curve_path, name, frames, channels, simplify, _angle_error)
        written += count
        worst = max(worst, error)
    return written, worst, effector, middle


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


def apply_motion(context, source, target, *, step=1, use_location=True, ground=True,
                 simplify=DEFAULT_SIMPLIFY, smooth=DEFAULT_SMOOTH, use_ik=False, name="CatAni 모션"):
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
    simplify = max(0.0, float(simplify))
    smooth = max(0, int(smooth))
    pairs, source_key, target_key, skipped, guessed = build_pairs(source, target)
    start, end = action_frame_range(source)
    frames = list(range(start, end + 1, step))
    if len(frames) < 2:
        frames = [start, end]
    if len(frames) * len(pairs) * 4 > MAX_KEYFRAMES:
        raise ValueError("키가 너무 많습니다. 상세 설정에서 프레임 간격을 늘리세요.")
    dropped = _leading_calibration(context, source, pairs, frames)
    if dropped and len(frames) - dropped >= 2:
        frames = frames[dropped:]
    else:
        dropped = 0
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
        rotations, locations, hips, lift, lifted_frames, poses = _sample(
            context, source, target, pairs, frames, corrections, translation_scale,
            ground=use_location and ground, smooth=smooth)
        setups = ik_setups(target) if use_ik else []
        # IK가 회전을 직접 풀어 주는 체인 본에는 FK 키를 쓰지 않는다.
        chain = {bone for setup in setups for bone in setup["chain"]}
        for bone in chain & set(rotations):
            del rotations[bone]
        # 체인 끝에 붙은 본은 IK가 정한 비틀림 위에서 다시 맞춰야 하므로 뒤로 미룬다.
        deferred = {}
        for bone in list(rotations):
            parent = target.data.bones[bone].parent
            if parent is not None and parent.name in chain:
                deferred[bone] = rotations.pop(bone)
        tracks = _ik_channels(target, setups, poses) if setups else []
        # 간소화를 끄지 않았을 때의 비교 기준. 모든 샘플 프레임에 키를 남겼을 경우의 개수다.
        dense = len(frames) * (len(pairs) * 4 + (3 if use_location and hips else 0))
        written, disabled, curve_error, curve_shift, bag = _write_curves(
            target, action, frames, rotations, locations if use_location else [], hips,
            simplify=simplify, scale=target_height, ik_tracks=tracks)
        ik_effector = ik_middle = 0.0
        pole_fix = {}
        if setups:
            # 폴 각도의 상수 잔차를 실측해 되돌린 뒤 폴 곡선만 다시 쓴다.
            pole_fix = _pole_residuals(context, target, setups, poses, frames)
            if any(abs(value) > math.radians(0.05) for value in pole_fix.values()):
                tracks = _ik_channels(target, setups, poses, pole_fix)
                written += _rewrite_poles(bag, target, frames, tracks, simplify, target_height)
            count, error, ik_effector, ik_middle = _bake_followers(
                context, target, bag, frames, deferred, poses, simplify, setups)
            written += count
            curve_error = max(curve_error, error)
        action["catani_motion_source"] = source.name
        action["catani_motion_pairs"] = len(pairs)
        action.use_fake_user = True
        scene.frame_start, scene.frame_end = frames[0], frames[-1]
        context.view_layer.update()
        # 키가 놓인 프레임만 재면 프레임 간격을 넓혔을 때의 보간 오차를 놓친다.
        # 구간 전체에 고르게 흩은 프레임으로 사용자가 실제로 보는 값을 잰다.
        # 간소화를 켜면 보간 구간이 곡선 전체로 퍼지므로 검증 프레임도 촘촘하게 잡는다.
        span = frames[-1] - frames[0]
        divisions = 12 if simplify > 0.0 else 6
        samples = sorted({frames[0], frames[-1],
                          *(frames[0] + round(span * index / divisions) for index in range(1, divisions))})
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
            "simplify": simplify, "dense_keyframes": dense, "smooth": smooth, "dropped_frames": dropped,
            "ik": [setup["control"] for setup in setups], "ik_requested": use_ik,
            "ik_effector": ik_effector, "ik_middle": ik_middle,
            "pole_fix": {name: math.degrees(value) for name, value in pole_fix.items()},
            "curve_error": curve_error, "curve_shift": curve_shift,
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
        + (" · 키가 없는 프레임을 포함해 보간 오차까지 반영" if report["step"] > 1 or report["simplify"] else ""),
    ]
    if report["dropped_frames"]:
        lines.append(f"선두 보정 프레임 제거: {report['dropped_frames']}개 · 모션 파일 첫 프레임이 T포즈 보정 자세라 그대로 구우면 팝이 남습니다")
    lines.append(f"노이즈 완화: {report['smooth']}프레임 창" if report["smooth"] > 1 else "노이즈 완화: 없음")
    if report["simplify"]:
        saved = 1.0 - report["keyframes"] / report["dense_keyframes"] if report["dense_keyframes"] else 0.0
        lines.append(
            f"곡선 간소화: 허용 오차 {report['simplify']:.2f}° · "
            f"키 {report['dense_keyframes']:,} → {report['keyframes']:,}개({saved * 100:.0f}% 감소) · "
            f"실측 회전 오차 최대 {report['curve_error']:.3f}°"
            + (f" · 엉덩이 이동 오차 최대 {report['curve_shift']:.4f}" if report["curve_shift"] else "")
        )
    else:
        lines.append("곡선 간소화: 없음 · 모든 프레임에 베지어 키")
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
    if report["ik"]:
        lines.append(
            f"IK로 전환: {', '.join(report['ik'])} · 리그의 IK 컨스트레인트에서 체인·폴을 읽어 굽습니다 · "
            f"목표 위치 오차 최대 {report['ik_effector']:.4f} · 중간 관절 오차 최대 {report['ik_middle']:.4f}"
        )
        if report["pole_fix"]:
            fixes = ", ".join(f"{name} {value:+.2f}°" for name, value in report["pole_fix"].items())
            lines.append(f"폴 각도 실측 보정: {fixes} · 리그 레스트 자세와 IK 해의 차이를 재서 되돌렸습니다")
    elif report["ik_requested"]:
        lines.append("IK로 전환: 대상 리그에 쓸 수 있는 IK 컨스트레인트가 없어 FK로 구웠습니다")
    if report["disabled_ik"]:
        lines.append(f"IK 영향 0으로 고정: {', '.join(report['disabled_ik'])}")
    if report["guessed"]:
        lines.append(f"이름 별칭으로 추정한 부위: {', '.join(report['guessed'])}")
    if report["skipped"]:
        lines.append(f"짝이 없어 건너뛴 부위: {', '.join(report['skipped'])}")
    for slot, source_bone, target_bone in report["pairs"]:
        lines.append(f"  {slot}: {source_bone} → {target_bone}")
    return lines
