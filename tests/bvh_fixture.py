"""검사용 합성 BVH 생성기. CMU / cgspeed 규격 관절 이름을 그대로 쓴다."""

import math
from pathlib import Path

# (이름, BVH 오프셋, 자식) — CMU / cgspeed 규격 관절 이름을 그대로 쓴다.
def _limb(side, sign):
    return [
        (f"{side}Shoulder", (3.0 * sign, 3.0, 0.0), [
            (f"{side}Arm", (4.0 * sign, 0.0, 0.0), [
                (f"{side}ForeArm", (5.0 * sign, 0.0, 0.0), [
                    (f"{side}Hand", (4.0 * sign, 0.0, 0.0), []),
                ]),
            ]),
        ]),
    ]


def _leg(side, sign):
    return (f"{side}UpLeg", (2.0 * sign, -1.0, 0.0), [
        (f"{side}Leg", (0.0, -8.0, 0.0), [
            (f"{side}Foot", (0.0, -8.0, 0.0), [
                (f"{side}ToeBase", (0.0, -2.0, 2.0), []),
            ]),
        ]),
    ])


TREE = ("Hips", (0.0, 0.0, 0.0), [
    ("LowerBack", (0.0, 4.0, 0.0), [
        ("Spine", (0.0, 4.0, 0.0), [
            ("Spine1", (0.0, 4.0, 0.0), [
                ("Neck", (0.0, 4.0, 0.0), [("Head", (0.0, 3.0, 0.0), [])]),
                *_limb("Left", 1),
                *_limb("Right", -1),
            ]),
        ]),
    ]),
    _leg("Left", 1),
    _leg("Right", -1),
])

FRAMES = 9
ROTATED = {"Spine": (0.0, 6.0, 0.0), "LeftArm": (-55.0, 0.0, 0.0), "LeftForeArm": (-35.0, 0.0, 0.0),
           "RightArm": (40.0, 0.0, 0.0), "LeftUpLeg": (0.0, 0.0, 25.0), "RightLeg": (0.0, 0.0, -20.0),
           "Head": (0.0, 12.0, 0.0)}


def _joints(node):
    name, _offset, children = node
    return [name, *(item for child in children for item in _joints(child))]


def _hierarchy(node, depth=1):
    name, offset, children = node
    pad = "  " * depth
    label = "ROOT" if depth == 1 else "JOINT"
    channels = "6 Xposition Yposition Zposition Zrotation Xrotation Yrotation" if depth == 1 else "3 Zrotation Xrotation Yrotation"
    lines = [f"{pad}{label} {name}", f"{pad}{{", f"{pad}  OFFSET {offset[0]:.4f} {offset[1]:.4f} {offset[2]:.4f}", f"{pad}  CHANNELS {channels}"]
    if children:
        for child in children:
            lines.extend(_hierarchy(child, depth + 1))
    else:
        lines.extend([f"{pad}  End Site", f"{pad}  {{", f"{pad}    OFFSET 0.0000 2.0000 0.0000", f"{pad}  }}"])
    lines.append(f"{pad}}}")
    return lines


def write_bvh(path):
    """관절마다 다른 회전과 루트 이동이 들어간 합성 모션을 만든다."""
    order = _joints(TREE)
    rows = []
    for frame in range(FRAMES):
        phase = frame / (FRAMES - 1)
        values = [0.0, 17.0 + 1.5 * math.sin(phase * math.tau), 6.0 * phase, 0.0, 0.0, 4.0 * phase]
        for name in order[1:]:
            base = ROTATED.get(name, (0.0, 0.0, 0.0))
            values.extend(component * phase for component in base)
        rows.append(" ".join(f"{value:.4f}" for value in values))
    text = "\n".join(["HIERARCHY", *_hierarchy(TREE), "MOTION", f"Frames: {FRAMES}", "Frame Time: 0.0333333", *rows, ""])
    Path(path).write_text(text, encoding="utf-8")
    return order
