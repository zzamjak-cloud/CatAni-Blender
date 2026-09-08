"""저장된 화면 구성을 제외한 실제 GUI 재생·패널 검증."""
from pathlib import Path
import json
import os
import bpy
from mathutils import Quaternion, Vector

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "artifacts" / os.environ.get("CATANI_DEMO_NAME", "CatAni_Wave_Demo.blend")), load_ui=False)
state = {"frame": 1}


def play_frames():
    scene = bpy.context.window_manager.windows[0].scene
    scene.frame_set(state["frame"])
    state["frame"] += 3
    if state["frame"] <= scene.frame_end:
        return 0.05
    scene.frame_set(70)
    print("CATANI_PASS 실제 GUI 프레임 재생 완료", flush=True)
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=4.0)
    return None


def setup_view():
    window = bpy.context.window_manager.windows[0]
    scene = window.scene
    rig = bpy.data.objects[json.loads(scene["catani_verification"])["rig"]]
    for obj in window.view_layer.objects:
        obj.select_set(False)
    rig.select_set(True)
    window.view_layer.objects.active = rig
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.show_region_ui = True
            space.overlay.show_overlays = False
            space.region_3d.view_rotation = Quaternion((0.70710678, 0.70710678, 0, 0))
            space.region_3d.view_distance = 4.0
            space.region_3d.view_location = Vector((0, 0, 1))
            space.region_3d.view_perspective = "ORTHO"
            with bpy.context.temp_override(window=window, area=area,
                                            region=next(r for r in area.regions if r.type == "WINDOW")):
                bpy.ops.wm.call_panel(name="CATANI_PT_main", keep_open=True)
            print("CATANI_PASS 실제 GUI CatAni 패널 호출", flush=True)
    bpy.app.timers.register(play_frames, first_interval=0.2)
    return None


bpy.app.timers.register(setup_view, first_interval=1.0)
