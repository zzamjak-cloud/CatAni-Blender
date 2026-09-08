"""전신 인사의 접촉·몸통 움직임·희소 곡선·원본 복원을 검사한다."""
import json
import math
from pathlib import Path

import bpy
from bl_ext.user_default.catani import core, engine
from bl_ext.user_default.catani.agent_plan import DEFAULT_PLAN

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
scene = bpy.context.scene
source = bpy.data.objects["Amature_Player"]
original_objects = set(bpy.data.objects)
original_action = source.animation_data.action
visibility = {o.name: (o.hide_get(), o.hide_render) for o in original_objects}
key_counts = []

plan_path = root / "artifacts/Agent_Natural_Wave_Plan.json"
live_plan = json.loads(plan_path.read_text()) if plan_path.exists() else dict(DEFAULT_PLAN)
maximum = dict(DEFAULT_PLAN, weight_shift=0.025, torso_turn=12, torso_lean=8,
               head_turn=15, arm_lift=125, wrist_swing=22, anticipation=0.12, settle=0.12, repeat=4)
cases = [("R", 60, DEFAULT_PLAN), ("L", 60, DEFAULT_PLAN), ("R", 24, DEFAULT_PLAN),
         (live_plan["side"], 60, live_plan), ("R", 60, maximum)]
for side, fps, base_plan in cases:
    plan = dict(base_plan, side=side)
    spec = core.MotionSpec(recipe="natural_wave", fps=fps, plan=plan)
    session = engine.begin_preview(bpy.context, source, spec)
    rig = session["rig"]
    action = session["action"]
    curves = [c for l in action.layers for s in l.strips for b in s.channelbags for c in b.fcurves]
    count = sum(len(c.keyframe_points) for c in curves)
    assert count < 300, count
    key_counts.append(count)
    initial_feet = None
    max_drift = 0.0
    hips = []
    torso = []
    for index in range(301):
        frame = spec.start_frame + spec.frame_count * index / 300
        scene.frame_set(math.floor(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        feet = [v.copy() for side_name in ("L", "R")
                for v in (rig.pose.bones[f"foot.{side_name}"].head,
                          rig.pose.bones[f"foot.{side_name}"].tail,
                          rig.pose.bones[f"toe.{side_name}"].tail)]
        if initial_feet is None:
            initial_feet = feet
        max_drift = max(max_drift, max((a-b).length for a,b in zip(feet, initial_feet)))
        hips.append(rig.pose.bones["spine"].head.copy())
        torso.append(rig.pose.bones["spine.003"].matrix.to_quaternion())
        assert all(math.isfinite(v) for p in rig.pose.bones for row in p.matrix for v in row)
    shift = max(p.x for p in hips) - min(p.x for p in hips)
    turn = max(min(q.rotation_difference(torso[0]).angle,
                   math.tau-q.rotation_difference(torso[0]).angle) for q in torso)
    assert max_drift < 0.002, (side, "발 접촉", max_drift)
    assert shift > 0.01, ("체중 이동 없음", shift)
    assert turn > 0.02, ("몸통 움직임 없음", turn)
    assert (hips[0]-hips[-1]).length < 1e-5
    print("CATANI_NATURAL", json.dumps({"side":side,"fps":fps,"keys":count,
          "max_foot_drift":max_drift,"pelvis_shift":shift,"torso_degrees":math.degrees(turn)}))
    engine.cancel_preview(bpy.context)
    assert set(bpy.data.objects) == original_objects
    assert source.animation_data.action == original_action
    assert {o.name:(o.hide_get(),o.hide_render) for o in original_objects} == visibility
assert len(set(key_counts[:3])) == 1, key_counts

plan_path = root / "artifacts/Agent_Natural_Wave_Plan.json"
plan = json.loads(plan_path.read_text()) if plan_path.exists() else dict(DEFAULT_PLAN)
spec = core.MotionSpec(recipe="natural_wave", fps=60, plan=plan)
session = engine.begin_preview(bpy.context, source, spec)
rig = session["rig"]
engine.confirm_preview(bpy.context)
poses = {}
for phase in [0, 0.15, 0.4, 0.6, 0.85, 1]:
    frame = round(spec.start_frame + phase*spec.frame_count)
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    poses[str(frame)] = {p.name:[v for row in p.matrix for v in row] for p in rig.pose.bones}
scene["catani_verification"] = json.dumps({"rig":rig.name,"poses":poses})
scene.frame_set(round(spec.frame_count*0.45))
bpy.ops.wm.save_as_mainfile(filepath=str(root / "artifacts/CatAni_Natural_Wave_Demo.blend"))
print("CATANI_PASS 전신 인사 예제 저장")
