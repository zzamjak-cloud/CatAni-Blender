"""CatAni: 실제 모션 데이터를 내려받고 검색하는 로컬 라이브러리."""

import textwrap
import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from .core import MotionSpec
from . import engine
from .motion_library import assets_from_json, assets_to_json, default_library_path, scan_library, search_assets
from .motion_import import import_asset
from .source_catalog import CATALOG, get_source
from .motion_downloader import DownloadJob

_download_job = None
_download_scene = None


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _refresh_library(settings):
    assets = search_assets(scan_library(bpy.path.abspath(settings.motion_library_path)), settings.motion_query)
    settings.motion_index_json = assets_to_json(assets)
    if not any(asset.identifier == settings.motion_selected_id for asset in assets):
        settings.motion_selected_id = assets[0].identifier if assets else ""
    settings.motion_status = f"검색 결과 {len(assets)}개" if assets else "공개 모션을 받거나 BVH/FBX 폴더를 선택하세요."
    return assets


def _poll_download():
    global _download_job, _download_scene
    if _download_job is None:
        return None
    try:
        settings = _download_scene.catani_settings
        settings.download_status = _download_job.status
        settings.download_progress = _download_job.progress
        if _download_job.done:
            if not _download_job.error:
                settings.motion_query = ""
                assets = _refresh_library(settings)
                selected = next((a for a in assets if a.path == str(_download_job.result)), None)
                if selected:
                    settings.motion_selected_id = selected.identifier
                settings.download_status = "다운로드·인덱싱 완료 · 선택 모션을 가져오세요."
            _download_job = None
            _download_scene = None
    except Exception as error:
        if _download_job:
            _download_job.cancel()
        try:
            _download_scene.catani_settings.download_status = str(error)[:250]
        except (AttributeError, ReferenceError):
            pass
        _download_job = None
        _download_scene = None
    _redraw()
    return 0.2 if _download_job else None


@bpy.app.handlers.persistent
def _stop_download(_unused=None):
    global _download_job, _download_scene
    if _download_job:
        _download_job.cancel()
    _download_job = None
    _download_scene = None
    if bpy.app.timers.is_registered(_poll_download):
        bpy.app.timers.unregister(_poll_download)


class CatAniSettings(bpy.types.PropertyGroup):
    motion_library_path: StringProperty(name="모션 폴더", subtype="DIR_PATH", default=str(default_library_path()))
    motion_query: StringProperty(name="검색", default="")
    motion_index_json: StringProperty(name="모션 인덱스", default="[]", options={"HIDDEN"})
    motion_selected_id: StringProperty(name="선택 모션", default="", options={"HIDDEN"})
    motion_status: StringProperty(name="모션 상태", default="공개 모션을 받거나 BVH/FBX 폴더를 선택하세요.")
    download_status: StringProperty(name="다운로드 상태", default="공개 모션 파일 직접 다운로드 · API 키 불필요")
    download_progress: FloatProperty(name="다운로드 진행", min=0.0, max=1.0, subtype="FACTOR")
    recipe: EnumProperty(name="보조 동작", items=[("idle", "대기 / 호흡", "Player 샘플의 절차 동작"), ("wave", "단순 손 흔들기", "비교용 FK 동작")], default="idle")
    side: EnumProperty(name="손", items=[("R", "오른손", "캐릭터 오른손"), ("L", "왼손", "캐릭터 왼손")], default="R")
    duration: FloatProperty(name="전체 길이(초)", default=2.0, min=0.5, max=10.0)
    intensity: FloatProperty(name="동작 강도", default=0.7, min=0.1, max=1.0)
    repeat: IntProperty(name="구간 내 반복", default=2, min=1, max=8)


class CATANI_OT_motion_download(bpy.types.Operator):
    bl_idname = "catani.motion_download"
    bl_label = "공개 모션 받기"
    bl_description = "출처와 이용 조건이 표시된 실제 CMU BVH를 내려받습니다"
    source_id: StringProperty(options={"HIDDEN"}, default=CATALOG[0].id)

    @classmethod
    def poll(cls, context):
        return _download_job is None

    def execute(self, context):
        global _download_job, _download_scene
        settings = context.scene.catani_settings
        try:
            source = get_source(self.source_id)
            if not settings.motion_library_path.strip():
                raise ValueError("다운로드할 모션 폴더를 선택하세요.")
            _download_scene = context.scene
            settings.download_progress = 0.0
            settings.download_status = f"{source.name} 다운로드 준비 중"
            _download_job = DownloadJob(source, bpy.path.abspath(settings.motion_library_path))
            bpy.app.timers.register(_poll_download, first_interval=0.2)
        except Exception as error:
            _stop_download()
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_motion_download_cancel(bpy.types.Operator):
    bl_idname = "catani.motion_download_cancel"
    bl_label = "다운로드 취소"

    @classmethod
    def poll(cls, context):
        return _download_job is not None

    def execute(self, context):
        _download_job.cancel()
        context.scene.catani_settings.download_status = "다운로드 취소 중"
        return {"FINISHED"}


class CATANI_OT_motion_refresh(bpy.types.Operator):
    bl_idname = "catani.motion_refresh"
    bl_label = "모션 목록 갱신"

    def execute(self, context):
        try:
            _refresh_library(context.scene.catani_settings)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            context.scene.catani_settings.motion_status = str(error)[:250]
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_motion_pick(bpy.types.Operator):
    bl_idname = "catani.motion_pick"
    bl_label = "모션 선택"
    asset_id: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            if not any(a.identifier == self.asset_id for a in assets_from_json(settings.motion_index_json)):
                raise ValueError("선택한 모션이 현재 검색 결과에 없습니다.")
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.motion_selected_id = self.asset_id
        return {"FINISHED"}


class CATANI_OT_motion_import(bpy.types.Operator):
    bl_idname = "catani.motion_import"
    bl_label = "선택 모션 가져오기"
    bl_description = "모션 원본 리그를 별도 컬렉션에 가져옵니다. 캐릭터 자동 리타게팅은 포함하지 않습니다"

    @classmethod
    def poll(cls, context):
        return engine.get_session() is None and context.mode == "OBJECT"

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            assets = assets_from_json(settings.motion_index_json)
            asset = next((a for a in assets if a.identifier == settings.motion_selected_id), None)
            if asset is None:
                raise ValueError("가져올 모션을 먼저 선택하세요.")
            import_asset(context, asset)
            settings.motion_status = f"{asset.name} 가져오기 완료 · 원본 리그의 Action을 재생하세요."
        except Exception as error:
            self.report({"ERROR"}, str(error))
            settings.motion_status = str(error)[:250]
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_inspect(bpy.types.Operator):
    bl_idname = "catani.inspect_rig"
    bl_label = "선택 리그 검사"

    def execute(self, context):
        errors = engine.inspect_rig(context.active_object)
        self.report({"ERROR"} if errors else {"INFO"}, " / ".join(errors) if errors else "Player v1 보조 동작을 사용할 수 있습니다.")
        return {"CANCELLED"} if errors else {"FINISHED"}


class CATANI_OT_preview(bpy.types.Operator):
    bl_idname = "catani.preview"
    bl_label = "보조 동작 미리보기"

    @classmethod
    def poll(cls, context):
        return engine.get_session() is None and context.mode == "OBJECT" and context.active_object is not None and context.active_object.type == "ARMATURE"

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            spec = MotionSpec(recipe=settings.recipe, side=settings.side, duration=settings.duration, intensity=settings.intensity, repeat=settings.repeat, fps=context.scene.render.fps / context.scene.render.fps_base)
            engine.begin_preview(context, context.active_object, spec)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_confirm(bpy.types.Operator):
    bl_idname = "catani.confirm"
    bl_label = "복사본으로 확정"

    @classmethod
    def poll(cls, context):
        return engine.get_session() is not None and context.mode == "OBJECT"

    def execute(self, context):
        action = engine.confirm_preview(context)
        self.report({"INFO"}, f"{action.name} 확정. 원본은 Outliner에서 다시 표시할 수 있습니다.")
        return {"FINISHED"}


class CATANI_OT_cancel(bpy.types.Operator):
    bl_idname = "catani.cancel"
    bl_label = "미리보기 취소"

    @classmethod
    def poll(cls, context):
        return engine.get_session() is not None and context.mode == "OBJECT"

    def execute(self, context):
        engine.cancel_preview(context)
        return {"FINISHED"}


def _label_lines(layout, text):
    for line in textwrap.wrap(text, 32):
        layout.label(text=line)


class CATANI_PT_main(bpy.types.Panel):
    bl_label = "CatAni · 모션 라이브러리"
    bl_idname = "CATANI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CatAni"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        path_row = layout.row()
        path_row.enabled = _download_job is None
        path_row.prop(settings, "motion_library_path")
        source_box = layout.box()
        source_box.label(text="공개 모션 받기 · CMU BVH", icon="IMPORT")
        source_box.label(text="실제 캡처 데이터 · API 키 불필요")
        for source in CATALOG:
            row = source_box.row(align=True)
            row.label(text=source.name)
            row.operator("catani.motion_download", text=f"받기 · {source.size_bytes / 1024:.0f} KB").source_id = source.id
        _label_lines(source_box, CATALOG[0].source_name)
        _label_lines(source_box, CATALOG[0].license_note)
        source_box.operator("wm.url_open", text="CMU 출처·이용 조건 원문", icon="URL").url = CATALOG[0].license_url
        _label_lines(source_box, settings.download_status)
        if _download_job is not None:
            source_box.progress(factor=settings.download_progress, text="다운로드")
            source_box.operator("catani.motion_download_cancel", icon="X")
        library = layout.box()
        library.label(text="내 모션 · BVH / FBX", icon="FILE_FOLDER")
        library.prop(settings, "motion_query")
        library.operator("catani.motion_refresh", icon="FILE_REFRESH")
        try:
            assets = assets_from_json(settings.motion_index_json)
        except ValueError:
            assets = []
        selected = next((a for a in assets if a.identifier == settings.motion_selected_id), None)
        for asset in assets[:10]:
            row = library.row(align=True)
            icon = "RADIOBUT_ON" if asset.identifier == settings.motion_selected_id else "RADIOBUT_OFF"
            row.operator("catani.motion_pick", text=asset.name[:32], icon=icon).asset_id = asset.identifier
        if len(assets) > 10:
            library.label(text=f"외 {len(assets) - 10}개 · 검색어를 좁히세요")
        if selected:
            _label_lines(library, selected.description)
            _label_lines(library, selected.source_name or "사용자가 등록한 로컬 파일")
            _label_lines(library, selected.license_note or "이용 조건 정보 없음 · 제공처에서 확인하세요")
            if selected.source_url:
                library.operator("wm.url_open", text="선택 모션 출처", icon="URL").url = selected.source_url
        library.operator("catani.motion_import", icon="IMPORT")
        _label_lines(library, settings.motion_status)
        layout.label(text="가져오기: 모션 원본 리그와 Action")
        layout.label(text="캐릭터 자동 리타게팅은 다음 단계")


class CATANI_PT_procedural(bpy.types.Panel):
    bl_label = "보조 · 절차 동작 비교"
    bl_idname = "CATANI_PT_procedural"
    bl_parent_id = "CATANI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CatAni"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        layout.label(text="Player v1 샘플 리그 전용")
        if engine.get_session():
            layout.operator("catani.confirm", icon="CHECKMARK")
            layout.operator("catani.cancel", icon="X")
            layout.label(text="확정하면 원본은 숨김으로 유지")
            return
        layout.operator("catani.inspect_rig")
        layout.prop(settings, "recipe")
        if settings.recipe == "wave":
            layout.prop(settings, "side", expand=True)
        for name in ("duration", "intensity", "repeat"):
            layout.prop(settings, name)
        layout.operator("catani.preview", icon="PLAY")


_classes = (CatAniSettings, CATANI_OT_motion_download, CATANI_OT_motion_download_cancel, CATANI_OT_motion_refresh, CATANI_OT_motion_pick, CATANI_OT_motion_import, CATANI_OT_inspect, CATANI_OT_preview, CATANI_OT_confirm, CATANI_OT_cancel, CATANI_PT_main, CATANI_PT_procedural)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.catani_settings = PointerProperty(type=CatAniSettings)
    bpy.app.handlers.load_pre.append(_stop_download)
    bpy.app.handlers.load_pre.append(engine.clear_before_load)
    bpy.app.handlers.save_pre.append(engine.cancel_before_save)
    bpy.app.handlers.undo_pre.append(engine.cancel_before_save)
    bpy.app.handlers.redo_pre.append(engine.cancel_before_save)


def unregister():
    _stop_download()
    if _stop_download in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_stop_download)
    engine.cancel_preview(bpy.context)
    for handlers, callback in ((bpy.app.handlers.load_pre, engine.clear_before_load), (bpy.app.handlers.save_pre, engine.cancel_before_save), (bpy.app.handlers.undo_pre, engine.cancel_before_save), (bpy.app.handlers.redo_pre, engine.cancel_before_save)):
        if callback in handlers:
            handlers.remove(callback)
    if hasattr(bpy.types.Scene, "catani_settings"):
        del bpy.types.Scene.catani_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
