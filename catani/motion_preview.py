"""BVH 표본 프레임을 스틱 피겨 미리보기 픽셀로 바꾼다.

목록에서 모션을 고를 때 실제 동작을 짐작할 수 있도록, 파일 전체를 읽지 않고
고르게 뽑은 몇 프레임만 순운동학으로 풀어 정면 3/4 시점으로 그린다.
bpy에 의존하지 않으므로 Blender 없이도 검사할 수 있다.
"""

from dataclasses import dataclass
import math

SAMPLE_COUNT = 6
THUMB_SIZE = 128  # Blender 프리뷰 이미지 표준 크기
YAW = math.radians(28.0)
BONE_COLOR = (0.72, 0.84, 1.0)
GHOST_COLOR = (0.42, 0.50, 0.66)
_MARGIN = 0.88
_CHANNEL_AXIS = {"XROTATION": 0, "YROTATION": 1, "ZROTATION": 2}
_CHANNEL_MOVE = {"XPOSITION": 0, "YPOSITION": 1, "ZPOSITION": 2}


@dataclass(frozen=True)
class MotionSketch:
    """표본 프레임의 뼈대를 0~1 좌표로 정규화해 담는다."""

    frames: int
    frame_time: float
    joints: int
    bones: tuple           # (부모 인덱스, 자식 인덱스) 쌍
    poses: tuple           # 프레임별 ((x, y), ...) 관절 위치

    @property
    def duration(self):
        return self.frames * self.frame_time

    @property
    def fps(self):
        return 1.0 / self.frame_time if self.frame_time > 0 else 0.0


def _rotation(axis, degrees):
    """열벡터 규약의 3x3 회전 행렬."""
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    if axis == 0:
        return ((1.0, 0.0, 0.0), (0.0, cos, -sin), (0.0, sin, cos))
    if axis == 1:
        return ((cos, 0.0, sin), (0.0, 1.0, 0.0), (-sin, 0.0, cos))
    return ((cos, -sin, 0.0), (sin, cos, 0.0), (0.0, 0.0, 1.0))


def _multiply(left, right):
    return tuple(tuple(sum(left[row][k] * right[k][col] for k in range(3)) for col in range(3)) for row in range(3))


def _transform(matrix, vector):
    return tuple(sum(matrix[row][k] * vector[k] for k in range(3)) for row in range(3))


_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _parse_header(handle):
    """HIERARCHY를 읽어 관절과 채널 순서를 돌려준다. MOTION 직전에서 멈춘다."""
    joints = []
    stack = []
    channels = []
    pending = None
    for line in handle:
        parts = line.split()
        if not parts:
            continue
        key = parts[0].upper()
        if key in {"ROOT", "JOINT"}:
            pending = " ".join(parts[1:]) or f"joint{len(joints)}"
        elif key == "END":
            pending = "End Site"
        elif key == "{":
            joints.append({"name": pending or f"joint{len(joints)}", "parent": stack[-1] if stack else -1, "offset": (0.0, 0.0, 0.0)})
            stack.append(len(joints) - 1)
            pending = None
        elif key == "}":
            if stack:
                stack.pop()
        elif key == "OFFSET" and stack:
            joints[stack[-1]]["offset"] = tuple(float(value) for value in parts[1:4])
        elif key == "CHANNELS" and stack:
            channels.extend((stack[-1], name.upper()) for name in parts[2:])
        elif key == "MOTION":
            break
    if not joints or not channels:
        raise ValueError("BVH 뼈대 정보를 읽지 못했습니다.")
    return joints, channels


def _parse_motion_meta(handle):
    frames, frame_time = 0, 0.0
    for line in handle:
        lowered = line.strip().lower()
        if lowered.startswith("frames:"):
            frames = int(float(lowered.split(":", 1)[1]))
        elif lowered.startswith("frame time:"):
            frame_time = float(lowered.split(":", 1)[1])
            break
    if frames <= 0:
        raise ValueError("BVH 프레임 수를 읽지 못했습니다.")
    return frames, frame_time or 1.0 / 30.0


def _sample_indices(frames, samples):
    """모캡 앞머리의 T 포즈를 건너뛰고 본 동작 구간에서 고르게 뽑는다."""
    count = max(1, min(samples, frames))
    first = int(frames * 0.08) if frames > 24 else 0
    if count == 1:
        return [first]
    return [first + round(index * (frames - 1 - first) / (count - 1)) for index in range(count)]


def _read_rows(handle, indices):
    """필요한 프레임 줄만 숫자로 바꾼다. 파일 전체를 파싱하지 않는다."""
    wanted = set(indices)
    last = max(wanted)
    rows = {}
    position = 0
    for line in handle:
        if not line.strip():
            continue
        if position in wanted:
            rows[position] = [float(value) for value in line.split()]
        if position >= last:
            break
        position += 1
    return rows


def _pose(joints, channels, values):
    """한 프레임의 관절 월드 위치를 순운동학으로 구한다."""
    rotations = [_IDENTITY] * len(joints)
    positions = [(0.0, 0.0, 0.0)] * len(joints)
    local_rotation = [None] * len(joints)
    local_move = [(0.0, 0.0, 0.0)] * len(joints)
    for slot, (joint, name) in enumerate(channels):
        if slot >= len(values):
            break
        if name in _CHANNEL_AXIS:
            matrix = _rotation(_CHANNEL_AXIS[name], values[slot])
            local_rotation[joint] = matrix if local_rotation[joint] is None else _multiply(local_rotation[joint], matrix)
        elif name in _CHANNEL_MOVE:
            axis = _CHANNEL_MOVE[name]
            move = list(local_move[joint])
            move[axis] = values[slot]
            local_move[joint] = tuple(move)
    for index, joint in enumerate(joints):
        parent = joint["parent"]
        offset = tuple(joint["offset"][axis] + local_move[index][axis] for axis in range(3))
        rotation = local_rotation[index] or _IDENTITY
        if parent < 0:
            positions[index] = offset
            rotations[index] = rotation
        else:
            positions[index] = tuple(positions[parent][axis] + _transform(rotations[parent], offset)[axis] for axis in range(3))
            rotations[index] = _multiply(rotations[parent], rotation)
    return positions


def _up_axis(joints):
    """뼈대 오프셋이 가장 길게 뻗은 축을 위쪽으로 본다. Z-up BVH도 바로 선다."""
    spans = [0.0, 0.0, 0.0]
    rest = []
    for joint in joints:
        parent = joint["parent"]
        base = rest[parent] if parent >= 0 else (0.0, 0.0, 0.0)
        rest.append(tuple(base[axis] + joint["offset"][axis] for axis in range(3)))
    for axis in range(3):
        values = [point[axis] for point in rest]
        spans[axis] = max(values) - min(values)
    return 2 if spans[2] > spans[1] else 1


def _project(pose, up):
    """위쪽 축을 세우고 28도 돌린 3/4 시점으로 평면에 내린다."""
    cos, sin = math.cos(YAW), math.sin(YAW)
    result = []
    for point in pose:
        if up == 1:
            forward, height, side = point[0], point[1], point[2]
        else:
            forward, height, side = point[0], point[2], -point[1]
        result.append((forward * cos + side * sin, height))
    return result


def _normalise(poses):
    """모든 표본이 같은 배율을 쓰도록 맞추고, 가로 위치만 골반에 고정한다."""
    shifted = [[(x - pose[0][0], y) for x, y in pose] for pose in poses]
    xs = [x for pose in shifted for x, _ in pose]
    ys = [y for pose in shifted for _, y in pose]
    width = max(max(xs) - min(xs), 1e-6)
    height = max(max(ys) - min(ys), 1e-6)
    scale = _MARGIN / max(width, height)
    center_x = (max(xs) + min(xs)) / 2.0
    center_y = (max(ys) + min(ys)) / 2.0
    return tuple(tuple((0.5 + (x - center_x) * scale, 0.5 + (y - center_y) * scale) for x, y in pose) for pose in shifted)


def sketch(path, samples=SAMPLE_COUNT):
    """BVH 파일에서 표본 프레임 뼈대를 뽑는다. 실패하면 ValueError."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        joints, channels = _parse_header(handle)
        frames, frame_time = _parse_motion_meta(handle)
        indices = _sample_indices(frames, samples)
        rows = _read_rows(handle, indices)
    if not rows:
        raise ValueError("BVH 모션 데이터를 읽지 못했습니다.")
    up = _up_axis(joints)
    poses = [_project(_pose(joints, channels, rows[index]), up) for index in indices if index in rows]
    bones = tuple((joint["parent"], index) for index, joint in enumerate(joints) if joint["parent"] >= 0)
    return MotionSketch(frames=frames, frame_time=frame_time, joints=len(joints), bones=bones, poses=_normalise(poses))


def _splat(buffer, size, x, y, color, weight):
    """부동 소수 좌표를 이웃 네 픽셀에 나눠 찍어 계단을 줄인다."""
    if weight <= 0.0 or not (-1.0 < x < size and -1.0 < y < size):
        return
    left, bottom = math.floor(x), math.floor(y)
    fraction_x, fraction_y = x - left, y - bottom
    for offset_x, offset_y, share in (
        (0, 0, (1 - fraction_x) * (1 - fraction_y)), (1, 0, fraction_x * (1 - fraction_y)),
        (0, 1, (1 - fraction_x) * fraction_y), (1, 1, fraction_x * fraction_y),
    ):
        column, row = left + offset_x, bottom + offset_y
        if not (0 <= column < size and 0 <= row < size):
            continue
        alpha = share * weight
        if alpha <= 0.0:
            continue
        base = (row * size + column) * 4
        previous = buffer[base + 3]
        if alpha <= previous:
            continue
        buffer[base] = color[0]
        buffer[base + 1] = color[1]
        buffer[base + 2] = color[2]
        buffer[base + 3] = alpha


def _line(buffer, size, start, end, color, weight, thickness):
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    steps = max(2, int(distance) + 2)
    for step in range(steps + 1):
        ratio = step / steps
        x = start[0] + (end[0] - start[0]) * ratio
        y = start[1] + (end[1] - start[1]) * ratio
        _splat(buffer, size, x, y, color, weight)
        if thickness > 1:
            for shift in (-1, 1):
                _splat(buffer, size, x + shift * 0.7, y, color, weight * 0.75)
                _splat(buffer, size, x, y + shift * 0.7, color, weight * 0.75)


def pixels(motion, index, size=THUMB_SIZE, ghost=True):
    """표본 한 장을 RGBA 실수 픽셀로 그린다. 아래 행이 먼저 오는 Blender 순서."""
    buffer = [0.0] * (size * size * 4)
    order = []
    if ghost and index > 0:
        order.append((motion.poses[index - 1], GHOST_COLOR, 0.35, 1))
    order.append((motion.poses[index], BONE_COLOR, 1.0, 2))
    for pose, color, weight, thickness in order:
        points = [(x * size, y * size) for x, y in pose]
        for parent, child in motion.bones:
            _line(buffer, size, points[parent], points[child], color, weight, thickness)
    return buffer
