"""주 패널은 목록 열기·대상·적용만 남고, 검색·표본 포즈·상세는 팝업에만 있는지 검사한다."""

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
# 주 흐름: 모션 샘플 보기(팝업) → 대상 → 적용. 좁은 사이드바에는 목록을 두지 않는다.
assert main["lists"] == [], main["lists"]
assert "catani.motion_browser" in main["operators"], main["operators"]
assert main["properties"] == ["target_armature"], main["properties"]
assert "catani.motion_apply" in main["operators"], main["operators"]
assert main["operators"].count("catani.motion_apply") == 1
# 복잡한 정보와 설정은 주 패널에 없어야 한다.
for hidden in ("motion_query", "motion_category", "local_only", "motion_library_path", "frame_step", "use_location", "hide_source"):
    assert hidden not in main["properties"], f"상세 설정이 주 패널에 노출되었습니다: {hidden}"
for hidden in ("catani.motion_download", "catani.motion_import", "catani.motion_refresh", "wm.url_open"):
    assert hidden not in main["operators"], f"보조 동작이 주 패널에 노출되었습니다: {hidden}"
joined = " ".join(main["labels"])
for entry in CATALOG:
    assert entry.license_note not in joined, "이용 조건 원문이 주 패널에 노출되었습니다"
    assert entry.source_name not in joined, "출처 문구가 주 패널에 노출되었습니다"
assert {"catani.motion_info", "catani.settings"} <= set(main["operators"]), main["operators"]
assert len(main["properties"]) + len(main["operators"]) <= 6, "주 패널 요소가 너무 많습니다"

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

# 모션 샘플 팝업: 넓은 목록과 검색·필터, 미리보기 재생, 대상 지정이 한 창에 모인다.
browser = record(addon.CATANI_OT_motion_browser.draw, bpy.context)
assert browser["lists"] == [("CATANI_UL_motions", "motions")], browser["lists"]
assert {"motion_query", "motion_category", "local_only", "target_armature"} <= set(browser["properties"]), browser["properties"]
assert {"catani.motion_preview", "catani.motion_refresh", "catani.motion_info"} <= set(browser["operators"]), browser["operators"]
# 아직 받지 않은 모션은 그림 대신 안내만 나온다.
assert not settings.motions[settings.motion_active].available
assert browser["icons"] == [], browser["icons"]

# 받아 둔 BVH는 표본 포즈 그림을 만들어 팝업에 건다.
temporary = tempfile.TemporaryDirectory(prefix="catani-ui-contract-")
library = Path(temporary.name)
(library / "wave.bvh").write_text("""HIERARCHY
ROOT Hips
{
    OFFSET 0.00 0.00 0.00
    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
    JOINT Spine
    {
        OFFSET 0.00 4.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
            OFFSET 0.00 4.00 0.00
        }
    }
}
MOTION
Frames: 3
Frame Time: 0.0416667
0.00 12.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00
0.00 12.00 0.00 0.00 0.00 0.00 -25.00 0.00 0.00
0.00 12.00 0.00 0.00 0.00 0.00 -45.00 0.00 0.00
""", encoding="utf-8")
settings.motion_library_path = str(library)
settings.local_only = True
addon.refresh(bpy.context.scene)
assert len(settings.motions) == 1, [item.name for item in settings.motions]
settings.motion_active = 0
browser = record(addon.CATANI_OT_motion_browser.draw, bpy.context)
assert len(browser["icons"]) == 3, browser["icons"]
# --background에서는 아이콘 ID가 발급되지 않으므로 그림 자체를 확인한다.
preview = addon._previews[f"{settings.motions[0].identifier}:0"]
assert tuple(preview.image_size) == (addon.motion_preview.THUMB_SIZE,) * 2, tuple(preview.image_size)
assert any(list(preview.image_pixels_float)[3::4]), "표본 포즈 그림이 비었습니다"
settings.local_only = False
settings.motion_library_path = ""

addon.unregister()
addon.register()
print("CATANI_PASS 주 패널 단순화·모션 샘플 팝업·표본 포즈·재등록")
