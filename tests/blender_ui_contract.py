"""실제 등록된 UI에서 제거된 에이전트·JSON 명세 경로가 되살아나지 않는지 검사한다."""

from pathlib import Path
from types import SimpleNamespace

import bpy
import bl_ext.user_default.catani as addon
from bl_ext.user_default.catani.source_catalog import CATALOG


class RecordedLayout:
    """패널의 실제 draw 경로가 노출하는 연산자와 속성을 기록한다."""

    def __init__(self):
        self.operators = []
        self.properties = []
        self.labels = []
        self.buttons = []

    def row(self, **kwargs):
        return self

    def column(self, **kwargs):
        return self

    def box(self):
        return self

    def separator(self, **kwargs):
        pass

    def label(self, *, text="", **kwargs):
        self.labels.append(text)

    def prop(self, data, name, **kwargs):
        self.properties.append(name)

    def operator(self, identifier, **kwargs):
        self.operators.append(identifier)
        button = SimpleNamespace(identifier=identifier)
        self.buttons.append(button)
        return button


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
for suffix in ("agent_generate", "agent_cancel", "plan_default", "plan_import", "plan_export"):
    assert bpy.types.Operator.bl_rna_get_subclass_py(f"CATANI_OT_{suffix}") is None, f"제거된 연산자가 등록되었습니다: {suffix}"
settings = bpy.context.scene.catani_settings
for name in ("prompt", "codex_path", "plan_json", "agent_status"):
    assert name not in settings.bl_rna.properties, f"제거된 입력이 남았습니다: {name}"
if "recipe" in settings.bl_rna.properties:
    assert "natural_wave" not in settings.bl_rna.properties["recipe"].enum_items.keys()
try:
    addon.MotionSpec(recipe="natural_wave")
except ValueError:
    pass
else:
    raise AssertionError("제거된 자연 인사 명세 경로가 엔진에서 다시 허용되었습니다")
layout = RecordedLayout()
addon.CATANI_PT_main.draw(SimpleNamespace(layout=layout), bpy.context)
assert "catani.motion_refresh" in layout.operators
assert "catani.motion_import" in layout.operators
assert "catani.motion_download" in layout.operators
assert "motion_library_path" in layout.properties
assert not any(name.startswith(("catani.agent_", "catani.plan_")) for name in layout.operators)
assert not {"prompt", "codex_path", "plan_json", "agent_status"}.intersection(layout.properties)
visible_urls = {getattr(button, "url", "") for button in layout.buttons}
assert any(entry.source_url in visible_urls for entry in CATALOG), "카탈로그 출처 링크가 UI에 없습니다"
assert any(entry.license_url in visible_urls for entry in CATALOG), "카탈로그 이용 조건 링크가 UI에 없습니다"
addon.unregister()
addon.register()
print("CATANI_PASS 모션 라이브러리 UI 유지·에이전트와 JSON 명세 UI 제거·재등록")
