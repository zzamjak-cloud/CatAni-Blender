"""양팔의 평가된 IK·폴 반응·굴곡 평면·레스트 롤과 손 경로를 검사한다."""
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector
from bl_ext.user_default.catani import core, engine
from bl_ext.user_default.catani.agent_plan import DEFAULT_PLAN


def evaluated_arm(rig, side):
    """IK가 갱신하지 않는 FK 채널 대신 의존 그래프의 최종 행렬을 읽는다."""
    bpy.context.view_layer.update()
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    upper = evaluated.pose.bones[f"upper_arm.{side}"]
    forearm = evaluated.pose.bones[f"forearm.{side}"]
    return {
        "shoulder": upper.head.copy(), "elbow": forearm.head.copy(),
        "wrist": evaluated.pose.bones[f"hand.{side}"].head.copy(),
        "target": evaluated.pose.bones[f"IK_Arm.{side}"].head.copy(),
        "upper_matrix": upper.matrix.copy(), "forearm_matrix": forearm.matrix.copy(),
    }


def projected_bend(arm):
    axis = (arm["wrist"] - arm["shoulder"]).normalized()
    elbow = arm["elbow"] - arm["shoulder"]
    return axis, elbow - axis * elbow.dot(axis)


def neutral_roll_alignment(rig, side, arm):
    """최소 방향 회전과 비교해 같은 관절 위치의 180도 롤도 검출한다."""
    alignment = 1.0
    for name, key in ((f"upper_arm.{side}", "upper_matrix"), (f"forearm.{side}", "forearm_matrix")):
        rest = rig.data.bones[name].matrix_local.to_3x3()
        posed = arm[key].to_3x3()
        rest_axis = (rest @ Vector((0, 1, 0))).normalized()
        posed_axis = (posed @ Vector((0, 1, 0))).normalized()
        swing = rest_axis.rotation_difference(posed_axis)
        expected = (swing @ (rest @ Vector((1, 0, 0)))).normalized()
        actual = (posed @ Vector((1, 0, 0))).normalized()
        alignment = min(alignment, expected.dot(actual))
    return alignment


def check_subframe_continuity(rig, spec, side, phase, coarse_distance, coarse_angle):
    """빠른 연속 이동과 폴 불연속을 구분하도록 같은 구간을 네 배 촘촘히 평가한다."""
    previous = None
    max_distance = 0.0
    max_angle = 0.0
    for index in range(5):
        sample = phase - (1 - index / 4) / 300
        frame = spec.start_frame + sample * spec.frame_count
        bpy.context.scene.frame_set(math.floor(frame), subframe=frame % 1)
        arm = evaluated_arm(rig, side)
        if previous is not None:
            max_distance = max(max_distance, (arm["elbow"] - previous["elbow"]).length)
            angle = arm["upper_matrix"].to_quaternion().rotation_difference(previous["upper_matrix"].to_quaternion()).angle
            max_angle = max(max_angle, min(angle, math.tau - angle))
        previous = arm
    assert max_distance < max(coarse_distance * 0.4, 0.004), (
        "팔꿈치 불연속이 세분화 후에도 남습니다", side, phase, coarse_distance, max_distance)
    assert max_angle < max(coarse_angle * 0.4, math.radians(1)), (
        "팔 굴곡 평면·롤 불연속이 세분화 후에도 남습니다", side, phase, coarse_angle, max_angle)


def check_pole_response(rig, side):
    """기존 팔 폴을 양방향으로 움직여 손목 고정과 팔꿈치·상완 반응을 확인한다."""
    forearm = rig.pose.bones[f"forearm.{side}"]
    constraint = next(c for c in forearm.constraints if c.type == "IK")
    pole_name = f"IK_Pole_Arm.{side}"
    assert constraint.pole_target == rig and constraint.pole_subtarget == pole_name, (
        "기존 팔 폴 연결이 끊겼습니다", side, constraint.pole_subtarget)
    pole = rig.pose.bones[pole_name]
    original_matrix = pole.matrix.copy()
    before = evaluated_arm(rig, side)
    axis, bend = projected_bend(before)
    tangent = axis.cross(bend).normalized()
    assert tangent.length > 0.9, ("폴 반응 검사에 필요한 팔 굴곡이 없습니다", side)
    length = rig.data.bones[f"upper_arm.{side}"].length + rig.data.bones[f"forearm.{side}"].length
    minimum_response = float("inf")
    for sign in (-1, 1):
        moved = original_matrix.copy()
        moved.translation += tangent * length * 0.4 * sign
        pole.matrix = moved
        rig.update_tag(refresh={"OBJECT"})
        after = evaluated_arm(rig, side)
        response = (after["elbow"] - before["elbow"]).length
        matrix_response = max(abs(a - b) for row_a, row_b in zip(after["upper_matrix"], before["upper_matrix"])
                              for a, b in zip(row_a, row_b))
        assert response > 0.01 and matrix_response > 0.02, (
            "폴 이동에 평가된 팔꿈치·상완이 반응하지 않습니다", side, sign, response, matrix_response)
        assert (after["target"] - before["target"]).length < 1e-5, ("폴 이동이 손목 목표를 옮겼습니다", side)
        assert (after["wrist"] - after["target"]).length < 0.002, ("폴 편집 후 손목이 목표를 놓쳤습니다", side)
        minimum_response = min(minimum_response, response)
        pole.matrix = original_matrix
        rig.update_tag(refresh={"OBJECT"})
        evaluated_arm(rig, side)
    return minimum_response


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
scene = bpy.context.scene
source = bpy.data.objects["Amature_Player"]
for side in ("L", "R"):
    original_ik = next(c for c in source.pose.bones[f"forearm.{side}"].constraints if c.type == "IK")
    assert original_ik.pole_subtarget == f"IK_Pole_Arm.{side}"
mesh = bpy.data.objects["Player_Base"]
group = mesh.vertex_groups["head"]
head_rest = source.data.bones["head"].matrix_local
forward = (head_rest.to_3x3().inverted() @ Vector((0, -1, 0))).normalized()
points = [head_rest.inverted() @ source.matrix_world.inverted() @ mesh.matrix_world @ vertex.co
          for vertex in mesh.data.vertices if any(g.group == group.index and g.weight > 0.5 for g in vertex.groups)]
face_depth = max(point.dot(forward) for point in points)
plans = []
for side in ("R", "L"):
    plans.extend((dict(DEFAULT_PLAN, side=side),
                  dict(DEFAULT_PLAN, side=side, torso_turn=-12, head_turn=-15, torso_lean=8, arm_lift=125, repeat=4),
                  dict(DEFAULT_PLAN, side=side, torso_turn=12, head_turn=15, wrist_swing=22, arm_lift=90)))
for plan in plans:
    spec = core.MotionSpec(recipe="natural_wave", plan=plan, fps=60)
    session = engine.begin_preview(bpy.context, source, spec)
    rig = session["rig"]
    curves = [curve for layer in session["action"].layers for strip in layer.strips
              for bag in strip.channelbags for curve in bag.fcurves]
    key_count = sum(len(curve.keyframe_points) for curve in curves)
    assert key_count < 300, ("팔 수정이 매 프레임 베이크로 퇴행했습니다", key_count)
    for side in ("L", "R"):
        assert any(f'pose.bones["IK_Arm.{side}"].location' == curve.data_path for curve in curves)
        for name in (f"upper_arm.{side}", f"forearm.{side}"):
            assert not any(f'pose.bones["{name}"].rotation' in curve.data_path for curve in curves)
    minimum_clearance = float("inf")
    minimum_bend_alignment = 1.0
    minimum_roll = 1.0
    max_tracking = 0.0
    previous_arms = {}
    max_elbow_step = 0.0
    max_elbow_step_at = None
    max_hold_step = 0.0
    convergence_checks = []
    raised = plan["anticipation"] + 0.16
    release = 1.0 - plan["settle"]
    torso_rest = rig.data.bones["spine.003"].matrix_local.to_quaternion()
    for index in range(301):
        phase = index / 300
        frame = spec.start_frame + phase * spec.frame_count
        scene.frame_set(math.floor(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        if raised <= phase <= release:
            hand = evaluated.pose.bones[f'hand.{plan["side"]}']
            head_inverse = evaluated.pose.bones["head"].matrix.inverted()
            clearance = min((head_inverse @ point).dot(forward) - face_depth for point in (hand.head, hand.tail))
            minimum_clearance = min(minimum_clearance, clearance)
        torso_rotation = evaluated.pose.bones["spine.003"].matrix.to_quaternion() @ torso_rest.inverted()
        for side in ("L", "R"):
            forearm = rig.pose.bones[f"forearm.{side}"]
            constraint = next(c for c in forearm.constraints if c.type == "IK")
            assert constraint.influence == 1 and not constraint.mute and not constraint.use_stretch
            assert constraint.target == rig and constraint.subtarget == f"IK_Arm.{side}"
            assert constraint.pole_target == rig and constraint.pole_subtarget == f"IK_Pole_Arm.{side}"
            arm = evaluated_arm(rig, side)
            max_tracking = max(max_tracking, (arm["wrist"] - arm["target"]).length)
            axis, bend = projected_bend(arm)
            if side in previous_arms:
                previous = previous_arms[side]
                elbow_step = (arm["elbow"] - previous["elbow"]).length
                if elbow_step > max_elbow_step:
                    max_elbow_step = elbow_step
                    max_elbow_step_at = (side, phase)
                if raised + 1 / 300 <= phase <= release:
                    max_hold_step = max(max_hold_step, elbow_step)
                angle = arm["upper_matrix"].to_quaternion().rotation_difference(previous["upper_matrix"].to_quaternion()).angle
                angle = min(angle, math.tau - angle)
                previous_bend = projected_bend(previous)[1]
                plane_change = bend.normalized().dot(previous_bend.normalized())
                if elbow_step > 0.025 or angle > math.radians(10) or plane_change < 0.95:
                    convergence_checks.append((side, phase, elbow_step, angle))
            previous_arms[side] = arm
            preferred = torso_rotation @ Vector((0.65 if side == "L" else -0.65, 0, -1))
            preferred -= axis * preferred.dot(axis)
            # 내려둔 팔은 레스트 굴곡을 유지하므로 인사 팔의 아래·바깥 기준을 강제하지 않는다.
            if side == plan["side"] and raised <= phase <= release and bend.length > 0.005 and preferred.length > 0.05:
                alignment = bend.normalized().dot(preferred.normalized())
                minimum_bend_alignment = min(minimum_bend_alignment, alignment)
                assert alignment > 0.0, ("팔꿈치 굴곡 평면이 해부학적 방향의 반대입니다", plan, side, phase, alignment)
            if index in (0, 300):
                roll = neutral_roll_alignment(rig, side, arm)
                minimum_roll = min(minimum_roll, roll)
                assert roll > 0.95, ("시작·끝 팔 레스트 롤이 반전되었습니다", plan, side, phase, roll)
    assert minimum_clearance > 0.01, (plan, "얼굴 앞 여유", minimum_clearance)
    assert max_tracking < 0.002, (plan, "손목 IK 추종", max_tracking)
    assert max_hold_step < 0.025, (plan, "인사 구간 팔꿈치 튐", max_hold_step)
    for side, phase, distance, angle in convergence_checks:
        check_subframe_continuity(rig, spec, side, phase, distance, angle)
    scene.frame_set(round(spec.start_frame + spec.frame_count * 0.5))
    bpy.context.view_layer.update()
    # 실제 Action이 연결된 상태에서 G 이동과 같은 포즈 편집 경로를 검사한다.
    responses = {side: check_pole_response(rig, side) for side in ("L", "R")}
    rig.animation_data.action = None
    side = plan["side"]
    controller = rig.pose.bones[f"IK_Arm.{side}"]
    before = evaluated_arm(rig, side)["wrist"]
    controller.location += controller.bone.matrix_local.to_3x3().inverted() @ Vector((0, -0.01, 0))
    rig.update_tag(refresh={"OBJECT"})
    movement = (evaluated_arm(rig, side)["wrist"] - before).length
    assert movement > 0.007, ("IK 손목 컨트롤러에 손이 반응하지 않습니다", movement)
    print("CATANI_ARM_IK", json.dumps({"side": side, "torso_turn": plan["torso_turn"],
          "head_turn": plan["head_turn"], "face_clearance": minimum_clearance, "keys": key_count,
          "bend_alignment": minimum_bend_alignment, "neutral_roll": minimum_roll,
          "max_elbow_step": max_elbow_step, "max_elbow_step_at": max_elbow_step_at,
          "subframe_checks": len(convergence_checks),
          "tracking_error": max_tracking, "controller_response": movement, "pole_response": responses}))
    engine.cancel_preview(bpy.context)
