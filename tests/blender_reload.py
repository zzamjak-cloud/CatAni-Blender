"""별도 Blender 프로세스에서 베이크 포즈 재현을 확인한다."""
import json
import os
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "artifacts" / os.environ.get("CATANI_DEMO_NAME", "CatAni_Motion_Demo.blend")))
data = json.loads(bpy.context.scene["catani_verification"])
rig = bpy.data.objects[data["rig"]]
max_error = 0.0
for frame, expected in data["poses"].items():
    bpy.context.scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    for name, values in expected.items():
        actual = [v for row in rig.pose.bones[name].matrix for v in row]
        max_error = max(max_error, max(abs(a-b) for a, b in zip(actual, values)))
assert max_error < 1e-5, max_error
print("CATANI_PASS 재로드 포즈 최대 오차", max_error)
