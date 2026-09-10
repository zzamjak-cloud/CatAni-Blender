"""CatAni: 공개 모션을 검색하고 캐릭터에 바로 적용하는 Extension."""

import math
import textwrap

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import engine, retarget
from .core import MotionSpec
from .motion_downloader import DownloadJob
from .motion_import import import_asset
from .motion_library import MotionAsset, browse, bundled_library_path, normalize_tags
from .source_catalog import get_source

# {"download": DownloadJob, "scene": Scene, "apply": bool, "asset": str}
_job = None


def user_library_path():
    """다운로드 기본 위치. 설치된 애드온 폴더는 읽기 전용일 수 있어 쓰지 않는다."""
    try:
        return bpy.utils.user_resource("DATAFILES", path="catani/motions", create=False)
    except Exception:
        return str(bundled_library_path())


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _lines(layout, text, width=34):
    for line in textwrap.wrap(text, width) or [""]:
        layout.label(text=line)


def _fill(item, asset):
    item.identifier = asset.identifier
    item.name = asset.name
    item.path = asset.path
    item.file_type = asset.file_type
    item.description = asset.description
    item.tags = ", ".join(asset.tags)
    item.source_name = asset.source_name
    item.source_url = asset.source_url
    item.license_note = asset.license_note
    item.license_url = asset.license_url
    item.download_url = asset.download_url
    item.sha256 = asset.sha256
    item.blob_sha1 = asset.blob_sha1
    item.source_id = asset.source_id
    item.size_bytes = min(asset.size_bytes, 2**31 - 1)
    item.available = asset.available


def refresh(scene, keep=""):
    """검색 결과로 목록을 다시 채우고 선택을 유지한다."""
    settings = scene.catani_settings
    wanted = keep or (settings.motions[settings.motion_active].identifier if 0 <= settings.motion_active < len(settings.motions) else "")
    try:
        assets = browse(bpy.path.abspath(settings.motion_library_path), settings.motion_query,
                        extra=[str(bundled_library_path())])
    except (ValueError, OSError) as error:
        settings.motions.clear()
        settings.motion_status = str(error)[:250]
        return []
    settings.motions.clear()
    for asset in assets:
        _fill(settings.motions.add(), asset)
    settings.motion_active = next((index for index, asset in enumerate(assets) if asset.identifier == wanted), 0)
    local = sum(1 for asset in assets if asset.available)
    settings.motion_status = f"{len(assets)}개 · 받아둔 모션 {local}개" if assets else "검색 결과가 없습니다. 검색어를 지우거나 상세에서 모션 폴더를 확인하세요."
    return assets


def _on_search(self, _context):
    refresh(self.id_data)


def _asset(item):
    """UI 목록 항목을 가져오기·리포트가 쓰는 MotionAsset으로 되돌린다."""
    return MotionAsset(
        identifier=item.identifier, name=item.name, path=item.path, file_type=item.file_type,
        tags=normalize_tags(item.tags), description=item.description,
        source_name=item.source_name, source_url=item.source_url,
        license_note=item.license_note, license_url=item.license_url,
        download_url=item.download_url, sha256=item.sha256, blob_sha1=item.blob_sha1,
        source_id=item.source_id, size_bytes=item.size_bytes, available=item.available,
    )


def _selected(settings):
    if not 0 <= settings.motion_active < len(settings.motions):
        raise ValueError("목록에서 적용할 모션을 선택하세요.")
    return settings.motions[settings.motion_active]


def _target(context, settings):
    target = settings.target_armature or (context.active_object if context.active_object and context.active_object.type == "ARMATURE" else None)
    if target is None:
        raise ValueError("애니메이션을 적용할 캐릭터 아마추어를 대상으로 지정하세요.")
    if target.get("catani_motion_source"):
        raise ValueError("가져온 모션 원본 리그가 아니라 캐릭터 아마추어를 대상으로 지정하세요.")
    if target.name not in context.view_layer.objects:
        raise ValueError("대상 캐릭터가 현재 뷰 레이어에 없습니다.")
    return target


def _enter_object_mode(context):
    """포즈 모드에서 눌러도 되도록 오브젝트 모드로 잠시 내려간다."""
    previous = context.mode
    if previous == "OBJECT":
        return None
    if not bpy.ops.object.mode_set.poll():
        raise ValueError("오브젝트 모드로 전환할 수 없습니다. 모드를 직접 바꾼 뒤 다시 시도하세요.")
    bpy.ops.object.mode_set(mode="OBJECT")
    return "POSE" if previous.startswith("POSE") else "EDIT" if previous.startswith("EDIT") else None


def _leave_object_mode(mode):
    if mode and bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode=mode)


def _armature_poll(_self, obj):
    return obj.type == "ARMATURE" and not obj.get("catani_motion_source")


def _stop_timer():
    if bpy.app.timers.is_registered(_poll_download):
        bpy.app.timers.unregister(_poll_download)


def _start_download(context, source_id, apply_after):
    global _job
    settings = context.scene.catani_settings
    if not settings.motion_library_path.strip():
        raise ValueError("내려받을 모션 폴더를 상세 설정에서 지정하세요.")
    entry = get_source(source_id)
    _job = {"download": DownloadJob(entry, bpy.path.abspath(settings.motion_library_path)), "scene": context.scene, "apply": apply_after, "path": entry.local_path}
    settings.download_progress = 0.0
    settings.download_status = f"{entry.name} 다운로드 준비 중"
    _stop_timer()
    bpy.app.timers.register(_poll_download, first_interval=0.2)


def _poll_download():
    global _job
    if _job is None:
        return None
    job = _job["download"]
    try:
        settings = _job["scene"].catani_settings
        settings.download_status = job.status
        settings.download_progress = job.progress
        if not job.done:
            _redraw()
            return 0.2
        follow_up = _job["apply"] and not job.error
        result = str(job.result) if job.result else ""
        _job = None
        if job.error:
            settings.motion_status = job.error[:250]
        else:
            settings.motion_query = ""
            assets = refresh(settings.id_data)
            settings.motion_active = next((index for index, asset in enumerate(assets) if asset.path == result), settings.motion_active)
            settings.download_status = "다운로드와 체크섬 검증 완료"
            settings.motion_status = "다운로드·체크섬 검증 완료 · " + settings.motion_status
        _redraw()
        if follow_up:
            bpy.ops.catani.motion_apply("EXEC_DEFAULT")
        return None
    except Exception as error:
        job.cancel()
        _job = None
        print("CatAni 다운로드 처리 실패:", error)
        _redraw()
        return None


@bpy.app.handlers.persistent
def _stop_download(_unused=None):
    global _job
    if _job is not None:
        _job["download"].cancel()
    _job = None
    _stop_timer()


def _refresh_all():
    for scene in bpy.data.scenes:
        if hasattr(scene, "catani_settings"):
            refresh(scene)
    _redraw()
    return None


@bpy.app.handlers.persistent
def _refresh_after_load(_unused=None):
    if not bpy.app.timers.is_registered(_refresh_all):
        bpy.app.timers.register(_refresh_all, first_interval=0.05)


class CatAniMotionItem(bpy.types.PropertyGroup):
    """목록의 한 줄. 아직 받지 않은 공개 모션은 available=False다."""

    identifier: StringProperty()
    name: StringProperty()
    path: StringProperty()
    file_type: StringProperty()
    description: StringProperty()
    tags: StringProperty()
    source_name: StringProperty()
    source_url: StringProperty()
    license_note: StringProperty()
    license_url: StringProperty()
    download_url: StringProperty()
    sha256: StringProperty()
    blob_sha1: StringProperty()
    source_id: StringProperty()
    size_bytes: IntProperty()
    available: BoolProperty(default=True)


class CatAniSettings(bpy.types.PropertyGroup):
    motion_query: StringProperty(name="검색", description="모션 이름·설명·태그에서 모든 단어를 포함하는 항목만 남깁니다", default="", update=_on_search)
    motions: CollectionProperty(type=CatAniMotionItem)
    motion_active: IntProperty(name="선택 모션", default=0)
    target_armature: PointerProperty(name="대상", description="애니메이션을 적용할 캐릭터 아마추어", type=bpy.types.Object, poll=_armature_poll)
    motion_status: StringProperty(name="상태", default="모션을 검색하고 대상 캐릭터를 지정한 뒤 적용하세요.")
    apply_report: StringProperty(name="적용 리포트", default="")
    motion_library_path: StringProperty(name="모션 폴더", description="공개 모션을 내려받아 둘 폴더. 애드온에 동봉한 예제는 항상 함께 검색됩니다",
                                       subtype="DIR_PATH", default=user_library_path(), update=_on_search)
    frame_step: IntProperty(name="프레임 간격", description="1이면 모든 프레임에 키를 만듭니다", default=1, min=1, max=10)
    smooth_window: IntProperty(name="노이즈 완화(프레임)",
                               description="모캡 흔들림을 이 프레임 수의 창으로 걷어냅니다. 노이즈를 남기면 키를 솎아내도 줄지 않습니다. 0이나 1이면 완화하지 않습니다",
                               default=retarget.DEFAULT_SMOOTH, min=0, max=31)
    simplify_error: FloatProperty(name="곡선 간소화 오차",
                                  description="이 각도 안에서 키를 솎아내고 베지어 곡선으로 만듭니다. 값이 크면 키가 적어 손으로 고치기 쉽고, 0이면 모든 프레임에 키를 남깁니다",
                                  default=math.radians(retarget.DEFAULT_SIMPLIFY), min=0.0, max=math.radians(5.0), unit="ROTATION")
    use_location: BoolProperty(name="이동 적용", description="엉덩이 이동을 캐릭터 비율에 맞춰 함께 적용합니다", default=True)
    ground_contact: BoolProperty(name="바닥 관통 보정", description="발이 바닥 아래로 내려가는 프레임에서 몸 전체를 필요한 만큼만 올립니다", default=True)
    use_ik: BoolProperty(name="IK로 전환",
                         description="캐릭터 리그에 IK 컨스트레인트가 있으면 팔다리를 IK 컨트롤 본으로 굽습니다. 체인·폴 구성은 리그의 컨스트레인트에서 직접 읽습니다",
                         default=True)
    hide_source: BoolProperty(name="모션 원본 리그 숨기기", default=True)
    download_status: StringProperty(name="다운로드", default="")
    download_progress: FloatProperty(name="진행", min=0.0, max=1.0, subtype="FACTOR")
    recipe: EnumProperty(name="보조 동작", items=[("idle", "대기 / 호흡", "Player 샘플의 절차 동작"), ("wave", "단순 손 흔들기", "비교용 FK 동작")], default="idle")
    side: EnumProperty(name="손", items=[("R", "오른손", "캐릭터 오른손"), ("L", "왼손", "캐릭터 왼손")], default="R")
    duration: FloatProperty(name="전체 길이(초)", default=2.0, min=0.5, max=10.0)
    intensity: FloatProperty(name="동작 강도", default=0.7, min=0.1, max=1.0)
    repeat: IntProperty(name="구간 내 반복", default=2, min=1, max=8)


class CATANI_UL_motions(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_prop, _index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="ARMATURE_DATA" if item.available else "IMPORT")
        badge = row.row()
        badge.alignment = "RIGHT"
        badge.label(text=item.file_type.upper() if item.available else f"받기 {item.size_bytes / 1024:.0f}KB")


class CATANI_OT_motion_refresh(bpy.types.Operator):
    bl_idname = "catani.motion_refresh"
    bl_label = "목록 다시 읽기"
    bl_description = "모션 폴더를 다시 훑어 목록을 갱신합니다"

    def execute(self, context):
        refresh(context.scene)
        return {"FINISHED"}


class CATANI_OT_motion_apply(bpy.types.Operator):
    bl_idname = "catani.motion_apply"
    bl_label = "적용"
    bl_description = "선택한 모션을 필요하면 내려받고 대상 캐릭터에 애니메이션을 굽습니다"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _job is None and engine.get_session() is None

    def execute(self, context):
        settings = context.scene.catani_settings
        restore = None
        try:
            item = _selected(settings)
            target = _target(context, settings)
            if not item.available:
                _start_download(context, item.source_id, apply_after=True)
                return {"FINISHED"}
            restore = _enter_object_mode(context)
            self._apply(context, settings, item, target)
        except Exception as error:
            settings.motion_status = str(error)[:250]
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            _leave_object_mode(restore)
        return {"FINISHED"}

    def _apply(self, context, settings, item, target):
        asset = _asset(item)
        source = _existing_source(asset)
        created = []
        collection = None
        if source is None:
            created, collection = import_asset(context, asset)
            source = next(obj for obj in created if obj.type == "ARMATURE")
        family = [source, *source.children_recursive]
        for obj in family:
            obj.hide_set(False)
        try:
            report = retarget.apply_motion(context, source, target, step=settings.frame_step, use_location=settings.use_location,
                                           ground=settings.ground_contact, simplify=math.degrees(settings.simplify_error),
                                           smooth=settings.smooth_window, use_ik=settings.use_ik, name=f"CatAni {item.name}")
        except Exception:
            if collection is not None:
                bpy.data.batch_remove(ids=[*created, collection])
            raise
        if collection is not None:
            collection["catani_motion_target"] = target.name
        if settings.hide_source:
            for obj in family:
                obj.hide_set(True)
                obj.hide_render = True
        for obj in context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        settings.apply_report = "\n".join(retarget.format_report(asset, report))
        warning = " · 매핑된 부위가 적어 상세에서 본 이름을 확인하세요" if report["coverage"] < 0.6 else ""
        saved = ""
        if report["simplify"] and report["dense_keyframes"]:
            saved = f"(-{(1.0 - report['keyframes'] / report['dense_keyframes']) * 100:.0f}%)"
        settings.motion_status = (
            f"적용됨 · 부위 {len(report['pairs'])}/{len(retarget.SLOT_ORDER)} · "
            f"{report['frame_start']}~{report['frame_end']}f · 키 {report['keyframes']:,}개{saved} · "
            f"방향 오차 {report['max_direction_error']:.2f}°{warning}"
        )
        self.report({"WARNING"} if warning else {"INFO"}, settings.motion_status)


def _existing_source(asset):
    """같은 파일을 이미 가져왔다면 다시 가져오지 않고 재사용한다."""
    if not asset.path:
        return None
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE" or obj.get("catani_motion_source") != asset.path:
            continue
        if obj.name in bpy.context.view_layer.objects and obj.animation_data and obj.animation_data.action:
            return obj
    return None


class CATANI_OT_motion_import(bpy.types.Operator):
    bl_idname = "catani.motion_import"
    bl_label = "모션 원본만 가져오기"
    bl_description = "리타게팅 없이 모션 원본 리그와 Action만 별도 컬렉션에 가져옵니다"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _job is None and engine.get_session() is None

    def execute(self, context):
        settings = context.scene.catani_settings
        restore = None
        try:
            item = _selected(settings)
            if not item.available:
                raise ValueError("먼저 적용 버튼으로 공개 모션을 내려받으세요.")
            restore = _enter_object_mode(context)
            created, _collection = import_asset(context, _asset(item))
            settings.motion_status = f"{item.name} 원본 {len(created)}개 가져오기 완료 · 리타게팅은 하지 않았습니다."
        except Exception as error:
            settings.motion_status = str(error)[:250]
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            _leave_object_mode(restore)
        return {"FINISHED"}


class CATANI_OT_motion_download(bpy.types.Operator):
    bl_idname = "catani.motion_download"
    bl_label = "받기만 하기"
    bl_description = "선택한 공개 모션 파일을 내려받고 체크섬을 검증합니다"
    source_id: StringProperty(options={"HIDDEN"}, default="")

    @classmethod
    def poll(cls, context):
        return _job is None

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            source_id = self.source_id or _selected(settings).source_id
            if not source_id:
                raise ValueError("이미 받아 둔 모션입니다. 목록에서 아직 받지 않은 공개 모션을 선택하세요.")
            _start_download(context, source_id, apply_after=False)
        except Exception as error:
            _stop_download()
            settings.motion_status = str(error)[:250]
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_download_cancel(bpy.types.Operator):
    bl_idname = "catani.download_cancel"
    bl_label = "다운로드 취소"

    @classmethod
    def poll(cls, context):
        return _job is not None

    def execute(self, context):
        _job["download"].cancel()
        context.scene.catani_settings.download_status = "다운로드 취소 중"
        return {"FINISHED"}


class CATANI_OT_motion_info(bpy.types.Operator):
    bl_idname = "catani.motion_info"
    bl_label = "출처 · 이용 조건"
    bl_description = "선택 모션의 실제 다운로드 주소, 체크섬, 출처와 이용 조건을 봅니다"

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        try:
            item = _selected(context.scene.catani_settings)
        except ValueError as error:
            layout.label(text=str(error), icon="ERROR")
            return
        layout.label(text=item.name, icon="ARMATURE_DATA" if item.available else "IMPORT")
        column = layout.column(align=True)
        _lines(column, item.description or "설명 없음", 78)
        column.separator()
        column.label(text=f"태그: {item.tags or '없음'}")
        column.label(text=f"형식: {item.file_type.upper()} · {item.size_bytes / 1024:.0f} KB")
        column.label(text=f"로컬 파일: {item.path or '아직 받지 않음 · 적용하면 자동으로 내려받습니다'}")
        if item.download_url:
            column.label(text="다운로드 주소")
            _lines(column, item.download_url, 78)
        if item.blob_sha1:
            column.label(text="git blob SHA-1 (고정 리비전 대조용)")
            _lines(column, item.blob_sha1, 78)
        if item.sha256:
            column.label(text="SHA-256")
            _lines(column, item.sha256, 78)
        column.separator()
        column.label(text=f"출처: {item.source_name or '사용자가 직접 넣은 로컬 파일'}", icon="WORLD")
        _lines(column, item.license_note or "이용 조건 정보가 없습니다. 제공처에서 직접 확인하세요.", 78)
        row = layout.row(align=True)
        if item.source_url:
            row.operator("wm.url_open", text="출처 페이지", icon="URL").url = item.source_url
        if item.license_url:
            row.operator("wm.url_open", text="이용 조건 원문", icon="URL").url = item.license_url

    def execute(self, _context):
        return {"FINISHED"}


class CATANI_OT_settings(bpy.types.Operator):
    bl_idname = "catani.settings"
    bl_label = "상세 설정 · 적용 리포트"
    bl_description = "모션 폴더, 굽기 옵션과 마지막 적용 결과를 봅니다"

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        column = layout.column()
        column.prop(settings, "motion_library_path")
        column.prop(settings, "frame_step")
        column.prop(settings, "smooth_window")
        column.prop(settings, "simplify_error")
        column.prop(settings, "use_location")
        column.prop(settings, "ground_contact")
        column.prop(settings, "use_ik")
        column.prop(settings, "hide_source")
        row = column.row(align=True)
        row.operator("catani.motion_refresh", icon="FILE_REFRESH")
        row.operator("catani.motion_download", icon="IMPORT").source_id = ""
        row.operator("catani.motion_import", icon="OUTLINER_OB_ARMATURE")
        layout.separator()
        box = layout.box()
        box.label(text="마지막 적용 리포트", icon="INFO")
        if not settings.apply_report:
            box.label(text="아직 적용한 모션이 없습니다.")
            return
        report = box.column(align=True)
        for line in settings.apply_report.splitlines():
            report.label(text=line)

    def execute(self, _context):
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


class CATANI_PT_main(bpy.types.Panel):
    bl_label = "CatAni · 모션"
    bl_idname = "CATANI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CatAni"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        layout.prop(settings, "motion_query", text="", icon="VIEWZOOM")
        layout.template_list("CATANI_UL_motions", "", settings, "motions", settings, "motion_active", rows=6)
        layout.prop(settings, "target_armature", text="대상")
        button = layout.row()
        button.scale_y = 1.6
        button.operator("catani.motion_apply", text="적용", icon="PLAY")
        if _job is not None:
            layout.progress(factor=settings.download_progress, text=settings.download_status[:48])
            layout.operator("catani.download_cancel", icon="X")
        _lines(layout, settings.motion_status)
        row = layout.row(align=True)
        row.operator("catani.motion_info", text="출처", icon="INFO")
        row.operator("catani.settings", text="상세", icon="PREFERENCES")


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


_classes = (
    CatAniMotionItem, CatAniSettings, CATANI_UL_motions,
    CATANI_OT_motion_refresh, CATANI_OT_motion_apply, CATANI_OT_motion_import,
    CATANI_OT_motion_download, CATANI_OT_download_cancel,
    CATANI_OT_motion_info, CATANI_OT_settings,
    CATANI_OT_inspect, CATANI_OT_preview, CATANI_OT_confirm, CATANI_OT_cancel,
    CATANI_PT_main, CATANI_PT_procedural,
)

_handlers = (
    (bpy.app.handlers.load_pre, _stop_download),
    (bpy.app.handlers.load_pre, engine.clear_before_load),
    (bpy.app.handlers.load_post, _refresh_after_load),
    (bpy.app.handlers.save_pre, engine.cancel_before_save),
    (bpy.app.handlers.undo_pre, engine.cancel_before_save),
    (bpy.app.handlers.redo_pre, engine.cancel_before_save),
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.catani_settings = PointerProperty(type=CatAniSettings)
    for handlers, callback in _handlers:
        handlers.append(callback)
    _refresh_after_load()


def unregister():
    _stop_download()
    if bpy.app.timers.is_registered(_refresh_all):
        bpy.app.timers.unregister(_refresh_all)
    engine.cancel_preview(bpy.context)
    for handlers, callback in _handlers:
        if callback in handlers:
            handlers.remove(callback)
    if hasattr(bpy.types.Scene, "catani_settings"):
        del bpy.types.Scene.catani_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
