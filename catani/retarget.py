"""모션 리그의 본 방향을 캐릭터 리그에 그대로 옮겨 키를 굽는다."""

import math
import re

import bpy
from mathutils import Matrix, Quaternion, Vector

Y_AXIS = Vector((0.0, 1.0, 0.0))
X_AXIS = Vector((1.0, 0.0, 0.0))
Z_AXIS = Vector((0.0, 0.0, 1.0))
MIN_PAIRS = 3
# 뼈 하나에 프레임당 쿼터니언 4채널을 쓰므로 상한을 두어 굽기 폭주를 막는다.
MAX_KEYFRAMES = 2_000_000
# 곡선 간소화 기본 허용 오차(도). 0이면 모든 프레임에 키를 남긴다.
# 실측 CMU 걷기에서 이 값이면 키가 90% 줄고 방향 오차는 2.2° 안에 머문다.
DEFAULT_SIMPLIFY = 1.0
# 노이즈 완화 기본 창 크기(프레임). 0이나 1이면 완화하지 않는다.
# 키는 확실히 줄지만(CMU 3개 클립에서 -15~-22%) 발 고정 판정(STANCE_SPEED_RATIO)이
# 완화로 느려진 발을 스탠스로 잘못 보는 클립이 있어 기본으로는 끈다. CMU 88_06에서
# 창 3은 방향 오차를 1.86°에서 7.01°로 키웠다. 지저분한 캡처에만 손으로 켠다.
DEFAULT_SMOOTH = 0
# 실측 무릎 방향이 루트 본(허벅지·위팔)의 비틀림에서 예측한 쪽으로 최소 이만큼은 굽어
# 있어야 한다고 보는 문턱. 루트 본 길이에 대한 비율이며 `side/arm`이 관절이 굽은 각의
# 사인이므로 0.05는 약 2.9°다. 예측 방향 성분이 이에 못 미치면 부족한 만큼 예측 방향을
# 더해, 실측 방향(표본 노이즈·과신전에 좌우됨)이 예측과 반대여도 뒤집히지 않게 한다.
# 뒤집힘 방지는 문턱 크기와 무관하고, 문턱은 펴진 관절에서 노이즈가 폴을 흔드는 정도와
# 살짝 굽은 관절에서 FK 무릎 방향을 얼마나 그대로 따르는지 사이의 절충이다. 실측에서
# 크라잉(CMU 80_45)의 펴진 다리는 0.03에서 약 4° 과신전으로 들어왔고, 걷기 중 다리는
# 0.10 위였다. 합성 걷기에서 0.05는 간소화 없는 IK의 방향 오차를 1.2°에 묶었다(0.1은 2.4°).
POLE_PRIOR_RATIO = 0.05
# 발 고정: 원본 발이 프레임당 이 비율(다리 길이 기준) 미만으로 움직이면 땅을 딛고 있는
# 것으로 본다. 실측에서 서 있는 자세(CMU 80_45)의 원본 발은 p95 0.0018, 걷기의 스탠스는
# 0.003 아래였고 스윙은 0.02 위였다.
STANCE_SPEED_RATIO = 0.004
# 스탠스로 인정하는 최소 길이(프레임)와 스탠스 앞뒤로 FK와 섞는 구간(프레임).
STANCE_MIN_FRAMES = 4
STANCE_BLEND_FRAMES = 6
# 발 고정 목표가 이보다 가까워야 다리가 닿는다고 보는 여유(허벅지+정강이 길이 비율).
REACH_MARGIN = 0.01
# IK 목표 곡선을 회전 곡선보다 몇 배 조일지. 다리가 거의 펴진 구간에서는 목표를 조금만
# 옮겨도 무릎 각이 크게 돌아 다리가 튄다. 실측에서 4배면 2°를 넘는 튐이 사라졌고, 더
# 조여도 이득은 거의 없이 키만 늘었다(01_13에서 16배는 키 +42%에 0.6° 개선).
IK_CURVE_TIGHTEN = 4.0
# 매듭 기울기를 사전분포(단조 제한 캣멀롬) 쪽으로 당기는 무게. 구간에 내부 표본이 없을 때
# 해를 하나로 정하는 것이 주 역할이고, 표본이 있는 구간에서는 영향이 몇 %에 그친다.
TANGENT_PRIOR = 0.002
# 접선을 이어 다시 푼 곡선이 허용치를 넘으면 매듭을 더해 다시 푸는 최대 횟수.
TANGENT_ROUNDS = 4
# 허용치를 벗어난 표본이 이만큼 연속으로 이어져야 매듭을 놓는다. 한 프레임만 튀는 표본은
# 모캡 노이즈다. 그 자리에 매듭을 놓으면 흐름과 무관한 키가 이웃 프레임에 줄줄이 박힌다.
NOISE_RUN = 2
# 다만 한 프레임짜리라도 허용치의 이 배수를 넘으면 노이즈가 아니라 빠른 자세 변화로 본다.
# 상한을 두지 않으면 한 프레임이 얼마든지 벗어날 수 있어, 허용치를 조금만 키워도 결과가
# 무너진다(실측 CMU 88_06, 1.5°에서 방향 오차 10.2°).
NOISE_PEAK = 3.0
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
# Unity 휴머노이드 계열의 흔한 이름. Bandai Namco Research 데이터셋이 그대로 쓴다.
_GENERIC_LIMBS = ("Shoulder_{side}", "UpperArm_{side}", "LowerArm_{side}", "Hand_{side}", "UpperLeg_{side}", "LowerLeg_{side}", "Foot_{side}", "Toes_{side}")

# 알려진 리그 규격. 위에서부터 일치 개수를 세어 가장 잘 맞는 규격을 고른다.
PROFILES = {
    "cmu": ("CMU / cgspeed BVH", _humanoid("Hips", ("LowerBack", "Spine", "Spine1"), "Neck", "Head", _CMU_LIMBS, "Left", "Right")),
    "mixamo": ("Mixamo", _humanoid("Hips", ("Spine", "Spine1", "Spine2"), "Neck", "Head", _CMU_LIMBS, "Left", "Right")),
    "cmu_asf": ("CMU ASF/AMC 원본 이름", _humanoid("hip", ("lowerback", "upperback", "thorax"), "lowerneck", "head", _ASF_LIMBS, "l", "r")),
    "rigify": ("Rigify / Player v1", _humanoid("spine", ("spine.001", "spine.002", "spine.003"), "neck", "head", _RIGIFY_LIMBS, "L", "R")),
    "unreal": ("Unreal / UE 스켈레톤", _humanoid("pelvis", ("spine_01", "spine_02", "spine_03"), "neck_01", "head", _UNREAL_LIMBS, "l", "r")),
    "biped": ("3ds Max Biped", _humanoid("Pelvis", ("Spine", "Spine1", "Spine2"), "Neck", "Head", _BIPED_LIMBS, "L ", "R ")),
    "daz": ("Daz Genesis", _humanoid("hip", ("abdomenLower", "abdomenUpper", "chestLower"), "neckLower", "head", _DAZ_LIMBS, "l", "r")),
    "generic": ("Unity 휴머노이드 계열", _humanoid("Hips", ("Spine", "Chest"), "Neck", "Head", _GENERIC_LIMBS, "L", "R")),
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


def _invented_direction(armature, bone):
    """가져오기가 방향을 지어낸 본인지 판별한다.

    모션 파일이 관절의 길이를 담고 있지 않으면 Blender는 방향을 임의로 정한다. 그 방향에
    캐릭터 본을 맞추면 손목이 통째로 꺾여 들어온다. 실측한 두 가지 형태를 모두 잡는다.

    - 자식이 모두 제 머리에 겹쳐 있는 관절. CMU의 `Hips`·`Spine1`·`LeftHand`·`RightHand`가
      그렇다(가져오기 로그의 "zero length node found").
    - End Site 없이 끝나는 말단 관절. Bandai Namco의 `Hand_L`·`Head`·`Toes_L`이 그렇다.

    둘 다 Blender가 같은 기본 길이를 넣으므로, 리그에서 가장 긴 본과 견주어 걸러낸다.
    실측에서 지어낸 본은 0.02~1.3%, 진짜 짧은 본(발끝)은 11.9% 위였다.
    """
    longest = max((item.length for item in armature.data.bones), default=0.0)
    if longest <= 0.0:
        return False
    if not bone.children:
        return bone.length <= longest * 0.01
    return all((child.head_local - bone.head_local).length <= longest * 1e-4 for child in bone.children)


def _roll_corrections(source, target, pairs):
    """레스트 자세가 달라도 본이 같은 방향을 보게 하는 축 회전 보정을 부위별로 만든다.

    보통은 모션 본이 가리키는 쪽으로 캐릭터 본을 돌린다(`align`). 다만 모션 본의 방향이
    지어낸 값이면 그쪽으로 맞출 수 없으므로, 부모 부위가 쓴 회전을 그대로 물려받아 본이
    부모를 따라가게 한다. 손목 자체의 회전은 프레임별 모션에 이미 들어 있으므로 잃지 않는다.
    """
    by_slot = {slot: (source_bone, target_bone) for slot, source_bone, target_bone in pairs}
    # 부모 부위를 먼저 풀어야 물려받을 회전이 준비된다. 이름 완전 일치 대체 경로는
    # 슬롯 자리에 본 이름이 들어오므로 표준 부위를 처리한 뒤 남은 것을 그대로 잇는다.
    order = [slot for slot in SLOT_ORDER if slot in by_slot]
    order += [slot for slot in by_slot if slot not in SLOT_ORDER]
    aligns = {}
    corrections = {}
    for slot in order:
        source_bone, target_bone = by_slot[slot]
        source_rest = _rotation(_rest_world(source, source.data.bones[source_bone]))
        target_rest = _rotation(_rest_world(target, target.data.bones[target_bone]))
        if _invented_direction(source, source.data.bones[source_bone]):
            align = aligns.get(PARENT_SLOT.get(slot), Quaternion())
        else:
            align = (source_rest @ Y_AXIS).rotation_difference(target_rest @ Y_AXIS)
        aligns[slot] = align
        corrections[target_bone] = (align @ source_rest).inverted() @ target_rest
    return corrections


def _flat(vector):
    """수평면에 투영한 방위 벡터. 거의 수직이면 None."""
    flat = Vector((vector.x, vector.y))
    return flat.normalized() if flat.length > 1e-4 else None


def _facing_axis(rotation):
    """엉덩이 본 좌표계에서 수평으로 누워 있는 축. 방위를 재는 기준으로 쓴다."""
    return next((axis for axis in (X_AXIS, Z_AXIS) if _flat(rotation @ axis) is not None), None)


def _facing_correction(context, source, target, pairs, frames, corrections):
    """첫 프레임의 모션 정면을 캐릭터 레스트 정면에 맞추는 수직축 회전.

    모캡 라이브러리는 배우가 캡처 공간에서 향한 방향이 클립마다 다르므로, 본 방향을
    그대로 옮기면 캐릭터가 옆이나 뒤를 본 채 생성된다. 기울기까지 건드리면 누운 모션이
    깨지므로 세계 Z축 둘레의 방위각만 되돌린다.
    """
    hips = next(((source_bone, target_bone) for slot, source_bone, target_bone in pairs if slot == "hips"), None)
    if hips is None:
        return Quaternion(), 0.0
    source_bone, target_bone = hips
    rest = _rotation(_rest_world(target, target.data.bones[target_bone]))
    axis = _facing_axis(rest)
    if axis is None:
        return Quaternion(), 0.0
    context.scene.frame_set(frames[0])
    source_eval = source.evaluated_get(context.evaluated_depsgraph_get())
    motion = _rotation(source_eval.matrix_world @ source_eval.pose.bones[source_bone].matrix)
    current = _flat(motion @ corrections[target_bone] @ axis)
    wanted = _flat(rest @ axis)
    if current is None or wanted is None:
        return Quaternion(), 0.0
    angle = math.atan2(current.x * wanted.y - current.y * wanted.x, current.x * wanted.x + current.y * wanted.y)
    return Quaternion(Z_AXIS, angle), angle


def _hierarchy(armature):
    order = []
    stack = [bone for bone in armature.data.bones if bone.parent is None]
    while stack:
        bone = stack.pop()
        order.append(bone)
        stack.extend(reversed(bone.children))
    return order


def _height(obj, bones):
    """다리 길이(허벅지+정강이 레스트 마디 길이). 이동 척도의 기준이다.

    땅을 딛은 발은 고관절을 중심으로 다리가 도는 만큼 몸을 밀어내므로, 엉덩이 이동은
    허벅지+정강이 길이 비로 옮겨야 스탠스 동안 발이 미끄러지지 않는다. 엉덩이 본 원점에서
    발까지의 거리로 재면 골반 오프셋(엉덩이 원점과 고관절 사이)이 리그마다 달라 비가
    어긋난다. 실측(ACCAD Walk1)에서 그 비는 다리 마디 비보다 30% 작았고, 스탠스 한 번에
    발이 8.6~9.8cm 미끄러지며 엉덩이가 22cm 들렸다. 다리 마디를 못 찾으면 엉덩이→발
    거리, 그것도 없으면 엉덩이 높이로 대신한다.
    """
    hips = bones.get("hips")
    if hips is None:
        return 0.0
    for side in ("l", "r"):
        chain = [bones.get(f"thigh_{side}"), bones.get(f"shin_{side}"), bones.get(f"foot_{side}")]
        if all(bone is not None for bone in chain):
            points = [_rest_world(obj, bone).translation for bone in chain]
            return sum((a - b).length for a, b in zip(points, points[1:]))
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
    """구간 양 끝에서는 창을 좌우 대칭으로 줄여 쓴다.

    한쪽만 잘라 쓰면 가중치를 다시 정규화해도 창이 한쪽으로 치우쳐, 기울기가 있는
    구간의 첫·끝 프레임이 안쪽으로 끌려간다. 대칭으로 줄이면 그 편향이 없다.
    """
    full = _kernel(window)
    if len(full) < 3 or len(series) < 3:
        return series
    limit = len(full) // 2
    smoothed = []
    for index in range(len(series)):
        half = min(index, len(series) - 1 - index, limit)
        if half < 1:
            smoothed.append(series[index])
            continue
        weights = _kernel(2 * half + 1)
        smoothed.append(combine([(series[index - half + offset], weight)
                                 for offset, weight in enumerate(weights)]))
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


def _plane_basis(root, mid, end, prior=None):
    """삼각형(루트·중간관절·끝점)에 붙은 정규 직교 좌표계. 없으면 None.

    Blender의 폴 타깃은 무릎 위치가 아니라 루트 본(허벅지)의 X축이 폴을 향하도록 체인을
    돌린다. 무릎이 어느 쪽으로 굽는지는 솔버가 레스트 굽힘 방향으로 정한다. 그래서 무릎이
    거의 펴진 구간에서 실측 무릎 방향만으로 폴을 놓으면, 무릎이 조금만 뒤로 꺾여(과신전)
    있어도 솔버가 허벅지를 180° 돌려 무릎을 그 자리에 맞춘다 — 다리 전체가 뒤집힌다.

    `prior`는 FK 루트 본의 비틀림에서 예측한 무릎 방향이다. 실측 `side`의 예측 방향 성분이
    루트 본 길이의 POLE_PRIOR_RATIO에 못 미치면 부족한 만큼 예측 방향을 더한다. 관절이
    펴질수록(또는 반대로 꺾일수록) 예측이 우세해 비틀림이 FK와 같아지고, 예측 쪽으로 충분히
    굽어 있으면 실측 무릎 방향이 그대로 남는다. 문턱에서 더하는 양이 0이 되므로 평면이 홱
    바뀌지 않고, 예측 방향 성분이 항상 문턱 이상이 되므로 반대쪽으로 뒤집히지도 않는다.
    """
    axis = end - root
    if axis.length < 1e-6:
        return None
    axis = axis.normalized()
    arm = mid - root
    side = arm - axis * arm.dot(axis)
    if prior is not None and arm.length > 1e-9:
        guess = prior - axis * prior.dot(axis)
        if guess.length > 1e-6:
            guess.normalize()
            shortfall = arm.length * POLE_PRIOR_RATIO - side.dot(guess)
            if shortfall > 0.0:
                side = side + guess * shortfall
    if side.length < 1e-6:
        return None
    side = side.normalized()
    return Matrix((axis, side, axis.cross(side))).transposed()


def _pole_prior(rest, rest_frame, root, pose):
    """FK 루트 본의 비틀림에서 예측한 무릎 방향. 레스트 평면이 없으면 None.

    레스트에서 무릎이 굽는 방향(rest_frame의 side)을 루트 본 로컬로 옮긴 뒤, 그 프레임의
    FK 루트 본 회전을 곱한다. Blender의 폴은 루트 본 X축을 폴로 향하게 하므로, 이 방향에
    폴을 놓으면 루트 본의 비틀림이 FK와 같아진다.
    """
    if rest_frame is None:
        return None
    local = _rotation(rest[root]).inverted() @ Vector(rest_frame.col[1])
    return _rotation(pose[root]) @ local


def _transport_mid(origin, mid, fk_end, end):
    """끝점이 FK 자리에서 옮겨졌을 때(발 고정) 무릎을 같은 스윙으로 함께 돌린다.

    FK 무릎을 그대로 두고 새 축에 투영하면, 축이 몇 도만 돌아도 무릎의 축 방향 성분이
    옆 성분으로 새어 들어와 폴 평면이 크게 돈다. 실측(CMU 94_16, 발이 8cm 옮겨진 스탠스)에서
    허벅지가 48° 비틀렸다. 뿌리→FK 끝점을 뿌리→새 끝점으로 보내는 최소 회전으로 무릎을
    옮기면 축에 대한 무릎 방향이 FK와 같게 유지된다.
    """
    before = fk_end - origin
    after = end - origin
    if before.length < 1e-6 or after.length < 1e-6 or (before - after).length < 1e-9:
        return mid
    return origin + before.rotation_difference(after) @ (mid - origin)


def _pole_position(rest_frame, rest_offset, root, mid, end, fallback, prior=None):
    """레스트에서 폴이 삼각형에 대해 갖던 관계를 현재 삼각형으로 옮긴다.

    이렇게 하면 리그의 pole_angle 규약이 무엇이든 레스트에서 성립하던 IK 해가 그대로
    재현된다. 규약을 추측하거나 부호를 맞춰 볼 필요가 없다. `prior`는 _plane_basis 참조.
    """
    if rest_frame is None:
        return fallback
    current = _plane_basis(root, mid, end, prior)
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


def _sample(context, source, target, pairs, frames, corrections, translation_scale, ground=True, smooth=0, facing=None,
            anchor_bones=(), anchor_scale=0.0, target_height=0.0):
    """프레임별로 캐릭터 본의 로컬 회전과 엉덩이 이동을 계산한다.

    anchor_bones는 원본 발이 멈춘 구간에서 IK 목표를 고정할 캐릭터 발 본이다. 돌려주는
    anchors는 본별로 프레임마다의 발목 목표 위치(아마추어 공간)다. _anchor_ends 참조.
    """
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
    facing = Quaternion() if facing is None else facing
    target_basis = target.matrix_world.copy()
    target_inverse = target_basis.inverted()
    target_rotation = _rotation(target_basis).inverted()
    hips_rest_world = _rest_world(target, target.data.bones[hips]).translation if hips else None
    rest_floor = _lowest_rest(target, target_basis, ground_bones) if ground and ground_bones else 0.0
    # 앵커 발의 원본 위치를 캐릭터 척도·아마추어 방향으로 모아 둔다. 절대 위치는 쓰지 않고
    # 프레임 사이의 차이만 쓴다(_anchor_ends).
    anchor_source = {name: mapped[name] for name in anchor_bones if name in mapped}
    source_pos = {name: [] for name in anchor_source}
    # 모션의 루트 이동은 첫 프레임을 기준으로 재는다. 리그마다 레스트 높이가 다르므로
    # 레스트를 기준으로 삼으면 캐릭터가 공중에 뜨거나 바닥을 파고든다.
    origin = None
    # 1단계: 프레임마다 캐릭터 본의 로컬 회전과 엉덩이의 세계 좌표 목표를 모은다.
    for frame in frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()
        source_eval = source.evaluated_get(depsgraph)
        source_world = source_eval.matrix_world
        for name, foot in anchor_source.items():
            foot_world = (source_world @ source_eval.pose.bones[foot].matrix).translation
            source_pos[name].append(target_rotation @ (facing @ (foot_world * anchor_scale)))
        pose = {}
        for bone in order:
            inverse = parent_rest[bone.name]
            base = pose[bone.parent.name] @ inverse @ rest[bone.name] if inverse is not None else rest[bone.name]
            source_bone = mapped.get(bone.name)
            if source_bone is None:
                pose[bone.name] = base
                continue
            motion = _rotation(source_world @ source_eval.pose.bones[source_bone].matrix)
            desired = target_rotation @ facing @ motion @ corrections[bone.name]
            location = base.to_translation()
            if bone.name == hips:
                current = (source_world @ source_eval.pose.bones[source_bone].matrix).translation
                if origin is None:
                    origin = current.copy()
                world_target = hips_rest_world + facing @ ((current - origin) * translation_scale)
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
    # 완화가 되돌려 놓은 발 높이를 놓친다. 앵커 발은 IK가 실제로 놓을 자리로 잰다.
    def replay_all():
        return [_replay(order, rest, parent_rest, rotations, index, hips,
                        rest[hips].inverted() @ (target_inverse @ hips_targets[index]) if hips and hips_targets else None)
                for index in range(len(frames))]

    # 앵커 발은 스탠스에서 발바닥을 수평으로 놓으므로(_flat_rotation) 그 최저점은 FK 발끝이
    # 아니라 발목 높이 - 레스트 발목 높이다. FK 발이 기울어 있을 때 FK 발끝으로 몸 높이를
    # 맞추면 수평 발의 발목이 다리가 닿지 않는 높이에 놓인다(실측 ACCAD Walk1 7.7cm 미달).
    ankle_height = {name: (target_basis @ rest[name].to_translation()).z - rest_floor for name in source_pos}
    free_ground = [name for name in ground_bones if _anchor_owner(target, name, source_pos) is None]

    def lowest_point(pose):
        values = [
            (target_basis @ pose[name] @ offset).z
            for name in free_ground
            for offset in (Vector((0.0, 0.0, 0.0)), Vector((0.0, target.data.bones[name].length, 0.0)))
        ]
        values += [(target_basis @ pose[name].to_translation()).z - ankle_height[name] for name in source_pos]
        return min(values)

    replays = replay_all()
    # 바닥 맞춤: 엉덩이 본 원점이 다리에 대해 어디 놓이는지는 리그마다 다르다(골반 위,
    # 다리 사이 등). 원본과 다르면 원본에서 땅을 딛던 발이 통째로 떠 있거나 파고든다.
    # 실측(ACCAD Walk1)에서 발이 10~15cm 아래로 들어가 프레임별 보정이 엉덩이를 22cm까지
    # 들었다 내렸다 했다. 프레임별 최저점의 하위 10% 지점이 바닥에 오도록 상수만큼 먼저
    # 옮기고, 프레임별 보정은 남은 관통에만 쓴다. 중앙값으로 맞추면 절반의 프레임이 몇 mm씩
    # 파고들어 그 보정이 매 프레임 튄다.
    base = 0.0
    if ground and ground_bones and hips and hips_targets:
        lows = sorted(lowest_point(pose) for pose in replays)
        base = rest_floor - lows[len(lows) // 10]
        if abs(base) > 1e-6:
            hips_targets = [world_target + Vector((0.0, 0.0, base)) for world_target in hips_targets]
            replays = replay_all()
    # 관통은 IK가 실제로 발을 놓을 자리(앵커)로 잰다. 최종 앵커는 아래에서 들어 올린 자세로
    # 다시 구한다: 스탠스 동안 발은 바닥에 붙어 있어야 하므로 스윙 발 때문에 생긴 프레임별
    # 보정에 같이 오르내리면 안 된다.
    anchors, _planted = _anchor_ends(replays, source_pos, frames, target_height) if source_pos else ({}, {})
    # 앵커 발(과 그 아래 발끝)은 엉덩이를 들어 바닥을 피하지 않고 발 목표 자체를 바닥 위로
    # 올린다(아래 클램프). 엉덩이를 들면 땅을 딛은 반대쪽 다리가 목표에 닿지 못해 발이
    # 엉덩이를 따라 오르내린다. 실측(ACCAD Walk1)에서 스윙 발끝 때문에 엉덩이가 7.5cm까지
    # 들리며 스탠스 발이 2~6cm 오르내렸다.
    if ground and free_ground:
        for pose in replays:
            floor = min(
                (target_basis @ pose[name] @ offset).z
                for name in free_ground
                for offset in (Vector((0.0, 0.0, 0.0)), Vector((0.0, target.data.bones[name].length, 0.0)))
            )
            penetration.append(max(0.0, rest_floor - floor))
    lift = _dilate(penetration) if ground and free_ground else []
    def build_final(lowered):
        """엉덩이 목표에 접지 보정과 도달 보정을 얹어 이동값과 최종 포즈를 만든다."""
        located = []
        for index, world_target in enumerate(hips_targets):
            raised = world_target.copy()
            if index < len(lift):
                raised.z += lift[index]
            if index < len(lowered):
                raised.z -= lowered[index]
            located.append((rest[hips].inverted() @ (target_inverse @ raised)))
        poses = [_replay(order, rest, parent_rest, rotations, index, hips,
                         located[index] if hips and index < len(located) else None)
                 for index in range(len(frames))]
        return located, poses

    # 최종 포즈. IK 목표 위치와 끝본 보정은 완화와 접지 보정까지 반영한 값으로 잡아야
    # FK 결과와 같은 자리에 놓인다.
    locations, final = build_final([])
    flatten = None
    if ground and ground_bones and source_pos:
        # 발 머리 기준 레스트 상대 접지점(발 꼬리, 발끝 머리·꼬리). 발끝은 스탠스에서 레스트로 두므로 레스트 값이 맞다.
        points = {}
        for name in source_pos:
            head = rest[name].to_translation()
            owned = [bone for bone in ground_bones if _anchor_owner(target, bone, source_pos) == name]
            points[name] = [rest[bone] @ offset - head for bone in owned
                            for offset in (Vector((0.0, 0.0, 0.0)), Vector((0.0, target.data.bones[bone].length, 0.0)))]
        flatten = {"basis": target_basis, "floor": rest_floor, "rest": rest, "points": points,
                   "up": _rotation(target_basis).inverted() @ Vector((0.0, 0.0, 1.0))}
    anchors, planted = _anchor_ends(final, source_pos, frames, target_height, flatten) if source_pos else ({}, {})
    # 다리 도달 보정: 땅을 딛은 발의 목표가 허벅지+정강이 길이보다 멀면 엉덩이를 그만큼 내린다
    # (올리지는 않는다). FK는 본 방향만 옮기므로 다리 비율이 다르면 두 발목 높이가 원본과 달리
    # 어긋나는데(실측 CMU 80_45: 원본 0.2cm 차이, FK 4cm 차이), 발을 바닥에 붙이면 높은 쪽
    # 다리가 닿지 못한다(목표 오차 7.5cm). 발이 바닥에 닿는 것이 엉덩이 높이보다 우선이다.
    lowered = []
    if flatten is not None and anchors and hips:
        deficits = [0.0] * len(frames)
        for name, ends in anchors.items():
            shin = target.data.bones[name].parent
            thigh = shin.parent if shin is not None else None
            if thigh is None:
                continue
            reach = (shin.length + thigh.length) * (1.0 - REACH_MARGIN)
            flags = planted.get(name, [])
            for index, pose in enumerate(final):
                if index >= len(flags) or not flags[index]:
                    continue
                deficit = (ends[index] - pose[thigh.name].to_translation()).length - reach
                if deficit > deficits[index]:
                    deficits[index] = deficit
        if any(deficits):
            lowered = _dilate(deficits)
            locations, final = build_final(lowered)
            anchors, planted = _anchor_ends(final, source_pos, frames, target_height, flatten)
    if ground and anchors:
        _clamp_anchors(target, final, anchors, planted, ground_bones, target_basis, rest_floor)
    return (rotations, locations, hips, (max(lift) if lift else 0.0), sum(1 for value in penetration if value > 1e-6), final,
            anchors, base, planted, (max(lowered) if lowered else 0.0))


def _stance_segments(positions, frames, height):
    """원본 발이 멈춰 있는 구간 [(시작, 끝) ...). 끝은 포함하지 않는다."""
    limit = height * STANCE_SPEED_RATIO
    planted = [False] * len(positions)
    for index in range(1, len(positions)):
        gap = max(1, frames[index] - frames[index - 1])
        planted[index] = (positions[index] - positions[index - 1]).length / gap < limit
    if len(planted) > 1:
        planted[0] = planted[1]
    segments = []
    index = 0
    while index < len(planted):
        if not planted[index]:
            index += 1
            continue
        low = index
        while index < len(planted) and planted[index]:
            index += 1
        if index - low >= STANCE_MIN_FRAMES:
            # 한두 프레임 노이즈로 끊긴 스탠스는 하나로 잇는다. 따로 두면 구간마다 FK 평균이
            # 달라 그 사이에서 발이 자리를 옮긴다.
            if segments and low - segments[-1][1] <= STANCE_BLEND_FRAMES:
                segments[-1] = (segments[-1][0], index)
            else:
                segments.append((low, index))
    return segments


def _anchor_ends(replays, source_pos, frames, height, flatten=None):
    """원본 발이 땅을 딛고 있는 동안 IK 발목 목표를 붙잡아 둔다.

    본 방향만 옮기는 FK는 캐릭터의 다리 기하(골반 폭, 다리 마디 길이, 엉덩이 원점과
    고관절의 관계)가 원본과 다르면, 원본에서 땅을 딛고 가만히 있던 발도 몸이 흔들리는
    만큼 미끄러진다. 실측(CMU 80_45 서 있는 자세)에서 원본 발은 0.3~0.7cm 안에 머물렀는데
    FK 발은 1.2~3.3cm를 움직였다.

    원본 발이 멈춘 구간(스탠스)마다 FK 발 위치의 구간 평균에 원본 발의 미세한 움직임만
    얹어 목표로 삼는다. 발이 서는 자리는 FK가 정하고, 흔들림은 원본만큼만 남는다. 스윙
    구간은 FK를 그대로 따르고, 스탠스 앞뒤 STANCE_BLEND_FRAMES 동안 두 값을 선형으로
    잇는다. 클립 전체에서 FK와 원본의 차이를 상수로 보고 빼는 방식은 걷기에서 스윙 위상마다
    차이가 달라 다리 방향이 20~36° 벗어났으므로 쓰지 않는다.

    flatten이 있으면 스탠스 동안 발 자세를 _flat_rotation(발바닥 수평)으로 보고, 발·발끝의
    최저 접지점이 바닥에 오도록 발목 높이를 프레임마다 정한다. 원본 발목의 상하 미세 움직임은
    얹지 않는다.
    """
    anchors = {}
    planted = {}
    zero = Vector((0.0, 0.0, 0.0))
    for name, source in source_pos.items():
        if len(source) != len(replays):
            continue
        fk = [pose[name].to_translation() for pose in replays]
        count = len(fk)
        delta = [zero.copy() for _index in range(count)]
        segments = _stance_segments(source, frames, height)
        planted[name] = [any(low <= index < high for low, high in segments) for index in range(count)]
        for low, high in segments:
            fk_mean = sum(fk[low:high], zero.copy()) / (high - low)
            source_mean = sum(source[low:high], zero.copy()) / (high - low)
            for index in range(low, high):
                wobble = source[index] - source_mean
                if flatten is None:
                    delta[index] = fk_mean + wobble - fk[index]
                    continue
                up = flatten["up"]
                wobble = wobble - up * wobble.dot(up)
                anchor = fk_mean + wobble
                rest_rotation = _rotation(flatten["rest"][name])
                rotation = _flat_rotation(_rotation(replays[index][name]), rest_rotation, up)
                basis_rotation = _rotation(flatten["basis"])
                # 접지점은 레스트 아마추어 공간 벡터이므로 레스트 회전을 벗긴 뒤 원하는 회전을 입힌다.
                lowest = min((basis_rotation @ (rotation @ (rest_rotation.inverted() @ point))).z
                             for point in flatten["points"][name])
                world = flatten["basis"] @ anchor
                world.z = flatten["floor"] - lowest
                delta[index] = flatten["basis"].inverted() @ world - fk[index]
        # 스탠스 사이·앞뒤의 스윙 구간을 잇는다. 짧은 틈은 양쪽 끝값을 선형으로 잇고,
        # 긴 틈은 STANCE_BLEND_FRAMES 동안 0으로 줄였다가 다시 키운다.
        edges = [(-1, None)] + [(low, high) for low, high in segments] + [(count, None)]
        for (_low, previous_high), (next_low, _high) in zip(edges, edges[1:]):
            gap_start = previous_high if previous_high is not None else 0
            gap_end = next_low
            if gap_end <= gap_start:
                continue
            before = delta[gap_start - 1] if previous_high is not None else None
            after = delta[gap_end] if gap_end < count else None
            span = gap_end - gap_start
            for index in range(gap_start, gap_end):
                if before is not None and after is not None and span <= 2 * STANCE_BLEND_FRAMES:
                    weight = (index - gap_start + 1) / (span + 1)
                    delta[index] = before * (1.0 - weight) + after * weight
                    continue
                value = zero.copy()
                if before is not None:
                    fade = 1.0 - (index - gap_start + 1) / (STANCE_BLEND_FRAMES + 1)
                    if fade > 0.0:
                        value = value + before * fade
                if after is not None:
                    rise = 1.0 - (gap_end - index) / (STANCE_BLEND_FRAMES + 1)
                    if rise > 0.0:
                        value = value + after * rise
                delta[index] = value
        anchors[name] = [position + shift for position, shift in zip(fk, delta)]
    return anchors, planted


def _planted_weights(flags):
    """스탠스 프레임은 1, 밖으로 STANCE_BLEND_FRAMES 동안 0으로 줄어드는 가중치."""
    count = len(flags)
    weights = [0.0] * count
    for index in range(count):
        if flags[index]:
            weights[index] = 1.0
            continue
        distance = None
        for step in range(1, STANCE_BLEND_FRAMES + 1):
            if (index - step >= 0 and flags[index - step]) or (index + step < count and flags[index + step]):
                distance = step
                break
        if distance is not None:
            weights[index] = 1.0 - distance / (STANCE_BLEND_FRAMES + 1)
    return weights


def _flat_rotation(fk_rotation, rest_rotation, up, pitch=0.0):
    """레스트 발바닥 자세를 FK 발의 방위각만큼 돌린 회전. pitch만큼 발끝을 들 수 있다.

    스탠스에서는 pitch 0으로 써서 발바닥이 바닥에 평평하게 놓인다. 원본 발의 피치를 그대로
    얹어 봤지만(CMU 80_45에서 레스트 대비 2.5~7.5° 발끝 들림), 그것이 바로 사용자가 본
    "발끝이 들린" 모습이어서 스탠스에서는 평평하게 놓는다. 뒤꿈치를 실제로 드는 동작은 발목이
    움직여 스탠스에서 빠지므로 FK를 따른다.

    본 방향만 옮기는 FK는 원본 발 본의 방향(발목→발끝 관절)을 그대로 따르는데, 캐릭터
    발 본의 기하(발목 높이·발 길이)가 원본과 다르면 원본 발이 바닥에 평평히 닿아 있어도
    캐릭터 발바닥은 기울고 발끝이 뜬다. 실측(CMU 80_45 서 있는 자세)에서 발바닥이 18~20°
    기울고 오른발 발끝이 3.5cm 떠 있었다. 레스트에서는 발바닥이 바닥에 평평히 닿아 있으므로
    (레스트 바닥이 발·발끝의 최저점으로 정의됨) 레스트 자세에 방위각만 얹는다.
    """
    forward = fk_rotation @ Y_AXIS
    rest_forward = rest_rotation @ Y_AXIS
    forward = forward - up * forward.dot(up)
    rest_forward = rest_forward - up * rest_forward.dot(up)
    if forward.length < 1e-6 or rest_forward.length < 1e-6:
        return fk_rotation
    yaw = math.atan2(up.dot(rest_forward.cross(forward)), rest_forward.dot(forward))
    yawed = Quaternion(up, yaw) @ rest_rotation
    if abs(pitch) < 1e-6:
        return yawed
    heading = yawed @ Y_AXIS
    heading = heading - up * heading.dot(up)
    axis = heading.cross(up)
    if axis.length < 1e-6:
        return yawed
    return Quaternion(axis.normalized(), pitch) @ yawed


def _anchor_owner(target, name, anchors):
    """본이 앵커 발 자신이거나 그 자손이면 그 앵커 발 이름, 아니면 None."""
    bone = target.data.bones[name]
    while bone is not None:
        if bone.name in anchors:
            return bone.name
        bone = bone.parent
    return None


def _clamp_anchors(target, poses, anchors, planted, ground_bones, target_basis, rest_floor):
    """스윙 중인 앵커 발의 발·발끝이 바닥 아래로 내려가면 그 프레임의 발목 목표를 그만큼 올린다.

    발끝 위치는 FK 자세의 발 방향(끝본 보정이 그대로 맞추는 방향)에 앵커 이동량을 더해 잰다.
    땅을 딛은(스탠스) 프레임은 건너뛴다. 거의 펴진 다리의 발목을 몇 mm만 올려도 무릎이
    10° 넘게 튀어나오기 때문이다(다리 0.52에서 3mm면 약 12°). 스탠스에서 남는 관통은
    바닥 맞춤이 하위 10% 지점을 쓰므로 몇 mm 수준이다.
    """
    inverse = target_basis.inverted()
    owned = {name: [bone for bone in ground_bones if _anchor_owner(target, bone, anchors) == name] for name in anchors}
    for name, ends in anchors.items():
        flags = planted.get(name, [])
        for index, pose in enumerate(poses):
            if index < len(flags) and flags[index]:
                continue
            delta = ends[index] - pose[name].to_translation()
            lowest = min(
                (target_basis @ (pose[bone] @ offset + delta)).z
                for bone in owned[name]
                for offset in (Vector((0.0, 0.0, 0.0)), Vector((0.0, target.data.bones[bone].length, 0.0)))
            )
            deficit = rest_floor - lowest
            if deficit > 1e-6:
                ends[index] = inverse @ (target_basis @ ends[index] + Vector((0.0, 0.0, deficit)))


def _anchor_targets(target, setups, foot_bones):
    """IK 체인이 끝나는 발 본. use_tail 체인은 끝본 꼬리에 머리가 붙은 발 자식이다."""
    anchored = {}
    for setup in setups:
        tip = setup["tip"]
        if not setup["use_tail"]:
            if tip in foot_bones:
                anchored[setup["control"]] = tip
            continue
        tail = target.data.bones[tip].tail_local
        for child in target.data.bones[tip].children:
            if child.name in foot_bones and (child.head_local - tail).length < 1e-4:
                anchored[setup["control"]] = child.name
                break
    return anchored


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


def _merge_segments(segments, fit, tolerance):
    """이웃한 두 구간을 하나로 다시 적합해 허용치 안이면 합친다.

    쪼개기는 가장 어긋난 지점에서 위에서 아래로 내려가므로 매듭이 최적 위치에 놓이지
    않는다. 합쳐 보는 패스를 한 번 돌리면 같은 허용치에서 매듭이 눈에 띄게 줄어든다.
    합친 구간은 다음 순회에서 다시 합침 후보가 되므로 더 못 합칠 때까지 반복한다.
    """
    merged = True
    while merged and len(segments) > 1:
        merged = False
        index = 0
        while index + 1 < len(segments):
            low, high = segments[index][0], segments[index + 1][1]
            controls, worst, _chosen = fit(low, high)
            if worst <= tolerance:
                segments[index:index + 2] = [(low, high, controls)]
                merged = True
            else:
                index += 1
    return segments


def _select_knots(frames, channels, tolerance, metric):
    """허용치를 지키면서 매듭을 가장 적게 쓰는 위치를 고른다.

    구간 하나로 맞춰 보고 오차가 넘으면 가장 어긋난 지점에서 쪼갠다. 키를 표본
    프레임에만 놓는 방식과 달리 구간이 데이터에 맞게 휘므로 같은 오차에서 매듭이
    훨씬 적게 남는다. 쪼갠 뒤에는 이웃 구간을 다시 합쳐 보아 하향식 쪼개기가 남긴
    불필요한 매듭을 걷어낸다.

    여기서는 구간마다 독립으로 적합해 위치만 빠르게 훑는다. 실제 제어점은 매듭에서
    접선이 이어지도록 _fit_group이 곡선 전체를 다시 풀어 얻는다.
    """
    count = len(frames)

    def fit(low, high):
        """구간 하나를 적합해 (제어점들, 최악 오차, 최악 위치)를 돌려준다."""
        width = float(frames[high] - frames[low]) or 1.0
        spans = {position: (frames[position] - frames[low]) / width for position in range(low, high + 1)}
        controls = [_solve_handles(spans, values, low, high) for values in channels]
        worst, chosen = _segment_worst(frames, channels, (low, high, controls), metric, tolerance)
        return controls, worst, chosen

    segments = []
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
    segments = _merge_segments(segments, fit, tolerance)
    return [segments[0][0]] + [segment[1] for segment in segments], segments


def _prior_tangents(times, heights):
    """매듭만 지나는 부드러운 곡선의 기울기.

    내부 표본이 없는 구간에서는 이 값이 해를 정한다. 캣멀롬 기울기를 쓰되 국소 극값에서는
    0으로 두고 이웃 기울기의 3배를 넘으면 잘라, 단조 구간이 부풀어 발이 바닥을 뚫는
    오버슈트가 생기지 않게 한다.
    """
    count = len(times)
    if count < 2:
        return [0.0] * count
    secants = [(heights[index + 1] - heights[index]) / ((times[index + 1] - times[index]) or 1.0)
               for index in range(count - 1)]
    tangents = []
    for index in range(count):
        before = secants[index - 1] if index > 0 else secants[0]
        after = secants[index] if index < count - 1 else secants[-1]
        if before * after <= 0.0:
            tangents.append(0.0)
            continue
        limit = 3.0 * min(abs(before), abs(after))
        slope = (before + after) / 2.0
        tangents.append(math.copysign(min(abs(slope), limit), slope))
    return tangents


def _solve_tridiagonal(diagonal, upper, rhs):
    """대칭 삼중대각 연립방정식을 전방소거·후방대입으로 푼다."""
    count = len(diagonal)
    pivots, values = list(diagonal), list(rhs)
    for index in range(1, count):
        if abs(pivots[index - 1]) < 1e-12:
            pivots[index - 1] = 1e-12
        factor = upper[index - 1] / pivots[index - 1]
        pivots[index] -= factor * upper[index - 1]
        values[index] -= factor * values[index - 1]
    if abs(pivots[-1]) < 1e-12:
        pivots[-1] = 1e-12
    solution = [0.0] * count
    solution[-1] = values[-1] / pivots[-1]
    for index in range(count - 2, -1, -1):
        solution[index] = (values[index] - upper[index] * solution[index + 1]) / pivots[index]
    return solution


def _solve_tangents(frames, values, knots, times, prior):
    """매듭마다 좌우 핸들이 한 기울기를 쓰도록 곡선 전체를 한 번에 최소제곱으로 푼다.

    핸들의 x를 구간의 1/3에 두므로, 매듭 하나에 기울기 하나만 쓰면 좌우 핸들이 저절로
    일직선이 된다. 구간마다 따로 적합하면 매듭에서 좌우 접선이 어긋나 그래프가 키마다
    꺾이고 핸들이 break된 채로 남는다. 이렇게 묶어 풀면 곡선이 C1 연속이 되어 손·머리·
    척추가 키 지점에서 떠는 현상이 사라진다.

    표본 하나는 자기 구간의 두 매듭만 건드리므로 정규방정식이 삼중대각이다.
    """
    count = len(knots)
    diagonal = [0.0] * count
    upper = [0.0] * max(0, count - 1)
    rhs = [0.0] * count
    for segment in range(count - 1):
        low, high = knots[segment], knots[segment + 1]
        width = (times[segment + 1] - times[segment]) or 1.0
        first, last = values[low], values[high]
        for position in range(low + 1, high):
            t = (frames[position] - times[segment]) / width
            one = 1.0 - t
            left = one * one * t * width
            right = -one * t * t * width
            residual = values[position] - ((one + 3.0 * t) * one * one * first
                                           + (3.0 * one + t) * t * t * last)
            diagonal[segment] += left * left
            diagonal[segment + 1] += right * right
            upper[segment] += left * right
            rhs[segment] += left * residual
            rhs[segment + 1] += right * residual
    for index in range(count):
        near = ([times[index + 1] - times[index]] if index < count - 1 else [])
        near += ([times[index] - times[index - 1]] if index > 0 else [])
        span = sum(near) / len(near) if near else 1.0
        weight = TANGENT_PRIOR * span * span
        diagonal[index] += weight
        rhs[index] += weight * prior[index]
    return _solve_tridiagonal(diagonal, upper, rhs)


def _tangent_segments(frames, channels, knots):
    """푼 매듭 기울기를 구간별 제어점으로 바꾼다."""
    times = [float(frames[knot]) for knot in knots]
    tangents = [_solve_tangents(frames, values, knots, times,
                                _prior_tangents(times, [values[knot] for knot in knots]))
                for values in channels]
    segments = []
    for index in range(len(knots) - 1):
        low, high = knots[index], knots[index + 1]
        width = (times[index + 1] - times[index]) or 1.0
        segments.append((low, high,
                         [(values[low] + slopes[index] * width / 3.0,
                           values[high] - slopes[index + 1] * width / 3.0)
                          for values, slopes in zip(channels, tangents)]))
    return segments


def _segment_worst(frames, channels, segment, metric, tolerance):
    """허용치를 연속으로 벗어난 곳에서만 최악 오차와 그 위치를 돌려준다.

    한 프레임만 벗어난 표본은 모캡 노이즈로 보고 넘긴다. 그 자리에 매듭을 놓으면 곡선이
    노이즈를 따라가느라 서로 이웃한 프레임에 키가 줄줄이 박히고, 그래프의 흐름과 상관없는
    키가 남는다. NOISE_RUN 프레임 이상 연달아 벗어났거나 한 프레임이라도 허용치의
    NOISE_PEAK배를 넘으면 실제 동작이므로 매듭을 놓는다.

    허용치가 0이면 비교 기준이 없으므로 그냥 최대 오차를 돌려준다.
    """
    low, high, controls = segment
    width = float(frames[high] - frames[low]) or 1.0
    spans = {position: (frames[position] - frames[low]) / width for position in range(low, high + 1)}
    worst, chosen = 0.0, -1
    run, peak, peak_at = 0, 0.0, -1
    for position in range(low + 1, high + 1):
        error = 0.0
        if position < high:
            predicted = tuple(_evaluate(control, spans, values, low, high, position)
                              for control, values in zip(controls, channels))
            actual = tuple(values[position] for values in channels)
            error = metric(actual, predicted)
        if tolerance <= 0.0:
            if error > worst:
                worst, chosen = error, position
            continue
        if position < high and error > tolerance:
            run += 1
            if error > peak:
                peak, peak_at = error, position
            continue
        if (run >= NOISE_RUN or peak > NOISE_PEAK * tolerance) and peak > worst:
            worst, chosen = peak, peak_at
        run, peak, peak_at = 0, 0.0, -1
    return worst, chosen


def _tangent_offenders(frames, channels, segments, tolerance, metric):
    """접선을 이은 곡선이 허용치를 넘는 구간마다 가장 어긋난 표본 위치를 모은다."""
    picked = set()
    for segment in segments:
        worst, chosen = _segment_worst(frames, channels, segment, metric, tolerance)
        if chosen >= 0 and worst > tolerance:
            picked.add(chosen)
    return picked


def _prune_knots(frames, channels, knots, tolerance, metric):
    """매듭을 하나씩 빼 보고 허용치를 지키면 버린다.

    접선을 이어 풀면 구간이 이웃의 정보까지 쓰므로, 구간별 독립 적합이 고른 매듭 중
    상당수가 필요 없어진다. 이 패스가 없으면 연속 조건을 지키느라 키가 오히려 는다.

    매듭 하나를 빼면 삼중대각 해가 전 구간에서 조금씩 움직이지만 영향은 매듭을 건널
    때마다 빠르게 줄어든다. 그래서 여기서는 뺀 자리 둘레만 다시 재고, 전체 검증은
    부르는 쪽에서 한 번에 한다.
    """
    kept = list(knots)
    index = 1
    while index < len(kept) - 1:
        trial = kept[:index] + kept[index + 1:]
        segments = _tangent_segments(frames, channels, trial)
        low = trial[max(0, index - 2)]
        high = trial[min(len(trial) - 1, index + 1)]
        if all(_segment_worst(frames, channels, segment, metric, tolerance)[0] <= tolerance
               for segment in segments if segment[1] > low and segment[0] < high):
            kept = trial
        else:
            index += 1
    return kept


def _fit_group(frames, channels, tolerance, metric):
    """허용치를 지키는 매듭을 고르고, 매듭에서 접선이 이어지는 베지어 구간을 만든다.

    매듭 위치는 구간별 독립 적합으로 훑고(_select_knots), 제어점은 매듭마다 기울기
    하나를 공유하도록 곡선 전체를 다시 풀어 얻는다(_solve_tangents). 다시 푼 곡선이
    허용치를 넘는 구간에는 가장 어긋난 자리에 매듭을 더하고, 반대로 남아도는 매듭은
    빼 본다(_prune_knots). 연속 조건만 놓고 보면 매듭당 자유도가 둘에서 하나로 줄어
    키가 조금 늘지만, 한 프레임짜리 튐을 매듭으로 세지 않는 판정(_segment_worst)까지
    합치면 실측 CMU 3개 클립에서 키가 11~19% 줄고 키 간격이 1프레임인 비율도 25%에서
    12~15%로 떨어진다. 키마다 꺾이던 접선도 사라진다.

    돌려주는 값은 (매듭 인덱스, 채널별 구간 제어점)이다.
    """
    count = len(frames)
    if count < 2:
        return list(range(count)), []
    if tolerance <= 0.0:
        # 간소화를 끄면 모든 프레임을 매듭으로 남긴다. 그래도 접선은 이어 부드럽게 만든다.
        knots = list(range(count))
        return knots, _tangent_segments(frames, channels, knots)
    knots = _select_knots(frames, channels, tolerance, metric)[0]
    segments = _tangent_segments(frames, channels, knots)
    for _round in range(TANGENT_ROUNDS):
        extra = _tangent_offenders(frames, channels, segments, tolerance, metric)
        if not extra:
            break
        knots = sorted(set(knots) | extra)
        segments = _tangent_segments(frames, channels, knots)
    for _round in range(TANGENT_ROUNDS):
        pruned = _prune_knots(frames, channels, knots, tolerance, metric)
        if len(pruned) == len(knots):
            break
        knots, segments = pruned, _tangent_segments(frames, channels, pruned)
    # 솎아내기는 뺀 자리 둘레만 보므로, 전체를 다시 재어 넘치는 자리를 채운다.
    for _round in range(TANGENT_ROUNDS):
        extra = _tangent_offenders(frames, channels, segments, tolerance, metric)
        if not extra:
            break
        knots = sorted(set(knots) | extra)
        segments = _tangent_segments(frames, channels, knots)
    return knots, segments


def _write_group(bag, path, group, frames, channels, knots, segments):
    """적합 결과를 베지어 곡선으로 쓴다.

    매듭마다 좌우 핸들이 한 기울기를 공유하도록 풀었으므로(_solve_tangents) 두 핸들은
    이미 일직선이다. 핸들 유형을 ALIGNED로 남겨 두어야 그래프 편집기에서 키가 break된
    상태로 보이지 않고, 사용자가 한쪽 핸들을 잡아도 반대쪽이 따라와 곡선이 계속 이어진다.
    """
    curves = []
    # 직접 대입은 문자열 enum을 받는다. 정수는 foreach_set에서만 쓴다.
    for index, values in enumerate(channels):
        curve = bag.fcurves.new(data_path=path, index=index, group_name=group)
        curve.keyframe_points.add(len(knots))
        for position, knot in enumerate(knots):
            key = curve.keyframe_points[position]
            key.co = (float(frames[knot]), float(values[knot]))
            key.interpolation = "BEZIER"
            # 좌표를 직접 넣는 동안에는 FREE여야 블렌더가 우리 값을 되돌리지 않는다.
            key.handle_left_type = "FREE"
            key.handle_right_type = "FREE"
            key.handle_left = key.co
            key.handle_right = key.co
        for position, (low, high, controls) in enumerate(segments):
            width = float(frames[high] - frames[low]) or 1.0
            left, right = controls[index]
            curve.keyframe_points[position].handle_right = (frames[low] + width / 3.0, left)
            curve.keyframe_points[position + 1].handle_left = (frames[high] - width / 3.0, right)
        _mirror_ends(curve)
        for key in curve.keyframe_points:
            key.handle_left_type = "ALIGNED"
            key.handle_right_type = "ALIGNED"
        curve.update()
        curves.append(curve)
    return curves


def _mirror_ends(curve):
    """양 끝 키의 바깥쪽 핸들을 안쪽 핸들의 반대편으로 맞춘다.

    바깥쪽 핸들은 곡선 평가에 쓰이지 않지만, 안쪽과 일직선이 아니면 ALIGNED로 바꿀 때
    블렌더가 안쪽 핸들을 평균 방향으로 돌려 첫·끝 구간의 접선이 틀어진다.
    """
    points = curve.keyframe_points
    if len(points) < 2:
        return
    for key, inner, outer in ((points[0], "handle_right", "handle_left"),
                              (points[len(points) - 1], "handle_left", "handle_right")):
        near = getattr(key, inner)
        setattr(key, outer, (2.0 * key.co.x - near.x, 2.0 * key.co.y - near.y))


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


def _pole_tolerance(track, simplify):
    """폴 위치 곡선의 허용 오차.

    폴을 반경 r만큼 떨어진 자리에서 옮기면 무릎이 도는 각은 대략 (거리 / r)이다.
    캐릭터 키를 기준으로 허용치를 잡으면 r이 그보다 훨씬 작은 리그에서 무릎이 허용치의
    몇 배로 홱 돌아 다리가 튄다. 반경을 기준으로 잡아 무릎이 도는 각을 바로 묶는다.
    """
    radius = track.get("pole_radius") or 0.0
    if radius <= 1e-6:
        return 0.0
    return radius * math.radians(simplify)


def _baked_poses(context, target, frames):
    """지금 걸린 곡선이 실제로 만드는 본 행렬을 프레임마다 읽는다."""
    scene = context.scene
    captured = []
    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()
        captured.append({bone.name: bone.matrix.copy() for bone in target.pose.bones})
    return captured


def _ik_channels(target, setups, poses, residuals=None, live=None, anchors=None, anchored=None):
    """프레임별 최종 포즈에서 IK 컨트롤과 폴 본의 로컬 이동값을 만든다.

    residuals는 컨스트레인트별 폴 각도 보정값(라디안)이다. 리그의 레스트 자세가 그
    리그의 IK 해와 정확히 일치하지 않으면 무릎이 일정 각도만큼 돌아간 채 풀리므로,
    실측한 상수 잔차를 여기서 되돌린다.

    live는 간소화한 곡선이 실제로 만든 프레임별 본 행렬이다. 곡선을 솎아내면 척추와
    엉덩이가 표본에서 조금 벗어나 다리 뿌리가 움직인다. 목표를 표본 그대로 두면 뿌리와
    발 사이 거리가 프레임마다 흔들리는데, 다리가 거의 펴진 구간에서는 이 거리가 조금만
    달라져도 무릎 각이 크게 돌아 다리가 튄다. 그래서 목표를 실제 뿌리에 맞춰 옮겨
    삼각형을 그대로 유지한다. 발은 뿌리가 벗어난 만큼(엉덩이 이동 오차 이하) 같이
    움직이지만, 그 값은 부드럽게 변하므로 튀지 않는다.

    anchors/anchored가 있으면 그 체인의 끝점은 FK 발 대신 앵커 위치(_anchor_ends)로 잡는다.
    """
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    tracks = []
    for setup in setups:
        tip, root, control, pole = setup["tip"], setup["root"], setup["control"], setup["pole"]
        anchor = (anchors or {}).get((anchored or {}).get(control))
        length = target.data.bones[tip].length
        offset = Vector((0.0, length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
        rest_root = rest[root].to_translation()
        rest_mid = rest[tip].to_translation()
        rest_end = rest[tip] @ offset
        rest_frame = _plane_basis(rest_root, rest_mid, rest_end)
        rest_offset = None
        # 폴이 체인 축에서 떨어진 거리. 폴을 이만큼 반경으로 돌리는 셈이므로, 폴 위치의
        # 허용 오차를 각도로 환산할 때의 기준이 된다.
        pole_radius = 0.0
        if rest_frame is not None and pole:
            rest_offset = rest_frame.transposed() @ (rest[pole].to_translation() - rest_root)
            pole_radius = Vector((0.0, rest_offset.y, rest_offset.z)).length
        control_track, pole_track, ends = [], [], []
        for index, pose in enumerate(poses):
            actual = live[index] if live else None
            # 표본에서의 다리 뿌리와 실제로 구워진 뿌리의 차이만큼 삼각형을 통째로 옮긴다.
            shift = (actual[root].to_translation() - pose[root].to_translation()
                     if actual else Vector((0.0, 0.0, 0.0)))
            fk_end = (pose[tip] @ offset) + shift
            end = (anchor[index] + shift) if anchor else fk_end
            ends.append(end)
            control_base = actual[control] if actual else pose[control]
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
                pole_base = actual[pole] if actual else pose[pole]
            origin = pose[root].to_translation() + shift
            mid = _transport_mid(origin, pose[tip].to_translation() + shift, fk_end, end)
            wanted = _pole_position(rest_frame, rest_offset, origin, mid, end,
                                    pole_base.to_translation(),
                                    _pole_prior(rest, rest_frame, root, pose))
            angle = (residuals or {}).get(setup["control"], 0.0)
            if angle:
                axis = end - origin
                if axis.length > 1e-6:
                    wanted = origin + Matrix.Rotation(angle, 3, axis.normalized()) @ (wanted - origin)
            pole_track.append(pole_base.inverted() @ wanted)
        tracks.append({"setup": setup, "control": control_track, "pole": pole_track,
                       "pole_radius": pole_radius, "ends": ends, "anchored": anchor is not None})
    return tracks


def _write_curves(target, action, frames, rotations, locations, hips, simplify=0.0, scale=1.0,
                  tighten_location=1.0):
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
        # IK를 쓸 때는 이 곡선이 다리 뿌리를 흔들어 무릎을 튀게 하므로 더 조인다.
        tolerance = scale * math.radians(simplify) / tighten_location
        count, error = _bake_group(bag, path, hips, frames, channels, tolerance, _distance_error)
        written += count
        shift_error = error
    written += _write_influence(bag, target, frames, ())[0]
    return written, angle_error, shift_error, bag


def _shift_keys(bag, shift):
    """채널백의 모든 키와 핸들을 프레임 축으로 shift만큼 옮긴다."""
    for curve in bag.fcurves:
        points = curve.keyframe_points
        for attribute in ("co", "handle_left", "handle_right"):
            values = [0.0] * (len(points) * 2)
            points.foreach_get(attribute, values)
            values[0::2] = [value + shift for value in values[0::2]]
            points.foreach_set(attribute, values)
        curve.update()


def _write_influence(bag, target, frames, ik_tracks):
    """IK 컨스트레인트 영향 키를 다시 쓴다.

    IK로 구울 때는 우리가 값을 채운 체인만 1로 되돌리고, FK로 구울 때는 0으로 눌러야
    구운 회전 키가 그대로 보인다.
    """
    driven = {track["setup"]["constraint"] for track in ik_tracks}
    influence = 1.0 if ik_tracks else 0.0
    written = 0
    disabled = []
    for bone in target.pose.bones:
        for constraint in bone.constraints:
            if constraint.type != "IK":
                continue
            value = influence if constraint.name in driven or not ik_tracks else 0.0
            constraint.influence = value
            path = constraint.path_from_id("influence")
            for curve in [item for item in bag.fcurves if item.data_path == path]:
                bag.fcurves.remove(curve)
            curve = bag.fcurves.new(data_path=path, index=0, group_name=bone.name)
            key = curve.keyframe_points.insert(frames[0], value)
            key.interpolation = "CONSTANT"
            curve.update()
            written += 1
            if value == 0.0:
                disabled.append(f"{bone.name}/{constraint.name}")
    return written, disabled


def _write_ik_curves(bag, target, frames, ik_tracks, simplify, scale):
    """IK 컨트롤·폴 위치 곡선과 영향 키를 쓴다."""
    written = 0
    shift_error = 0.0
    for track in ik_tracks:
        for kind in ("control", "pole"):
            series = track[kind]
            if not series:
                continue
            name = track["setup"][kind]
            channels = [[value[index] for value in series] for index in range(3)]
            path = target.pose.bones[name].path_from_id("location")
            count, error = _bake_group(bag, path, name, frames, channels,
                                       _pole_tolerance(track, simplify) if kind == "pole"
                                       else scale * math.radians(simplify) / IK_CURVE_TIGHTEN,
                                       _distance_error)
            written += count
            shift_error = max(shift_error, error)
    count, disabled = _write_influence(bag, target, frames, ik_tracks)
    return written + count, disabled, shift_error


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


def _pole_residuals(context, target, tracks, poses, frames, probes=5):
    """구운 결과에서 무릎이 원하는 자리에서 얼마나 돌아갔는지 잰다.

    폴 각도 규약은 리그마다 다르고 컨스트레인트의 pole_angle과도 별개로 레스트 자세가
    어긋날 수 있다. 규약을 추측하는 대신 Blender가 실제로 푼 결과를 읽어 상수 오차를
    구한다. 구간에 흩은 몇 프레임의 중앙값을 쓴다.
    """
    scene = context.scene
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    span = len(frames)
    picked = sorted({max(0, min(span - 1, span * (index + 1) // (probes + 1))) for index in range(probes)})
    gathered = {track["setup"]["control"]: [] for track in tracks if track["setup"]["pole"]}
    for index in picked:
        scene.frame_set(frames[index])
        context.view_layer.update()
        pose = poses[index]
        for track in tracks:
            setup = track["setup"]
            if not setup["pole"]:
                continue
            tip, root = setup["tip"], setup["root"]
            offset = Vector((0.0, target.data.bones[tip].length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
            origin = target.pose.bones[root].matrix.to_translation()
            # 발 고정으로 끝점이 옮겨졌으면 축과 무릎도 그 자리 기준으로 잰다.
            end = track["ends"][index]
            axis = end - origin
            if axis.length < 1e-6:
                continue
            axis.normalize()
            wanted = _transport_mid(origin, pose[tip].to_translation(), pose[tip] @ offset, end) - origin
            solved = target.pose.bones[tip].matrix.to_translation() - origin
            wanted = wanted - axis * wanted.dot(axis)
            solved = solved - axis * solved.dot(axis)
            if wanted.length < 1e-5 or solved.length < 1e-5:
                continue
            # 폴이 실측 무릎 방향 대신 루트 본 비틀림 예측을 따른 프레임(_plane_basis 참조)은
            # 무릎이 원래 그 자리에 있을 이유가 없으므로 잔차로 세지 않는다.
            rest_frame = _plane_basis(rest[root].to_translation(), rest[tip].to_translation(), rest[tip] @ offset)
            prior = _pole_prior(rest, rest_frame, root, pose)
            if prior is not None:
                guess = prior - axis * prior.dot(axis)
                floor = target.data.bones[root].length * POLE_PRIOR_RATIO
                if guess.length < 1e-6 or wanted.dot(guess.normalized()) < floor:
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
    written = 0
    for track in tracks:
        name = track["setup"]["pole"]
        if not name or not track["pole"]:
            continue
        curve_path = target.pose.bones[name].path_from_id("location")
        for curve in [curve for curve in bag.fcurves if curve.data_path == curve_path]:
            bag.fcurves.remove(curve)
        channels = [[value[index] for value in track["pole"]] for index in range(3)]
        count, _error = _bake_group(bag, curve_path, name, frames, channels,
                                    _pole_tolerance(track, simplify), _distance_error)
        written += count
    return written


def _bake_followers(context, target, bag, frames, deferred, poses, simplify, tracks, flatten=None):
    """IK가 정한 부모 방향 위에서 끝본의 세계 방향을 FK 결과와 같게 맞춘다.

    2본 IK는 팔뚝·정강이의 비틀림을 폴이 정하므로 FK와 다를 수 있다. 그대로 두면 손과
    발이 자기 축을 따라 돌아간다. Blender가 실제로 푼 결과를 읽어 그 위에서 보정한다.
    같은 순회에서 IK가 목표와 무릎을 얼마나 맞혔는지도 함께 잰다.

    flatten은 {발 본: 스탠스 가중치 목록}이다. 가중치만큼 FK 방향 대신 수평 발바닥 자세
    (_flat_rotation)로 섞는다.
    """
    scene = context.scene
    rest = {bone.name: bone.matrix_local for bone in target.data.bones}
    series = {name: [] for name in deferred}
    effector = 0.0
    middle = 0.0
    up = _rotation(target.matrix_world).inverted() @ Vector((0.0, 0.0, 1.0))
    for index, frame in enumerate(frames):
        scene.frame_set(frame)
        context.view_layer.update()
        pose = poses[index]
        for name in series:
            parent = target.data.bones[name].parent
            base = target.pose.bones[parent.name].matrix @ rest[parent.name].inverted() @ rest[name]
            desired = _rotation(pose[name])
            weight = (flatten or {}).get(name, [])
            if index < len(weight) and weight[index] > 0.0:
                desired = desired.slerp(_flat_rotation(desired, _rotation(rest[name]), up), weight[index])
            quaternion = _rotation(base).inverted() @ desired
            previous = series[name]
            if previous:
                quaternion.make_compatible(previous[-1])
            previous.append(quaternion)
        for track in tracks:
            setup = track["setup"]
            tip = setup["tip"]
            offset = Vector((0.0, target.data.bones[tip].length, 0.0)) if setup["use_tail"] else Vector((0.0, 0.0, 0.0))
            solved = target.pose.bones[tip].matrix
            effector = max(effector, ((solved @ offset) - track["ends"][index]).length)
            # 앵커 체인은 끝점이 FK와 다르므로 무릎도 FK에서 벗어나는 것이 맞다.
            if not track["anchored"]:
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


def deepest_penetration(context, target, frames, floor, bones=None):
    """검증 프레임에서 바닥보다 아래로 내려간 가장 깊은 본과 깊이. bones로 대상을 좁힌다."""
    scene = context.scene
    bones = set(bones) if bones is not None else {bone.name for bone in target.pose.bones}
    worst = (0.0, "")
    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()
        basis = target.matrix_world
        for bone in target.pose.bones:
            # 바닥에 닿아야 하는 발·발끝만 본다. 손이나 IK 컨트롤·폴, 소켓이 바닥 아래여도 관통이 아니다.
            if bone.name not in bones:
                continue
            matrix = basis @ bone.matrix
            for point in (matrix.translation, matrix @ Vector((0.0, bone.bone.length, 0.0))):
                depth = floor - point.z
                if depth > worst[0]:
                    worst = (depth, bone.name)
    return worst


def verify(context, source, target, pairs, frames, facing=None, exclude=()):
    """구운 결과에서 두 리그의 본 방향 차이를 도 단위 최대값으로 돌려준다.

    모션 본의 방향이 지어낸 값이면 그 방향에 맞추지 않으므로 오차로도 세지 않는다.
    그대로 세면 손처럼 방향을 알 수 없는 본 때문에 100°가 넘는 값이 찍혀, 정작 봐야 할
    다른 본의 오차가 묻힌다. exclude(캐릭터 본 이름)도 뺀다 — 발 고정으로 발을 FK와 다른
    자리에 붙잡은 다리는 방향이 원본과 다른 것이 의도다.
    """
    facing = Quaternion() if facing is None else facing
    pairs = [item for item in pairs
             if not _invented_direction(source, source.data.bones[item[1]]) and item[2] not in exclude]
    scene = context.scene
    worst = 0.0
    for frame in frames:
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()
        source_eval = source.evaluated_get(depsgraph)
        target_eval = target.evaluated_get(depsgraph)
        for _slot, source_bone, target_bone in pairs:
            from_source = facing @ (_rotation(source_eval.matrix_world @ source_eval.pose.bones[source_bone].matrix) @ Y_AXIS)
            from_target = _rotation(target_eval.matrix_world @ target_eval.pose.bones[target_bone].matrix) @ Y_AXIS
            worst = max(worst, math.degrees(from_source.angle(from_target, 0.0)))
    return worst


def apply_motion(context, source, target, *, step=1, use_location=True, ground=True,
                 simplify=DEFAULT_SIMPLIFY, smooth=DEFAULT_SMOOTH, use_ik=False, align_facing=True,
                 facing_offset=0.0, anchor_feet=True, name="CatAni 모션"):
    """모션 리그의 동작을 캐릭터에 굽고 적용 결과 보고서를 돌려준다.

    anchor_feet가 켜져 있으면 발로 끝나는 IK 체인의 목표를 원본 발이 멈춘 구간에서 고정한다
    (_anchor_ends). 구운 키는 걷어낸 선두 보정 프레임만큼 앞으로 옮겨 원본 첫 프레임에서
    시작한다.

    facing_offset은 자동 정면 정렬 위에 사용자가 얹는 수직축 회전(도)이다. 제공처마다
    캡처 좌표계의 정면 기준이 달라 자동 정렬만으로는 90°·180° 돌아간 채 구워지는 클립이
    있어, 0/+90/-90/180을 직접 고를 수 있게 둔다.
    """
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
    corrections = _roll_corrections(source, target, pairs)
    facing, facing_angle = _facing_correction(context, source, target, pairs, frames, corrections) if align_facing else (Quaternion(), 0.0)
    # 사용자가 고른 수직축 오프셋은 자동 정렬 결과 위에 얹는다(자동 정렬을 꺼도 그대로 먹는다).
    facing_offset = float(facing_offset)
    if abs(facing_offset) > 1e-6:
        facing = Quaternion(Z_AXIS, math.radians(facing_offset)) @ facing
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
        setups = ik_setups(target) if use_ik else []
        foot_targets = {target_bone for slot, _source, target_bone in pairs if slot.startswith("foot")}
        anchored = _anchor_targets(target, setups, foot_targets) if anchor_feet else {}
        anchor_scale = target_height / source_height if source_height > 1e-5 and target_height > 1e-5 else 0.0
        (rotations, locations, hips, lift, lifted_frames, poses, anchors, ground_base, planted,
         reach_lower) = _sample(
            context, source, target, pairs, frames, corrections, translation_scale,
            ground=use_location and ground, smooth=smooth, facing=facing,
            anchor_bones=set(anchored.values()), anchor_scale=anchor_scale, target_height=target_height)
        anchored = {control: bone for control, bone in anchored.items() if bone in anchors}
        # 스탠스에서는 발바닥을 수평으로 놓고(_flat_rotation) 발 아래 본(발끝)은 레스트로 둔다.
        # 접지 보정이 꺼져 있으면 바닥 기준이 없으므로 하지 않는다.
        flatten = ({name: _planted_weights(flags) for name, flags in planted.items() if name in anchors}
                   if use_location and ground else {})
        flattened_frames = max((sum(1 for weight in weights if weight >= 1.0) for weights in flatten.values()), default=0)
        identity = Quaternion()
        for bone, series in rotations.items():
            owner = _anchor_owner(target, bone, flatten)
            if owner is None or owner == bone:
                continue
            weights = flatten[owner]
            for index in range(min(len(series), len(weights))):
                if weights[index] > 0.0:
                    series[index] = series[index].slerp(identity, weights[index])
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
        # 간소화를 끄지 않았을 때의 비교 기준. 모든 샘플 프레임에 키를 남겼을 경우의 개수다.
        dense = len(frames) * (len(pairs) * 4 + (3 if use_location and hips else 0))
        # 1단계: FK 곡선만 굽는다(IK 영향 0). 다음 단계에서 이 곡선이 실제로 만든 자세를
        # 읽어 IK 목표를 거기에 맞춘다. 그래야 곡선을 솎아내도 다리 삼각형이 닫힌다.
        written, curve_error, curve_shift, bag = _write_curves(
            target, action, frames, rotations, locations if use_location else [], hips,
            simplify=simplify, scale=target_height,
            tighten_location=IK_CURVE_TIGHTEN if setups else 1.0)
        disabled = _write_influence(bag, target, frames, ())[1]
        ik_effector = ik_middle = 0.0
        pole_fix = {}
        tracks = []
        if setups:
            # 2단계: 구워진 FK 자세 위에서 IK 목표를 잡고 곡선을 쓴다.
            live = _baked_poses(context, target, frames)
            tracks = _ik_channels(target, setups, poses, live=live, anchors=anchors, anchored=anchored)
            count, disabled, ik_shift = _write_ik_curves(bag, target, frames, tracks, simplify, target_height)
            written += count
            curve_shift = max(curve_shift, ik_shift)
            # 폴 각도의 상수 잔차를 실측해 되돌린 뒤 폴 곡선만 다시 쓴다.
            pole_fix = _pole_residuals(context, target, tracks, poses, frames)
            if any(abs(value) > math.radians(0.05) for value in pole_fix.values()):
                tracks = _ik_channels(target, setups, poses, pole_fix, live=live, anchors=anchors, anchored=anchored)
                written += _rewrite_poles(bag, target, frames, tracks, simplify, target_height)
            count, error, ik_effector, ik_middle = _bake_followers(
                context, target, bag, frames, deferred, poses, simplify, tracks, flatten)
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
        anchored_feet = set(anchored.values())
        anchored_chain = sorted({bone for setup in setups if setup["control"] in anchored for bone in setup["chain"]}
                                | {target_bone for _slot, _source, target_bone in pairs
                                   if anchored_feet and _anchor_owner(target, target_bone, anchored_feet) is not None})
        error = verify(context, source, target, pairs, samples, facing=facing, exclude=anchored_chain)
        invented = [target_bone for _slot, source_bone, target_bone in pairs
                    if _invented_direction(source, source.data.bones[source_bone])]
        floor_bones = [target_bone for slot, _source, target_bone in pairs if slot.startswith(("foot", "toe"))]
        rest_floor = _lowest_rest(target, target.matrix_world.copy(), floor_bones) if floor_bones else 0.0
        depth, deep_bone = deepest_penetration(context, target, samples, rest_floor, floor_bones)
        # 선두 보정 프레임을 걷어낸 만큼 키를 앞으로 옮겨 원본 첫 프레임에서 시작하게 한다.
        # 검증은 원본과 같은 프레임에서 재야 하므로 그 뒤에 옮긴다.
        shift = start - frames[0]
        if shift:
            _shift_keys(bag, shift)
        first, last = frames[0] + shift, frames[-1] + shift
        scene.frame_start, scene.frame_end = first, last
        scene.frame_set(first)
        succeeded = True
        return {
            "pairs": pairs, "skipped": skipped, "guessed": guessed, "keyframes": written,
            "coverage": len(pairs) / len(SLOT_ORDER),
            "frame_start": first, "frame_end": last, "frame_count": len(frames), "step": step,
            "source_profile": profile_label(source_key), "target_profile": profile_label(target_key),
            "target_bone_total": len(target.data.bones), "translation_scale": translation_scale,
            "simplify": simplify, "dense_keyframes": dense, "smooth": smooth, "dropped_frames": dropped,
            "align_facing": align_facing, "facing_angle": math.degrees(facing_angle),
            "facing_offset": facing_offset,
            "ik": [setup["control"] for setup in setups], "ik_requested": use_ik,
            "ik_effector": ik_effector, "ik_middle": ik_middle, "anchored": sorted(anchored.values()),
            "flattened_frames": flattened_frames, "reach_lower": reach_lower,
            "pole_fix": {name: math.degrees(value) for name, value in pole_fix.items()},
            "curve_error": curve_error, "curve_shift": curve_shift, "invented_bones": invented,
            "max_direction_error": error, "verified_frames": samples, "anchored_chain": anchored_chain,
            "ground_lift": lift, "ground_frames": lifted_frames, "ground_base": ground_base,
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
    if report["invented_bones"]:
        lines.append(
            "모션 본 방향 없음: " + ", ".join(report["invented_bones"])
            + " · 모션 파일이 이 관절의 길이를 담고 있지 않아 가져오기가 방향을 지어냅니다. "
            "부모 부위가 쓴 회전을 물려받아 맞추고, 방향 오차 계산에서도 제외합니다")
    if not report["align_facing"]:
        lines.append("정면 정렬: 없음 · 모션 파일이 향한 방향 그대로 굽습니다")
    elif abs(report["facing_angle"]) >= 0.05:
        lines.append(f"정면 정렬: {report['facing_angle']:+.1f}° · 모션 첫 프레임의 정면을 캐릭터 레스트 정면으로 돌렸습니다")
    else:
        lines.append("정면 정렬: 보정 불필요 · 모션이 이미 캐릭터 정면을 향합니다")
    if report.get("facing_offset"):
        lines.append(f"회전 보정: {report['facing_offset']:+.0f}° · 사용자가 고른 수직축 회전을 정면 정렬 위에 더했습니다")
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
    if report.get("anchored"):
        lines.append(f"발 고정: {', '.join(report['anchored'])} (원본 발이 멈춘 구간에서 IK 목표를 붙잡음 · "
                     f"{', '.join(report.get('anchored_chain', []))}은 방향 검증에서 제외)")
        if report.get("flattened_frames"):
            lines.append(f"발바닥 정렬: 스탠스 {report['flattened_frames']}프레임에서 발바닥을 수평으로, 발끝은 레스트로 두고 접지점을 바닥에 맞춤")
    if report.get("reach_lower", 0.0) > 1e-6:
        lines.append(f"다리 도달 보정: 땅을 딛은 발에 다리가 닿도록 엉덩이를 최대 {report['reach_lower']:.3f} 내림")
    if abs(report.get("ground_base", 0.0)) > 1e-6:
        lines.append(f"바닥 맞춤: 엉덩이 {report['ground_base']:+.3f}")
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
