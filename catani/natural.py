"""시선·체중 이동·팔 동작을 시간차로 연결하는 전신 인사 레시피."""

import math


def _pulse(amplitude, start, peak, release, end):
    phases = [(0.0, 0.0), (start, 0.0), (peak, amplitude), (release, amplitude), (end, 0.0), (1.0, 0.0)]
    return [(phase, value, 0.0, 0.0) for phase, value in dict(phases).items()]


def _rotation(vector, phases):
    angle = math.sqrt(sum(value * value for value in vector))
    axis = tuple(value / angle for value in vector) if angle > 1e-12 else (1.0, 0.0, 0.0)
    return {"axis": axis, "knots": _pulse(angle, *phases)}


def natural_channels(plan):
    """각 본의 고정 회전축과 연기 단계별 희소 각도 키를 반환한다."""
    sign = 1 if plan["side"] == "R" else -1
    side = plan["side"]
    anticipation = plan["anticipation"]
    release = 1.0 - plan["settle"]
    degree = math.radians
    channels = {
        "head": _rotation((0.0, 0.0, -sign * degree(plan["head_turn"])), (0.0, anticipation * 0.65, release + 0.06, 1.0)),
        "neck": _rotation((degree(-2.0 if plan["style"] == "shy" else 1.0), 0.0, 0.0), (0.02, anticipation, release + 0.04, 0.98)),
        "spine.001": _rotation((degree(plan["torso_lean"] * 0.35), 0.0, -sign * degree(plan["torso_turn"] * 0.3)), (0.02, anticipation + 0.02, release - 0.05, 0.94)),
        "spine.002": _rotation((degree(plan["torso_lean"] * 0.65), 0.0, -sign * degree(plan["torso_turn"] * 0.7)), (0.06, anticipation + 0.08, release, 0.97)),
        f"shoulder.{side}": _rotation((0.0, sign * degree(5.0), 0.0), (anticipation * 0.5, anticipation + 0.11, release, 0.98)),
    }
    # 팔 인사 구간에 호흡 한 번을 더해 상체가 고정된 채 팔만 움직이지 않게 한다.
    for name, rise, fall in (("spine.002", 1.08, 0.94), (f"shoulder.{side}", 1.05, 0.97)):
        knots = channels[name]["knots"]
        peak_index = next((index for index, knot in enumerate(knots) if abs(knot[1]) > 1e-12), None)
        if peak_index is None:
            continue
        peak, hold_end = knots[peak_index], knots[peak_index + 1]
        span = hold_end[0] - peak[0]
        response = [
            (peak[0] + span / 3.0, peak[1] * rise, 0.0, 0.0),
            (peak[0] + span * 2.0 / 3.0, peak[1] * fall, 0.0, 0.0),
        ]
        knots[peak_index + 1:peak_index + 1] = response
    return channels


def hand_target_knots(plan, side, rest, shoulder, length):
    """음의 Y 전방으로 손목을 옮긴 뒤 얼굴 옆에서 실제 IK 목표를 흔든다."""
    sign = 1 if side == "L" else -1
    anticipation = plan["anticipation"]
    release = 1.0 - plan["settle"]
    if side != plan["side"]:
        target = (rest[0] + sign * length * 0.035, rest[1] - length * 0.08, rest[2] + length * 0.045)
        phases = (0.02, anticipation + 0.04, release - 0.03, 0.99)
        return [[(phase, rest[index] + value, left, right) for phase, value, left, right in _pulse(target[index] - rest[index], *phases)] for index in range(3)]
    raised = anticipation + 0.16
    target = (shoulder[0] + sign * length * 0.34, shoulder[1] - length * 0.58, shoulder[2] + length * (0.44 + (plan["arm_lift"] - 90.0) / 700.0))
    amplitudes = (length * 0.06 * plan["wrist_swing"] / 14.0, 0.0, length * 0.016)
    count = 4 * plan["repeat"]
    result = []
    for component in range(3):
        knots = [(0.0, rest[component], 0.0, 0.0), (anticipation * 0.65, rest[component], 0.0, 0.0)]
        for index in range(count + 1):
            phase = index / count
            angle = math.tau * plan["repeat"] * phase
            amplitude = amplitudes[component]
            value = target[component] + amplitude * math.sin(angle)
            slope = amplitude * math.tau * plan["repeat"] / (release - raised) * math.cos(angle)
            knots.append((raised + (release - raised) * phase, value, 0.0 if index == 0 else slope, 0.0 if index == count else slope))
        knots.extend([(0.98, rest[component], 0.0, 0.0), (1.0, rest[component], 0.0, 0.0)])
        result.append(knots)
    return result


def pelvis_channels(plan, height):
    """아마추어 공간의 골반 이동량을 반환한다. 양발 고정 IK와 함께 사용한다."""
    sign = 1 if plan["side"] == "R" else -1
    amount = height * plan["weight_shift"]
    phases = (0.0, plan["anticipation"], 1.0 - plan["settle"] - 0.04, 0.96)
    return [
        _pulse(-sign * amount, *phases),
        _pulse(-amount * 0.15, *phases),
        _pulse(-height * (0.004 + plan["weight_shift"] * 0.45), *phases),
    ]
