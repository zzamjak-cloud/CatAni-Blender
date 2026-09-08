"""팔 IK의 실제 작동과 인사 구간의 얼굴 앞쪽 손 경로를 검사한다."""
import json
import math
from pathlib import Path
import bpy
from mathutils import Vector
from bl_ext.user_default.catani import core, engine
from bl_ext.user_default.catani.agent_plan import DEFAULT_PLAN

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
scene = bpy.context.scene
source = bpy.data.objects["Amature_Player"]
mesh = bpy.data.objects["Player_Base"]
group = mesh.vertex_groups["head"]
head_rest = source.data.bones["head"].matrix_local
forward = (head_rest.to_3x3().inverted() @ Vector((0, -1, 0))).normalized()
points = [head_rest.inverted() @ source.matrix_world.inverted() @ mesh.matrix_world @ v.co
          for v in mesh.data.vertices if any(g.group == group.index and g.weight > 0.5 for g in v.groups)]
face_depth = max(p.dot(forward) for p in points)
plans = [dict(DEFAULT_PLAN, side=side) for side in ["R", "L"]]
plans += [dict(DEFAULT_PLAN, torso_turn=-12, head_turn=-15, torso_lean=8, arm_lift=125),
          dict(DEFAULT_PLAN, torso_turn=12, head_turn=15, wrist_swing=22, arm_lift=90)]
for plan in plans:
    spec = core.MotionSpec(recipe="natural_wave", plan=plan, fps=60)
    session = engine.begin_preview(bpy.context, source, spec)
    rig = session["rig"]
    curves = [c for l in session["action"].layers for s in l.strips for b in s.channelbags for c in b.fcurves]
    for side in ["L", "R"]:
        assert any(f'pose.bones["IK_Arm.{side}"].location' == c.data_path for c in curves)
        for bone in [f"upper_arm.{side}", f"forearm.{side}"]:
            assert not any(f'pose.bones["{bone}"].rotation' in c.data_path for c in curves)
    minimum_clearance = float("inf")
    max_tracking = 0.0
    previous_elbow = None
    max_elbow_step = 0.0
    start = plan["anticipation"] + 0.16
    end = 1.0 - plan["settle"]
    for index in range(161):
        phase = start + (end-start)*index/160
        frame = spec.start_frame + phase*spec.frame_count
        scene.frame_set(math.floor(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        hand = rig.pose.bones[f'hand.{plan["side"]}']
        elbow = rig.pose.bones[f'forearm.{plan["side"]}'].head.copy()
        if previous_elbow is not None:
            max_elbow_step = max(max_elbow_step, (elbow-previous_elbow).length)
        previous_elbow = elbow
        head_inverse = rig.pose.bones["head"].matrix.inverted()
        clearance = min((head_inverse @ p).dot(forward)-face_depth for p in [hand.head, hand.tail])
        minimum_clearance = min(minimum_clearance, clearance)
        for side in ["L", "R"]:
            forearm = rig.pose.bones[f"forearm.{side}"]
            constraint = next(c for c in forearm.constraints if c.type == "IK")
            assert constraint.influence == 1 and not constraint.mute and not constraint.use_stretch
            assert constraint.target == rig and constraint.subtarget == f"IK_Arm.{side}"
            assert constraint.pole_target is not None
            wrist = rig.pose.bones[f"hand.{side}"].head
            target = rig.pose.bones[f"IK_Arm.{side}"].head
            max_tracking = max(max_tracking, (wrist-target).length)
    assert minimum_clearance > 0.01, (plan, "얼굴 앞 여유", minimum_clearance)
    assert max_tracking < 0.002, (plan, "손목 IK 추종", max_tracking)
    assert max_elbow_step < 0.025, (plan, "팔꿈치 튐", max_elbow_step)
    side = plan["side"]
    rig.animation_data.action = None
    controller = rig.pose.bones[f"IK_Arm.{side}"]
    before = rig.pose.bones[f"hand.{side}"].head.copy()
    controller.location += controller.bone.matrix_local.to_3x3().inverted() @ Vector((0, -0.01, 0))
    bpy.context.view_layer.update()
    movement = (rig.pose.bones[f"hand.{side}"].head-before).length
    assert movement > 0.007, ("IK 컨트롤러에 손이 반응하지 않음", movement)
    print("CATANI_ARM_IK", json.dumps({"side":side,"torso_turn":plan["torso_turn"],
          "head_turn":plan["head_turn"],"face_clearance":minimum_clearance,
          "tracking_error":max_tracking,"controller_response":movement}))
    engine.cancel_preview(bpy.context)
