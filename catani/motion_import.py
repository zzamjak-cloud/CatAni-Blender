"""원본 장면을 보존하며 별도 컬렉션에 모션 리그를 가져온다."""

from pathlib import Path

import bpy


_DATA_COLLECTIONS = ("objects", "collections", "meshes", "armatures", "actions", "materials", "images", "cameras", "lights", "curves", "shape_keys", "textures", "node_groups")


def _data_snapshot():
    return {name: set(getattr(bpy.data, name)) for name in _DATA_COLLECTIONS}


def _find_layer(layer, collection):
    if layer.collection == collection:
        return layer
    for child in layer.children:
        found = _find_layer(child, collection)
        if found is not None:
            return found
    return None


def _has_animation(obj):
    animation = obj.animation_data
    if animation is None:
        return False
    actions = {animation.action} if animation.action else set()
    for track in animation.nla_tracks:
        actions.update(strip.action for strip in track.strips if strip.action)
    return any(len(curve.keyframe_points) for action in actions for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves)


def import_asset(context, asset):
    """성공 시 (생성 오브젝트, 컬렉션)을 반환하고 실패 시 생성 데이터 전체를 정리한다."""
    if context.mode != "OBJECT":
        raise ValueError("모션 가져오기는 오브젝트 모드에서 실행하세요.")
    path = Path(bpy.path.abspath(asset.path)).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"모션 파일을 찾을 수 없습니다: {path}")
    if asset.file_type not in {"bvh", "fbx"} or path.suffix.lower() != "." + asset.file_type:
        raise ValueError("지원 모션 형식과 실제 파일 확장자가 일치하지 않습니다.")
    operator = bpy.ops.import_anim.bvh if asset.file_type == "bvh" else bpy.ops.import_scene.fbx
    try:
        operator.get_rna_type()
    except (AttributeError, RuntimeError):
        raise ValueError(f"Blender의 {asset.file_type.upper()} 가져오기 기능을 사용할 수 없습니다.") from None
    scene = context.scene
    layer = context.view_layer
    state = {
        "frame_start": scene.frame_start, "frame_end": scene.frame_end,
        "frame": scene.frame_current, "subframe": scene.frame_subframe,
        "fps": scene.render.fps, "fps_base": scene.render.fps_base,
        "preview_start": scene.frame_preview_start, "preview_end": scene.frame_preview_end,
        "use_preview": scene.use_preview_range,
        "selected": list(context.selected_objects), "active": layer.objects.active,
        "active_collection": layer.active_layer_collection,
    }
    before = _data_snapshot()
    succeeded = False
    try:
        collection = bpy.data.collections.new(f"CatAni 모션 원본 · {asset.name[:28]}")
        scene.collection.children.link(collection)
        layer.update()
        layer.active_layer_collection = _find_layer(layer.layer_collection, collection)
        if asset.file_type == "bvh":
            result = operator(filepath=str(path), target="ARMATURE", frame_start=1, use_fps_scale=True, update_scene_fps=False, update_scene_duration=False)
        else:
            result = operator(filepath=str(path), use_anim=True, use_image_search=False)
        if "FINISHED" not in result:
            raise ValueError("Blender가 모션 가져오기를 완료하지 못했습니다.")
        created = sorted(set(bpy.data.objects) - before["objects"], key=lambda obj: obj.name)
        armatures = [obj for obj in created if obj.type == "ARMATURE"]
        if not any(_has_animation(obj) for obj in armatures):
            raise ValueError("파일에 애니메이션이 있는 아마추어를 찾지 못했습니다.")
        for obj in created:
            if collection not in obj.users_collection:
                collection.objects.link(obj)
            for linked in tuple(obj.users_collection):
                if linked != collection:
                    linked.objects.unlink(obj)
            obj["catani_motion_source"] = str(path)
            obj["catani_motion_tags"] = ", ".join(asset.tags)
            for field in ("source_name", "source_url", "license_note", "license_url"):
                obj[f"catani_motion_{field}"] = getattr(asset, field, "")
        collection["catani_motion_id"] = asset.identifier
        collection["catani_motion_source"] = str(path)
        # 가져오기 도중 만들어진 빈 임시 컬렉션만 제거한다.
        for _ in range(len(bpy.data.collections)):
            empty = [item for item in bpy.data.collections if item not in before["collections"] and item != collection and not item.objects and not item.children]
            if not empty:
                break
            for item in empty:
                bpy.data.collections.remove(item)
        for obj in context.selected_objects:
            obj.select_set(False)
        armatures[0].select_set(True)
        layer.objects.active = armatures[0]
        succeeded = True
        return created, collection
    finally:
        if not succeeded:
            if context.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="OBJECT")
            created_data = [item for name, previous in before.items() for item in getattr(bpy.data, name) if item not in previous]
            if created_data:
                bpy.data.batch_remove(ids=created_data)
        scene.frame_start, scene.frame_end = state["frame_start"], state["frame_end"]
        scene.frame_preview_start, scene.frame_preview_end = state["preview_start"], state["preview_end"]
        scene.use_preview_range = state["use_preview"]
        scene.render.fps, scene.render.fps_base = state["fps"], state["fps_base"]
        scene.frame_set(state["frame"], subframe=state["subframe"])
        layer.active_layer_collection = state["active_collection"]
        if not succeeded:
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in state["selected"]:
                if obj.name in layer.objects:
                    obj.select_set(True)
            layer.objects.active = state["active"]
