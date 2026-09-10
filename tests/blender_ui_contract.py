"""주 패널이 검색·목록·적용을 담고 상세 설정과 출처만 팝업에 남는지 검사한다."""

from pathlib import Path
from types import SimpleNamespace
import tempfile

import bpy
import bl_ext.user_default.catani as addon
from bl_ext.user_default.catani.source_catalog import CATALOG


class RecordedLayout:
    """패널과 팝업의 실제 draw 경로가 노출하는 요소를 기록한다."""

    def __init__(self, sink=None):
        self.sink = sink if sink is not None else {"operators": [], "properties": [], "labels": [], "buttons": [], "lists": [], "icons": []}

    def _child(self):
        return RecordedLayout(self.sink)

    row = column = box = split = lambda self, **kwargs: self._child()

    def separator(self, **kwargs):
        pass

    def progress(self, **kwargs):
        pass

    def label(self, *, text="", **kwargs):
        self.sink["labels"].append(text)

    def prop(self, _data, name, **kwargs):
        self.sink["properties"].append(name)

    def template_list(self, listtype, _identifier, _data, propname, *args, **kwargs):
        self.sink["lists"].append((listtype, propname))

    def template_icon(self, *, icon_value=0, **kwargs):
        self.sink["icons"].append(icon_value)

    def operator(self, identifier, **kwargs):
        self.sink["operators"].append(identifier)
        button = SimpleNamespace(identifier=identifier)
        self.sink["buttons"].append(button)
        return button

    @property
    def alignment(self):
        return "EXPAND"

    @alignment.setter
    def alignment(self, _value):
        pass

    def __setattr__(self, name, value):
        if name in {"scale_y", "scale_x", "enabled", "active", "use_property_split", "alert"}:
            return
        object.__setattr__(self, name, value)


def record(draw, context):
    layout = RecordedLayout()
    draw(SimpleNamespace(layout=layout), context)
    return layout.sink


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))

for suffix in ("agent_generate", "agent_cancel", "plan_default", "plan_import", "plan_export"):
    assert bpy.types.Operator.bl_rna_get_subclass_py(f"CATANI_OT_{suffix}") is None, f"제거된 연산자가 등록되었습니다: {suffix}"
settings = bpy.context.scene.catani_settings
for name in ("prompt", "codex_path", "plan_json", "agent_status", "motion_index_json", "motion_selected_id"):
    assert name not in settings.bl_rna.properties, f"제거된 입력이 남았습니다: {name}"

main = record(addon.CATANI_PT_main.draw, bpy.context)
# 주 흐름: 검색 → 목록에서 고르기 → 대상 → 적용. 목록은 사이드바에서 바로 보인다.
assert main["lists"] == [("CATANI_UL_motions", "motions")], main["lists"]
assert addon._LIST_ROWS >= 16, addon._LIST_ROWS
assert {"motion_query", "motion_category", "local_only", "target_armature"} <= set(main["properties"]), main["properties"]
assert {"catani.motion_apply", "catani.motion_preview", "catani.motion_refresh"} <= set(main["operators"]), main["operators"]
assert main["operators"].count("catani.motion_apply") == 1
# 폴더·굽기 옵션 같은 상세 설정과 받기 전용 경로는 주 패널에 없어야 한다.
for hidden in ("motion_library_path", "frame_step", "smooth_window", "simplify_error", "use_location", "hide_source"):
    assert hidden not in main["properties"], f"상세 설정이 주 패널에 노출되었습니다: {hidden}"
for hidden in ("catani.motion_download", "catani.motion_import", "wm.url_open"):
    assert hidden not in main["operators"], f"보조 동작이 주 패널에 노출되었습니다: {hidden}"
# 표본 포즈 그림은 제거했다. 목록 높이를 아이콘에 내주지 않는다.
assert main["icons"] == [], main["icons"]
assert bpy.types.Operator.bl_rna_get_subclass_py("CATANI_OT_motion_browser") is None, "제거한 팝업 연산자가 남았습니다"
joined = " ".join(main["labels"])
for entry in CATALOG:
    assert entry.license_note not in joined, "이용 조건 원문이 주 패널에 노출되었습니다"
    assert entry.source_name not in joined, "출처 문구가 주 패널에 노출되었습니다"
assert {"catani.motion_info", "catani.settings"} <= set(main["operators"]), main["operators"]

# 출처 팝업이 실제 다운로드 주소와 이용 조건, 원문 링크를 담는지.
settings.motion_library_path = ""
settings.motion_query = ""
addon.refresh(bpy.context.scene)
assert len(settings.motions) == len(CATALOG), [item.name for item in settings.motions]
settings.motion_active = 0
selected = settings.motions[0]
info = record(addon.CATANI_OT_motion_info.draw, bpy.context)
text = " ".join(info["labels"])
# 긴 주소는 팝업 폭에 맞춰 여러 줄로 접히므로 공백을 없애고 이어 붙여 검사한다.
packed = text.replace(" ", "")
assert selected.download_url in packed, "팝업에 실제 다운로드 주소가 없습니다"
checksum = selected.blob_sha1 or selected.sha256
assert checksum and checksum in packed, "팝업에 체크섬이 없습니다"
assert selected.license_note.split(".")[0].replace(" ", "") in packed, "팝업에 이용 조건이 없습니다"
urls = {getattr(button, "url", "") for button in info["buttons"]}
assert selected.source_url in urls and selected.license_url in urls, urls

# 상세 팝업이 폴더·굽기 옵션·리포트와 보조 연산자를 담는지.
detail = record(addon.CATANI_OT_settings.draw, bpy.context)
assert {"motion_library_path", "frame_step", "use_location", "hide_source"} <= set(detail["properties"]), detail["properties"]
assert {"catani.motion_refresh", "catani.motion_download", "catani.motion_import"} <= set(detail["operators"]), detail["operators"]
assert any("적용 리포트" in label for label in detail["labels"]), detail["labels"]

# 받아 둔 BVH는 머리글만 읽어 길이를 표시한다. 표본 프레임은 읽지 않는다.
temporary = tempfile.TemporaryDirectory(prefix="catani-ui-contract-")
library = Path(temporary.name)
(library / "wave.bvh").write_text("""HIERARCHY
ROOT Hips
{
    OFFSET 0.00 0.00 0.00
    CHANNELS 3 Zrotation Xrotation Yrotation
    End Site
    {
        OFFSET 0.00 4.00 0.00
    }
}
MOTION
Frames: 120
Frame Time: 0.0416667
""" + "0.00 0.00 0.00\n" * 120, encoding="utf-8")
settings.motion_library_path = str(library)
settings.local_only = True
addon.refresh(bpy.context.scene)
assert len(settings.motions) == 1, [item.name for item in settings.motions]
settings.motion_active = 0
assert addon._duration_line(settings.motions[0]) == "120프레임 · 약 5.0초 · 24 fps", addon._duration_line(settings.motions[0])
local = record(addon.CATANI_PT_main.draw, bpy.context)
assert any("5.0초" in label for label in local["labels"]), local["labels"]
settings.local_only = False
settings.motion_library_path = ""
temporary.cleanup()

addon.unregister()
addon.register()
print("CATANI_PASS 사이드바 목록·검색·길이 표시·상세/출처 팝업·재등록")
