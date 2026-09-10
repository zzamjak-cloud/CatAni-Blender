"""저장된 결과의 고정 시점 검토 이미지를 만든다."""
import json
import os
from pathlib import Path
import bpy
from mathutils import Vector

root = Path(__file__).resolve().parents[1]
demo_name = os.environ.get("CATANI_DEMO_NAME", "CatAni_Motion_Demo.blend")
bpy.ops.wm.open_mainfile(filepath=str(root / "artifacts" / demo_name))
scene = bpy.context.scene
result = bpy.data.objects[json.loads(scene["catani_verification"])["rig"]]
result_objects = set(o for collection in result.users_collection for o in collection.objects)
for obj in scene.objects:
    obj.hide_render = obj not in result_objects or obj.type != "MESH"
camera_data = bpy.data.cameras.new("CatAni_Review")
camera = bpy.data.objects.new("CatAni_Review_Camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.type = "ORTHO"
camera_data.ortho_scale = 2.7
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.background_type = "WORLD"
scene.world.color = (0.13, 0.13, 0.13)
scene.render.resolution_x = 640
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
for view, position in [("front", (0, -6, 1.2)), ("side", (6, -0.4, 1.2))]:
    camera.location = Vector(position) + result.location
    target = Vector((0, 0, 1.0)) + result.location
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    for frame in [round(scene.frame_start + t*(scene.frame_end-scene.frame_start)) for t in [0, 0.15, 0.35, 0.55, 0.8, 1]]:
        scene.frame_set(frame)
        prefix = "natural" if "Natural" in demo_name else "wave"
        scene.render.filepath = str(root / f"artifacts/{prefix}_{view}_{frame:03d}.png")
        bpy.ops.render.render(write_still=True)
print("CATANI_PASS 검토 이미지 12개 생성")
