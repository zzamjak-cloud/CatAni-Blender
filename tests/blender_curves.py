"""희소 Bézier 곡선의 키 수와 기존 모션 대비 포즈 오차를 검사한다."""
import json
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector
from bl_ext.user_default.catani import core, engine

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
source = bpy.data.objects["Amature_Player"]
scene = bpy.context.scene
counts = {}
reports = []


def set_progress(spec, t):
    frame = spec.start_frame + t * spec.frame_count
    scene.frame_set(math.floor(frame), subframe=frame % 1)
    bpy.context.view_layer.update()


cases = [
    ("idle", "R", 2, 0.7, 60),
    ("wave", "R", 2, 0.8, 60),
    ("wave", "R", 2, 0.8, 24),
    ("wave", "L", 2, 0.8, 60),
    ("wave", "R", 8, 1.0, 60),
    ("idle", "R", 8, 1.0, 60),
]
for recipe, side, repeat, intensity, fps in cases:
    spec = core.MotionSpec(recipe=recipe, side=side, repeat=repeat,
                           intensity=intensity, duration=3.0, fps=fps)
    session = engine.begin_preview(bpy.context, source, spec)
    rig, action = session["rig"], session["action"]
    curves = [c for layer in action.layers for strip in layer.strips
              for bag in strip.channelbags for c in bag.fcurves]
    key_count = sum(len(c.keyframe_points) for c in curves)
    angle_curves = [c for c in curves if c.data_path.endswith("rotation_axis_angle") and c.array_index == 0]
    assert len(angle_curves) == (2 if recipe == "idle" else 5)
    assert not any(c.data_path.endswith(("location", "scale", "rotation_quaternion")) for c in curves)
    assert all(k.interpolation == "BEZIER" for c in angle_curves for k in c.keyframe_points)
    assert all(k.handle_left_type == "FREE" and k.handle_right_type == "FREE"
               for c in angle_curves for k in c.keyframe_points)
    assert key_count < 200, key_count
    if recipe == "wave":
        upper = next(c for c in angle_curves if "upper_arm" in c.data_path)
        assert len(upper.keyframe_points) == 4
    key = (recipe, side, repeat, intensity)
    if key in counts:
        assert counts[key] == key_count, "FPS 변경으로 키 수가 달라짐"
    counts[key] = key_count
    progress = sorted(set([i / 256 for i in range(257)] + [0.22, 0.78]))
    expected = []
    for t in progress:
        set_progress(spec, t)
        expected.append({p.name: p.matrix.copy() for p in rig.pose.bones})
    rig.animation_data.action = None
    max_angle = max_position = 0.0
    for t, poses in zip(progress, expected):
        set_progress(spec, t)
        for name, values in core.sample_motion(spec, t).items():
            bone = rig.pose.bones[name]
            vector = Vector(values)
            rotation = Quaternion(vector.normalized(), vector.length) if vector.length else Quaternion()
            rest = bone.bone.matrix_local.to_quaternion()
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = rest.inverted() @ rotation @ rest
        bpy.context.view_layer.update()
        for name, actual in poses.items():
            reference = rig.pose.bones[name].matrix
            difference = actual.to_quaternion().rotation_difference(reference.to_quaternion()).angle
            max_angle = max(max_angle, min(difference, math.tau - difference))
            max_position = max(max_position, (actual.translation - reference.translation).length)
    assert math.degrees(max_angle) < 0.4, math.degrees(max_angle)
    assert max_position < 0.004, max_position
    reports.append({"motion": recipe, "side": side, "repeat": repeat, "fps": fps,
                    "curves": len(curves), "keys": key_count,
                    "max_angle_degrees": round(math.degrees(max_angle), 6),
                    "max_position": round(max_position, 6)})
    engine.cancel_preview(bpy.context)
print("CATANI_CURVES", json.dumps(reports, ensure_ascii=False))
