"""실행 코드가 아닌 제한된 전신 인사 동작 명세를 검증한다."""

import json
import math


DEFAULT_PLAN = {
    "schema_version": 1, "supported": True,
    "reason": "시선과 체중 이동으로 준비하고 가슴과 팔이 뒤따르는 친근한 전신 인사입니다.",
    "side": "R", "duration": 3.5, "repeat": 2, "style": "friendly",
    "weight_shift": 0.015, "torso_turn": 8.0, "torso_lean": 3.0,
    "head_turn": 10.0, "arm_lift": 105.0, "wrist_swing": 14.0,
    "anticipation": 0.18, "settle": 0.22,
}

_RANGES = {
    "duration": (2.0, 6.0), "repeat": (1, 4), "weight_shift": (0.0, 0.025),
    "torso_turn": (-12.0, 12.0), "torso_lean": (0.0, 8.0),
    "head_turn": (-15.0, 15.0), "arm_lift": (90.0, 125.0),
    "wrist_swing": (8.0, 22.0), "anticipation": (0.12, 0.22), "settle": (0.12, 0.25),
}
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": list(DEFAULT_PLAN),
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "supported": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 500},
        "side": {"type": "string", "enum": ["L", "R"]},
        "style": {"type": "string", "enum": ["friendly", "shy", "energetic"]},
        **{name: {"type": "integer" if name == "repeat" else "number", "minimum": bounds[0], "maximum": bounds[1]} for name, bounds in _RANGES.items()},
    },
}


def validate_plan(value):
    """알 수 없는 필드, 비유한 수, 불리언 숫자를 거부하고 새 사본을 반환한다."""
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PLAN):
        raise ValueError("동작 명세 필드가 누락되었거나 허용하지 않는 필드가 있습니다.")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("동작 명세 버전은 정수 1이어야 합니다.")
    if type(value["supported"]) is not bool:
        raise ValueError("supported는 불리언이어야 합니다.")
    if not isinstance(value["reason"], str) or len(value["reason"]) > 500:
        raise ValueError("동작 설명은 500자 이하 문자열이어야 합니다.")
    if value["side"] not in ("L", "R") or value["style"] not in ("friendly", "shy", "energetic"):
        raise ValueError("지원하지 않는 방향 또는 인사 스타일입니다.")
    for name, (minimum, maximum) in _RANGES.items():
        number = value[name]
        if type(number) not in (int, float) or not minimum <= number <= maximum or not math.isfinite(number):
            raise ValueError(f"{name}: {minimum}~{maximum}의 유한한 숫자가 필요합니다.")
        if name == "repeat" and type(number) is not int:
            raise ValueError("반복 횟수는 정수여야 합니다.")
    return dict(value)


def parse_plan(text):
    if len(text.encode("utf-8")) > 16384:
        raise ValueError("동작 명세는 16KB를 넘을 수 없습니다.")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"중복 명세 필드: {key}")
            result[key] = value
        return result
    return validate_plan(json.loads(text, object_pairs_hook=unique_pairs))
