"""원본을 복제하여 생성하는 Blender 동작 엔진."""

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from .core import sparse_channels

_session = None
_required = {"spine": None, "spine.001": "spine", "spine.002": "spine.001", "spine.003": "spine.002", "neck": "spine.003", "head": "neck"}
for _side in ("L", "R"):
    _required.update({f"upper_arm.{_side}": f"shoulder.{_side}", f"forearm.{_side}": f"upper_arm.{_side}", f"hand.{_side}": f"forearm.{_side}", f"IK_Arm.{_side}": None, f"IK_Target.{_side}": None})


def inspect_rig(obj):
    errors = []
    if obj is None or obj.type != "ARMATURE":
        return ["Player 샘플의 아마추어를 선택하세요."]
    if obj.library or obj.data.library:
        errors.append("링크된 리그는 지원하지 않습니다. 로컬 복사본을 사용하세요.")
    for name, parent in _required.items():
        bone = obj.data.bones.get(name)
        if bone is None:
            errors.append(f"필수 뼈 없음: {name}")
        elif parent and (bone.parent is None or bone.parent.name != parent):
            errors.append(f"뼈 계층 불일치: {name}")
    if not errors:
        for side, sign in (("L", 1), ("R", -1)):
            arm = obj.data.bones[f"upper_arm.{side}"]
            direction = (arm.tail_local - arm.head_local).normalized()
            if direction.z > -0.6 or direction.x * sign < 0.2:
                errors.append("Player v1의 Z축 위쪽, 아래로 내려간 팔 레스트 포즈만 지원합니다.")
                break
    if obj.animation_data and obj.animation_data.drivers:
        errors.append("드라이버가 있는 리그는 첫 버전에서 지원하지 않습니다.")
    return errors


def get_session():
    return _session


def _write_curve(channelbag, path, component, knots, spec, group):
    curve = channelbag.fcurves.new(data_path=path, index=component, group_name=group)
    curve.keyframe_points.add(len(knots))
    for index, (phase, value, slope_left, slope_right) in enumerate(knots):
        key = curve.keyframe_points[index]
        frame = spec.start_frame + phase * spec.frame_count
        left_span = phase - knots[index - 1][0] if index else knots[1][0] - phase
        right_span = knots[index + 1][0] - phase if index < len(knots) - 1 else phase - knots[index - 1][0]
        key.co = (frame, value)
        key.interpolation = "BEZIER"
        key.handle_left_type = "FREE"
        key.handle_right_type = "FREE"
        key.handle_left = (frame - left_span * spec.frame_count / 3.0, value - slope_left * left_span / 3.0)
        key.handle_right = (frame + right_span * spec.frame_count / 3.0, value + slope_right * right_span / 3.0)
    curve.update()
    return curve


def _create_sparse_curves(rig, action, spec):
    """각도 채널 하나와 고정 회전 축으로 편집 가능한 베지어 곡선을 만든다."""
    slot = action.slots.new(id_type="OBJECT", name=rig.name)
    layer = action.layers.new("CatAni 동작")
    strip = layer.strips.new(type="KEYFRAME")
    channelbag = strip.channelbag(slot, ensure=True)
    rig.animation_data.action_slot = slot
    for name, channel in sparse_channels(spec).items():
        bone = rig.pose.bones[name]
        bone.rotation_mode = "AXIS_ANGLE"
        axis = bone.bone.matrix_local.to_quaternion().inverted() @ Vector(channel["axis"])
        bone.rotation_axis_angle = (0.0, *axis)
        path = bone.path_from_id("rotation_axis_angle")
        _write_curve(channelbag, path, 0, channel["knots"], spec, name)
        for index, value in enumerate(axis, start=1):
            fixed = channelbag.fcurves.new(data_path=path, index=index, group_name=name)
            key = fixed.keyframe_points.insert(spec.start_frame, value)
            key.interpolation = "CONSTANT"
            fixed.lock = True


def _related(obj, source, known):
    return obj.parent in known or any(getattr(m, "object", None) == source for m in obj.modifiers) or any(getattr(c, "target", None) == source for c in obj.constraints)


def _restore_context(context, session):
    scene = session["scene"]
    view_layer = session["view_layer"]
    scene.frame_start, scene.frame_end = session["frame_start"], session["frame_end"]
    scene.frame_set(session["frame"], subframe=session["subframe"])
    for obj, hidden in session["hidden"]:
        if obj.name in scene.objects:
            obj.hide_set(hidden, view_layer=view_layer)
    for obj, hidden in session["render_hidden"]:
        if obj.name in scene.objects:
            obj.hide_render = hidden
    for obj in view_layer.objects:
        if obj.select_get(view_layer=view_layer):
            obj.select_set(False, view_layer=view_layer)
    for obj in session["selected"]:
        if obj.name in view_layer.objects:
            obj.select_set(True, view_layer=view_layer)
    if session["active"] and session["active"].name in view_layer.objects:
        view_layer.objects.active = session["active"]


def cancel_preview(context):
    global _session
    session = _session
    if session is None:
        return
    _session = None
    for obj in session["copies"]:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
    if session["collection"].name in bpy.data.collections:
        bpy.data.collections.remove(session["collection"])
    action = session.get("action")
    if action and action.users == 0:
        bpy.data.actions.remove(action)
    _restore_context(context, session)


def begin_preview(context, source, spec):
    global _session
    if _session is not None:
        raise ValueError("현재 미리보기를 확정하거나 취소하세요.")
    if context.mode != "OBJECT":
        raise ValueError("오브젝트 모드에서 실행하세요.")
    errors = inspect_rig(source)
    if errors:
        raise ValueError(" / ".join(errors))
    scene = context.scene
    collection = bpy.data.collections.new("CatAni 미리보기")
    scene.collection.children.link(collection)
    session = {"source": source, "collection": collection, "copies": [], "hidden": [], "render_hidden": [], "frame": scene.frame_current, "subframe": scene.frame_subframe, "frame_start": scene.frame_start, "frame_end": scene.frame_end, "selected": list(context.selected_objects), "active": context.view_layer.objects.active, "action": None}
    session["scene"] = scene
    session["view_layer"] = context.view_layer
    _session = session
    try:
        sources = {source}
        for _ in range(len(scene.objects)):
            added = {obj for obj in scene.objects if obj not in sources and _related(obj, source, sources)}
            if not added:
                break
            sources.update(added)
        mapping = {}
        clone_sources = {source}
        for _ in range(len(sources)):
            added = {obj for obj in sources if obj not in clone_sources and (obj.parent in clone_sources or any(getattr(m, "object", None) == source for m in obj.modifiers))}
            if not added:
                break
            clone_sources.update(added)
        for original in sorted(sources, key=lambda obj: obj.name):
            session["hidden"].append((original, original.hide_get()))
            session["render_hidden"].append((original, original.hide_render))
            original.hide_set(True)
            original.hide_render = True
            if original not in clone_sources:
                continue
            clone = original.copy()
            if original == source or original.type == "MESH":
                clone.data = original.data.copy()
            collection.objects.link(clone)
            session["copies"].append(clone)
            mapping[original] = clone
            clone.hide_set(False)
            clone.hide_viewport = False
            clone.hide_render = False
        rig = mapping[source]
        session["rig"] = rig
        rig.name = f"CatAni_{spec.recipe}"
        for original, clone in mapping.items():
            if original.parent in mapping:
                clone.parent = mapping[original.parent]
            for modifier in clone.modifiers:
                if hasattr(modifier, "object") and modifier.object in mapping:
                    modifier.object = mapping[modifier.object]
            for constraint in clone.constraints:
                if hasattr(constraint, "target") and constraint.target in mapping:
                    constraint.target = mapping[constraint.target]
        rig.animation_data_clear()
        rig.animation_data_create()
        rig.data.pose_position = "POSE"
        action = bpy.data.actions.new(f"CatAni_{spec.recipe}_{spec.side}")
        session["action"] = action
        action["catani_motion_spec"] = spec.to_json()
        action["catani_source"] = source.name
        rig.animation_data.action = action
        _create_sparse_curves(rig, action, spec)
        animated_bones = set(sparse_channels(spec))
        for bone in rig.pose.bones:
            bone.location = (0, 0, 0)
            if bone.name not in animated_bones:
                bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.scale = (1, 1, 1)
            for constraint in bone.constraints:
                for attr in ("target", "pole_target"):
                    if hasattr(constraint, attr) and getattr(constraint, attr) in mapping:
                        setattr(constraint, attr, mapping[getattr(constraint, attr)])
                if constraint.type == "IK":
                    constraint.influence = 0
                    constraint.keyframe_insert(data_path="influence", frame=spec.start_frame)
        for obj in context.selected_objects:
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        scene.frame_start, scene.frame_end = spec.start_frame, spec.end_frame
        scene.frame_set(spec.start_frame)
        context.view_layer.update()
        return session
    except Exception:
        cancel_preview(context)
        raise


def confirm_preview(context):
    global _session
    if _session is None:
        raise ValueError("확정할 미리보기가 없습니다.")
    session = _session
    session["action"].use_fake_user = True
    session["collection"].name = "CatAni 생성 결과"
    session["rig"]["catani_source"] = session["source"].name
    _session = None
    return session["action"]


@persistent
def clear_before_load(_):
    global _session
    _session = None


@persistent
def cancel_before_save(_):
    if _session is not None:
        cancel_preview(bpy.context)
