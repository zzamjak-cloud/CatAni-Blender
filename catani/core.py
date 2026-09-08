"""로컬 보조 절차 동작의 최소 곡선 샘플러."""

from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class MotionSpec:
    recipe: str = "idle"
    side: str = "R"
    duration: float = 2.0
    intensity: float = 0.7
    repeat: int = 2
    fps: float = 24.0
    start_frame: int = 1

    def __post_init__(self):
        if self.recipe not in {"idle", "wave"}:
            raise ValueError("지원 보조 동작은 idle, wave입니다.")
        if self.side not in {"L", "R"}:
            raise ValueError("손 방향은 L 또는 R이어야 합니다.")
        for name in ("duration", "intensity", "fps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"{name}: 유한한 숫자를 입력하세요.")
        if not 0.5 <= self.duration <= 10.0 or not 0.1 <= self.intensity <= 1.0:
            raise ValueError("길이는 0.5~10초, 강도는 0.1~1입니다.")
        if not 1 <= self.fps <= 240:
            raise ValueError("FPS는 1~240입니다.")
        if type(self.repeat) is not int or not 1 <= self.repeat <= 8:
            raise ValueError("반복 횟수는 정수 1~8입니다.")
        if type(self.start_frame) is not int or self.start_frame < 1:
            raise ValueError("시작 프레임은 1 이상의 정수입니다.")

    @property
    def frame_count(self):
        return max(2, round(self.duration * self.fps))

    @property
    def end_frame(self):
        return self.start_frame + self.frame_count

    def to_json(self):
        return json.dumps({"schema_version": 1, "engine_version": "0.5.1", "rig_profile": "player_v1", "curve_encoding": "sparse_axis_angle_bezier", **asdict(self)}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sample_motion(spec, progress):
    """각 뼈의 아마추어 공간 회전 벡터(라디안)를 반환한다."""
    t = max(0.0, min(1.0, progress))
    strength = spec.intensity
    breath = math.sin(t * math.tau * spec.repeat)
    result = {"spine.002": (0.025 * strength * breath, 0.0, 0.0), "head": (-0.012 * strength * breath, 0.0, 0.0)}
    if spec.recipe == "wave":
        ramp = min(t / 0.22, (1.0 - t) / 0.22, 1.0)
        envelope = ramp * ramp * (3.0 - 2.0 * ramp)
        sign = 1 if spec.side == "R" else -1
        swing = math.sin(math.tau * spec.repeat * max(0.0, min(1.0, (t - 0.22) / 0.56)))
        result[f"upper_arm.{spec.side}"] = (0.0, sign * math.radians(130) * envelope, 0.0)
        result[f"forearm.{spec.side}"] = (0.0, sign * math.radians(12) * envelope + math.radians(14) * strength * envelope * swing, 0.0)
        result[f"hand.{spec.side}"] = (math.radians(10) * strength * envelope * swing, 0.0, 0.0)
    return result


def sparse_channels(spec):
    """본별 고정 축과 (위상, 각도, 좌미분, 우미분) 최소 곡선 키를 만든다."""
    frequency = math.tau * spec.repeat
    quarter_phases = [i / (4 * spec.repeat) for i in range(4 * spec.repeat + 1)]
    channels = {}
    for name, amplitude in (("spine.002", 0.025 * spec.intensity), ("head", -0.012 * spec.intensity)):
        knots = []
        for phase in quarter_phases:
            value = amplitude * math.sin(frequency * phase)
            slope = amplitude * frequency * math.cos(frequency * phase)
            knots.append((phase, value, slope, slope))
        channels[name] = {"axis": (1.0, 0.0, 0.0), "knots": knots}
    if spec.recipe == "wave":
        sign = 1 if spec.side == "R" else -1
        channels[f"upper_arm.{spec.side}"] = {
            "axis": (0.0, 1.0, 0.0),
            "knots": [(0.0, 0.0, 0.0, 0.0), (0.22, sign * math.radians(130), 0.0, 0.0), (0.78, sign * math.radians(130), 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)],
        }
        for name, axis, baseline, amplitude in (
            (f"forearm.{spec.side}", (0.0, 1.0, 0.0), sign * math.radians(12), math.radians(14) * spec.intensity),
            (f"hand.{spec.side}", (1.0, 0.0, 0.0), 0.0, math.radians(10) * spec.intensity),
        ):
            knots = [(0.0, 0.0, 0.0, 0.0)]
            for index, phase in enumerate(quarter_phases):
                value = baseline + amplitude * math.sin(frequency * phase)
                slope = amplitude * frequency / 0.56 * math.cos(frequency * phase)
                knots.append((0.22 + 0.56 * phase, value, 0.0 if index == 0 else slope, 0.0 if index == len(quarter_phases) - 1 else slope))
            knots.append((1.0, 0.0, 0.0, 0.0))
            channels[name] = {"axis": axis, "knots": knots}
    return channels
