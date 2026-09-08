"""저장된 명세 또는 고정 fixture로 UI 가져오기·생성 경로와 비동기 상태를 검사한다."""
import json
from pathlib import Path
from unittest.mock import patch
import bpy
import bl_ext.user_default.catani as addon

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
source = bpy.data.objects["Amature_Player"]
bpy.context.view_layer.objects.active = source
bpy.context.view_layer.update()
if bpy.context.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
originals = set(bpy.data.objects)
settings = bpy.context.scene.catani_settings
settings.recipe = "natural_wave"
path = root / "artifacts/Agent_Natural_Wave_Plan.json"
if not path.exists():
    path = root / "tests/fixtures/natural_wave_plan.json"
assert bpy.ops.catani.plan_import(filepath=str(path)) == {"FINISHED"}
assert json.loads(settings.plan_json) == json.loads(path.read_text())
assert bpy.ops.catani.preview() == {"FINISHED"}
session = addon.engine.get_session()
assert json.loads(session["action"]["catani_motion_spec"])["plan"] == json.loads(settings.plan_json)
assert bpy.ops.catani.cancel() == {"FINISHED"}
assert set(bpy.data.objects) == originals
assert bpy.ops.catani.plan_export(filepath=str(root / "artifacts/Agent_Plan_Roundtrip.json")) == {"FINISHED"}
assert json.loads((root / "artifacts/Agent_Plan_Roundtrip.json").read_text()) == json.loads(path.read_text())


class FakeJob:
    def __init__(self, *args, **kwargs):
        self._closed = False
        self.calls = 0
    def poll(self):
        self.calls += 1
        if self.calls == 1:
            return None
        self.close()
        return dict(addon.DEFAULT_PLAN)
    def close(self):
        self._closed = True


with patch.object(addon, "AgentJob", FakeJob):
    assert bpy.ops.catani.agent_generate() == {"FINISHED"}
    assert addon._poll_agent() == 0.3
    assert set(bpy.data.objects) == originals
    assert addon._poll_agent() is None
    addon._stop_agent()
    assert json.loads(settings.plan_json) == addon.DEFAULT_PLAN
    assert bpy.ops.catani.agent_generate() == {"FINISHED"}
    job = addon._agent_job
    assert bpy.ops.catani.agent_cancel() == {"FINISHED"}
    assert job._closed and addon._agent_job is None
unsupported = dict(addon.DEFAULT_PLAN, supported=False, reason="걷기는 아직 지원하지 않습니다.")
settings.plan_json = json.dumps(unsupported)
try:
    outcome = bpy.ops.catani.preview()
    assert outcome == {"CANCELLED"}
except RuntimeError:
    pass
assert addon.engine.get_session() is None
assert set(bpy.data.objects) == originals
addon.unregister()
addon.register()
print("CATANI_PASS 명세 UI 입출력·생성·비동기 상태·취소·미지원 요청 거부")
