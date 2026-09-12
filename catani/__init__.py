"""CatAni: 공개 모션을 검색하고 캐릭터에 바로 적용하는 Extension."""

import math
import os
from pathlib import Path
import shutil
import tempfile
import textwrap
import time

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import retarget
from .motion_downloader import DownloadJob
from .motion_import import import_asset
from .motion_library import (MotionAsset, browse, bundled_library_path, merge_manifest, normalize_tags, read_length,
                              read_manifest, update_manifest)
from .source_catalog import CATEGORIES, get_source

# {"download": DownloadJob, "scene": Scene, "apply": bool, "preview": bool, "path": str}
_job = None

# 목록 길이 표시용 BVH 머리글 캐시. 패널은 자주 다시 그려지므로 mtime으로만 다시 읽는다.
_lengths = {}
_library_counts = {}  # {폴더: (측정 시각, BVH 개수)}
_LIST_ROWS = 18  # 좁은 사이드바에서도 샘플을 한눈에 훑을 수 있는 최소 줄 수
_EDIT_CATEGORY_ITEMS = [(key, label, f"{label}로 분류합니다")
                        for key, label in sorted(CATEGORIES.items(), key=lambda pair: pair[1])]
_CATEGORY_ITEMS = [("ALL", "전체 카테고리", "카테고리로 거르지 않습니다")] + [
    (key, label, f"{label} 모션만 봅니다") for key, label in sorted(CATEGORIES.items(), key=lambda pair: pair[1])
]
_FALLBACK_CATEGORY = next((key for key, *_ in _EDIT_CATEGORY_ITEMS if key == "misc"), _EDIT_CATEGORY_ITEMS[0][0])


def user_library_path():
    """다운로드 기본 위치. 설치된 애드온 폴더는 읽기 전용일 수 있어 쓰지 않는다."""
    try:
        return bpy.utils.user_resource("DATAFILES", path="catani/motions", create=False)
    except Exception:
        return str(bundled_library_path())


def _library_root(settings):
    """지금 쓰는 모션 폴더. 비워 두면 기본 사용자 폴더를 본다."""
    raw = (settings.motion_library_path or "").strip()
    return Path(bpy.path.abspath(raw)) if raw else Path(user_library_path())


def _library_count(root):
    """팝업은 자주 다시 그려지므로 폴더 훑기를 잠깐 캐시한다."""
    key = str(root)
    stamp = time.monotonic()
    cached = _library_counts.get(key)
    if cached is not None and stamp - cached[0] < 3.0:
        return cached[1]
    try:
        count = sum(1 for _ in root.rglob("*.bvh")) if root.is_dir() else 0
    except OSError:
        count = 0
    _library_counts[key] = (stamp, count)
    return count


def _sibling_libraries(current):
    """Blender 버전을 올리면 datafiles 경로가 바뀐다. 이전 버전 폴더에 남은 모션을 찾아 준다."""
    try:
        default = Path(user_library_path())
        versions = default.parents[2]
    except (IndexError, OSError):
        return []
    found = []
    try:
        entries = sorted(versions.iterdir())
    except OSError:
        return []
    for entry in entries:
        candidate = entry / "datafiles" / "catani" / "motions"
        if candidate in (current, default) or not candidate.is_dir():
            continue
        try:
            if next(candidate.rglob("*.bvh"), None) is not None:
                found.append(candidate)
        except OSError:
            continue
    return found


def _import_library(source, target):
    """다른 폴더의 BVH와 인덱스를 현재 모션 폴더로 합친다. 같은 이름의 기존 파일은 건드리지 않는다."""
    copied = skipped = 0
    try:
        catalog = read_manifest(source)
    except ValueError:
        catalog = {}  # 인덱스가 깨졌어도 파일은 옮긴다. 이름은 카탈로그 경로로 복원된다.
    meta = {}
    for path in sorted(source.rglob("*.bvh")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(source)
        key = str(relative).replace("\\", "/")
        entry = catalog.get(key)
        if entry:
            meta[key] = {name: value for name, value in entry.items() if name != "file"}
        destination = target / relative
        if destination.exists():
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".catani-import-", suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
            shutil.copy2(path, temporary)
            os.replace(temporary, destination)
            temporary = None
            copied += 1
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if meta:
        merge_manifest(target, meta)
    return copied, skipped


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
    item.category = asset.category
    item.commercial_use = asset.commercial_use


def refresh(scene, keep=""):
    """검색 결과로 목록을 다시 채우고 선택을 유지한다."""
    settings = scene.catani_settings
    wanted = keep or (settings.motions[settings.motion_active].identifier if 0 <= settings.motion_active < len(settings.motions) else "")
    try:
        assets = browse(bpy.path.abspath(settings.motion_library_path), settings.motion_query,
                        extra=[str(bundled_library_path())],
                        category="" if settings.motion_category == "ALL" else settings.motion_category,
                        local_only=settings.local_only,
                        commercial_only=not settings.include_noncommercial)
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
        category=item.category, commercial_use=item.commercial_use,
    )


def _selected(settings):
    if not 0 <= settings.motion_active < len(settings.motions):
        raise ValueError("목록에서 적용할 모션을 선택하세요.")
    return settings.motions[settings.motion_active]


def _library_roots(settings):
    """목록을 훑는 폴더들. refresh와 같은 순서를 유지한다."""
    roots = []
    for candidate in (settings.motion_library_path, str(bundled_library_path())):
        text = str(candidate).strip()
        if not text:
            continue
        library = Path(bpy.path.abspath(text)).expanduser().resolve()
        if library not in roots:
            roots.append(library)
    return roots


def _library_slot(settings, item):
    """이름을 적어 둘 모션 폴더와 그 안에서의 상대 경로.

    목록은 설정한 모션 폴더와 함께 훑는 폴더를 모두 담으므로, 파일이 실제로
    들어 있는 쪽에 적는다. 두 폴더가 겹치면 더 안쪽을 쓴다.
    """
    if not item.available or not item.path:
        raise ValueError("아직 받지 않은 모션입니다. 받은 뒤에 이름을 바꿀 수 있습니다.")
    path = Path(bpy.path.abspath(item.path)).expanduser().resolve()
    owners = [library for library in _library_roots(settings) if path.is_relative_to(library)]
    if not owners:
        raise ValueError("모션 폴더 밖의 파일은 이름을 바꿀 수 없습니다. 상세 설정에서 폴더를 확인하세요.")
    library = max(owners, key=lambda candidate: len(candidate.parts))
    if not os.access(library, os.W_OK):
        raise ValueError(f"쓸 수 없는 폴더의 모션입니다. 파일을 모션 폴더로 옮긴 뒤 바꾸세요: {library}")
    return library, path.relative_to(library).as_posix()


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


def _viewport(context):
    """재생과 시점 맞춤에 쓸 3D 뷰 영역을 찾는다."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is not None:
                return window, area, region
    return None, None, None


def _play(context, focus=False):
    window, area, region = _viewport(context)
    if area is None:
        return
    with context.temp_override(window=window, screen=window.screen, area=area, region=region):
        if focus:
            try:
                bpy.ops.view3d.view_selected()
            except RuntimeError:
                pass
        if not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()


def _stop_play(context):
    window, area, region = _viewport(context)
    if area is None:
        return
    with context.temp_override(window=window, screen=window.screen, area=area, region=region):
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)


def _release_preview(settings):
    """미리보기 리그를 그대로 쓰기로 했을 때 추적만 끊는다. 오브젝트는 남긴다."""
    settings.preview_active = False
    settings.preview_name = ""
    settings.preview_path = ""
    settings.preview_collection = ""
    settings.preview_reused = ""


def _clear_preview(context):
    """미리보기로 불러온 임시 리그와 프레임 범위를 되돌린다."""
    settings = context.scene.catani_settings
    if not settings.preview_active:
        return
    _stop_play(context)
    collection = bpy.data.collections.get(settings.preview_collection) if settings.preview_collection else None
    if collection is not None:
        victims = [collection]
        for obj in collection.objects:
            victims.append(obj)
            victims.append(obj.data)
            action = obj.animation_data.action if obj.animation_data else None
            if action is not None:
                action.use_fake_user = False
                victims.append(action)
        bpy.data.batch_remove(ids=[item for item in victims if item is not None])
    reused = bpy.data.objects.get(settings.preview_reused) if settings.preview_reused else None
    if reused is not None and settings.preview_hidden:
        # 이미 적용해 숨겨 두었던 원본을 미리보려고 드러냈으므로 다시 숨긴다.
        for obj in [reused, *reused.children_recursive]:
            if obj.name in context.view_layer.objects:
                obj.hide_set(True)
            obj.hide_render = True
    scene = context.scene
    scene.frame_start, scene.frame_end = settings.preview_frame_start, settings.preview_frame_end
    scene.frame_set(min(max(scene.frame_current, scene.frame_start), scene.frame_end))
    _release_preview(settings)


def _stop_timer():
    if bpy.app.timers.is_registered(_poll_download):
        bpy.app.timers.unregister(_poll_download)


def _start_download(context, source_id, apply_after, preview_after=False):
    global _job
    settings = context.scene.catani_settings
    if not settings.motion_library_path.strip():
        raise ValueError("내려받을 모션 폴더를 상세 설정에서 지정하세요.")
    entry = get_source(source_id)
    _job = {"download": DownloadJob(entry, bpy.path.abspath(settings.motion_library_path)), "scene": context.scene,
            "apply": apply_after, "preview": preview_after, "path": entry.local_path}
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
        preview_up = _job["preview"] and not job.error
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
        elif preview_up:
            bpy.ops.catani.motion_preview("EXEC_DEFAULT")
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
        if not hasattr(scene, "catani_settings"):
            continue
        settings = scene.catani_settings
        # 미리보기 도중 저장·불러오기를 하면 임시 리그가 없어도 상태만 남는다.
        if settings.preview_active and bpy.data.collections.get(settings.preview_collection) is None:
            _release_preview(settings)
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
    category: StringProperty()
    commercial_use: BoolProperty(default=True)


class CatAniSettings(bpy.types.PropertyGroup):
    motion_query: StringProperty(name="검색", description="모션 이름·설명·태그에서 모든 단어를 포함하는 항목만 남깁니다", default="", update=_on_search)
    motion_category: EnumProperty(name="카테고리", description="공개 카탈로그의 동작 분류로 목록을 좁힙니다",
                                  items=_CATEGORY_ITEMS, default="ALL", update=_on_search)
    local_only: BoolProperty(name="받은 모션만", description="이미 내려받아 바로 재생할 수 있는 모션만 남깁니다", default=False, update=_on_search)
    include_noncommercial: BoolProperty(name="비상업 데이터 포함",
                                        description="CC BY-NC처럼 상업 사용이 금지된 출처를 목록에 넣습니다. 목록에서 NC 배지로 표시되며, 상업 제품에는 쓸 수 없습니다",
                                        default=False, update=_on_search)
    motions: CollectionProperty(type=CatAniMotionItem)
    motion_active: IntProperty(name="선택 모션", default=0)
    preview_active: BoolProperty(default=False, options={"HIDDEN"})
    preview_name: StringProperty(default="", options={"HIDDEN"})
    preview_path: StringProperty(default="", options={"HIDDEN"})
    preview_collection: StringProperty(default="", options={"HIDDEN"})
    preview_reused: StringProperty(default="", options={"HIDDEN"})
    preview_hidden: BoolProperty(default=False, options={"HIDDEN"})
    preview_frame_start: IntProperty(default=1, options={"HIDDEN"})
    preview_frame_end: IntProperty(default=250, options={"HIDDEN"})
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


class CATANI_UL_motions(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_prop, _index):
        row = layout.row(align=True)
        row.label(text=item.name, icon="ARMATURE_DATA" if item.available else "IMPORT")
        badge = row.row()
        badge.alignment = "RIGHT"
        if not item.commercial_use:
            badge.label(text="NC", icon="ERROR")
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
        return _job is None

    def execute(self, context):
        settings = context.scene.catani_settings
        restore = None
        try:
            item = _selected(settings)
            target = _target(context, settings)
            if not item.available:
                _start_download(context, item.source_id, apply_after=True)
                return {"FINISHED"}
            if settings.preview_active:
                _stop_play(context)
                # 같은 모션을 미리보고 있었다면 그 리그를 그대로 원본으로 쓴다.
                if settings.preview_path == item.path:
                    _release_preview(settings)
                else:
                    _clear_preview(context)
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
        if not asset.commercial_use:
            settings.motion_status += " · 비상업 데이터(상업 제품 사용 금지)"
            settings.apply_report += f"\n라이선스: {asset.license_note}"
        self.report({"WARNING"} if warning or not asset.commercial_use else {"INFO"}, settings.motion_status)


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
        return _job is None

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


class CATANI_OT_motion_preview(bpy.types.Operator):
    bl_idname = "catani.motion_preview"
    bl_label = "뷰포트에서 재생"
    bl_description = "선택한 모션 원본 리그를 임시로 불러와 뷰포트에서 재생합니다. 적용하면 그대로 원본으로 쓰입니다"

    @classmethod
    def poll(cls, context):
        return _job is None

    def execute(self, context):
        settings = context.scene.catani_settings
        restore = None
        try:
            item = _selected(settings)
            if not item.available:
                _start_download(context, item.source_id, apply_after=False, preview_after=True)
                return {"FINISHED"}
            _clear_preview(context)
            restore = _enter_object_mode(context)
            self._show(context, settings, item)
        except Exception as error:
            settings.motion_status = str(error)[:250]
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            _leave_object_mode(restore)
        return {"FINISHED"}

    def _show(self, context, settings, item):
        asset = _asset(item)
        source = _existing_source(asset)
        collection = None
        if source is None:
            created, collection = import_asset(context, asset)
            source = next(obj for obj in created if obj.type == "ARMATURE")
        family = [source, *source.children_recursive]
        settings.preview_hidden = source.hide_get()
        for obj in family:
            obj.hide_set(False)
            obj.hide_render = False
        scene = context.scene
        settings.preview_frame_start, settings.preview_frame_end = scene.frame_start, scene.frame_end
        settings.preview_active = True
        settings.preview_name = item.name
        settings.preview_path = item.path
        # 이미 씬에 있던 원본은 정리 대상이 아니다. 이번에 불러온 컬렉션만 지운다.
        settings.preview_collection = collection.name if collection is not None else ""
        settings.preview_reused = "" if collection is not None else source.name
        start, end = retarget.action_frame_range(source)
        scene.frame_start, scene.frame_end = start, end
        scene.frame_set(start)
        for obj in context.selected_objects:
            obj.select_set(False)
        source.select_set(True)
        context.view_layer.objects.active = source
        _play(context, focus=True)
        settings.motion_status = f"미리보기 재생 중 · {item.name} · {start}~{end}f"


class CATANI_OT_preview_clear(bpy.types.Operator):
    bl_idname = "catani.preview_clear"
    bl_label = "미리보기 정리"
    bl_description = "미리보기로 불러온 임시 리그를 지우고 프레임 범위를 되돌립니다"

    @classmethod
    def poll(cls, context):
        return context.scene.catani_settings.preview_active

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            _clear_preview(context)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.motion_status = "미리보기를 정리했습니다."
        return {"FINISHED"}


def _cached_length(path):
    """패널 draw마다 파일을 다시 열지 않도록 mtime 기준으로 (프레임 수, fps)를 기억한다."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return 0, 0.0
    cached = _lengths.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1], cached[2]
    try:
        frames, fps = read_length(path)
    except (OSError, ValueError, UnicodeDecodeError):
        frames, fps = 0, 0.0
    if len(_lengths) > 64:
        _lengths.clear()
    _lengths[str(path)] = (stamp, frames, fps)
    return frames, fps


def _duration_line(item):
    """받은 파일은 BVH 머리글에서, 아직 안 받은 모션은 카탈로그에서 길이를 읽는다."""
    frames, fps = 0, 0.0
    if item.available and item.path and item.file_type == "bvh":
        frames, fps = _cached_length(Path(bpy.path.abspath(item.path)))
    if not frames and item.source_id:
        try:
            entry = get_source(item.source_id)
        except ValueError:
            entry = None
        if entry is not None:
            frames, fps = entry.frames, entry.fps
    if not frames:
        return ""
    return f"{frames:,}프레임 · 약 {frames / fps:.1f}초 · {fps:.0f} fps" if fps else f"{frames:,}프레임"


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


class CATANI_OT_motion_rename(bpy.types.Operator):
    bl_idname = "catani.motion_rename"
    bl_label = "이름·분류 바꾸기"
    bl_description = "목록에 보일 이름과 분류를 바꿔 모션 폴더의 motions.json에 저장합니다"

    new_name: StringProperty(name="이름", default="")
    new_category: EnumProperty(name="분류", items=_EDIT_CATEGORY_ITEMS, default=_FALLBACK_CATEGORY)

    @classmethod
    def poll(cls, context):
        settings = context.scene.catani_settings
        return _job is None and 0 <= settings.motion_active < len(settings.motions) and settings.motions[settings.motion_active].available

    def invoke(self, context, _event):
        item = _selected(context.scene.catani_settings)
        self.new_name = item.name
        known = {key for key, *_ in _EDIT_CATEGORY_ITEMS}
        self.new_category = item.category if item.category in known else _FALLBACK_CATEGORY
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "new_name", text="")
        layout.prop(self, "new_category", text="분류")
        layout.label(text="모션 폴더의 motions.json에 적어 두므로 다음에 열어도 유지됩니다.", icon="INFO")

    def execute(self, context):
        settings = context.scene.catani_settings
        title = " ".join(self.new_name.split())
        if not title:
            self.report({"ERROR"}, "이름을 입력하세요.")
            return {"CANCELLED"}
        try:
            item = _selected(settings)
            identifier = item.identifier
            library, relative = _library_slot(settings, item)
            update_manifest(library, relative, {"name": title, "category": self.new_category})
        except (ValueError, OSError) as error:
            self.report({"ERROR"}, str(error)[:250])
            settings.motion_status = str(error)[:250]
            return {"CANCELLED"}
        refresh(context.scene, keep=identifier)
        label = CATEGORIES.get(self.new_category, self.new_category)
        note = ""
        # 카테고리 필터가 켜져 있으면 방금 옮긴 항목이 목록에서 빠진다. 필터를 따라 옮긴다.
        if not any(entry.identifier == identifier for entry in settings.motions):
            if settings.motion_category not in ("ALL", self.new_category):
                settings.motion_category = self.new_category
                note = " · 카테고리 필터를 옮겼습니다"
            refresh(context.scene, keep=identifier)
        settings.motion_status = f"이름을 바꿨습니다: {title} · 분류 {label}{note}"
        _redraw()
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


class CATANI_OT_library_open(bpy.types.Operator):
    bl_idname = "catani.library_open"
    bl_label = "모션 폴더 열기"
    bl_description = "내려받은 모션이 들어 있는 폴더를 운영체제 파일 탐색기에서 엽니다"

    path: StringProperty(default="", options={"HIDDEN"})

    def execute(self, context):
        raw = self.path.strip()
        target = Path(bpy.path.abspath(raw)) if raw else _library_root(context.scene.catani_settings)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.report({"ERROR"}, f"모션 폴더를 열 수 없습니다: {error}")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(target))
        self.report({"INFO"}, f"모션 폴더를 열었습니다: {target}")
        return {"FINISHED"}


class CATANI_OT_library_use(bpy.types.Operator):
    bl_idname = "catani.library_use"
    bl_label = "이 폴더 사용"
    bl_description = "이 폴더를 모션 폴더로 지정하고 목록을 다시 읽습니다"

    path: StringProperty(default="", options={"HIDDEN"})

    def execute(self, context):
        settings = context.scene.catani_settings
        settings.motion_library_path = self.path.strip() or user_library_path()
        self.report({"INFO"}, f"모션 폴더를 {settings.motion_library_path}로 바꿨습니다.")
        return {"FINISHED"}


class CATANI_OT_library_migrate(bpy.types.Operator):
    bl_idname = "catani.library_migrate"
    bl_label = "모션 가져오기"
    bl_description = "다른 폴더(이전 Blender 버전 폴더 등)의 모션을 현재 모션 폴더로 한 번에 옮겨 옵니다"

    directory: StringProperty(subtype="DIR_PATH", default="", options={"HIDDEN"})
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    browse: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, _event):
        if not self.browse and self.directory.strip():
            return self.execute(context)
        if not self.directory.strip():
            # 탐색창을 이전 Blender 버전 폴더에서 열어 준다.
            others = _sibling_libraries(_library_root(context.scene.catani_settings))
            self.directory = f"{others[0]}{os.sep}" if others else ""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.catani_settings
        raw = self.directory.strip()
        if not raw:
            self.report({"ERROR"}, "가져올 폴더를 고르세요.")
            return {"CANCELLED"}
        source = Path(bpy.path.abspath(raw)).resolve()
        if not source.is_dir():
            self.report({"ERROR"}, f"폴더를 찾을 수 없습니다: {source}")
            return {"CANCELLED"}
        target = _library_root(settings)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.report({"ERROR"}, f"모션 폴더를 만들 수 없습니다: {error}")
            return {"CANCELLED"}
        target = target.resolve()
        if source == target:
            self.report({"ERROR"}, "현재 모션 폴더와 같은 폴더입니다.")
            return {"CANCELLED"}
        if target.is_relative_to(source):
            self.report({"ERROR"}, "현재 모션 폴더를 품고 있는 폴더는 가져올 수 없습니다.")
            return {"CANCELLED"}
        context.window_manager.progress_begin(0, 1)
        try:
            copied, skipped = _import_library(source, target)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, f"가져오지 못했습니다: {error}")
            return {"CANCELLED"}
        finally:
            context.window_manager.progress_end()
        _library_counts.pop(str(target), None)
        refresh(context.scene)
        if not copied and not skipped:
            settings.motion_status = f"가져올 BVH가 없습니다: {source}"
            self.report({"WARNING"}, settings.motion_status)
            return {"CANCELLED"}
        already = f" · 이미 있던 {skipped}개는 그대로 뒀습니다" if skipped else ""
        settings.motion_status = f"모션 {copied}개를 가져왔습니다{already}"
        self.report({"INFO"}, settings.motion_status)
        return {"FINISHED"}


class CATANI_OT_library_guide(bpy.types.Operator):
    bl_idname = "catani.library_guide"
    bl_label = "모션 폴더 · 보관 위치"
    bl_description = "받아 둔 모션이 어디에 남는지 보고, 폴더를 열거나 이전 Blender 버전 폴더를 다시 연결합니다"

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        root = _library_root(settings)
        default = Path(user_library_path())
        count = _library_count(root)
        column = layout.column(align=True)
        column.label(text="현재 모션 폴더", icon="FILE_FOLDER")
        _lines(column, str(root), 78)
        if count:
            column.label(text=f"BVH {count}개를 보관 중입니다.")
        elif root.is_dir():
            column.label(text="폴더는 있지만 받아 둔 모션이 아직 없습니다.")
        else:
            column.label(text="아직 폴더가 없습니다. 처음 받을 때 자동으로 만듭니다.")
        row = layout.row(align=True)
        row.operator("catani.library_open", text="폴더 열기", icon="FILE_FOLDER").path = ""
        migrate = row.operator("catani.library_migrate", text="모션 가져오기", icon="IMPORT")
        migrate.directory = ""
        migrate.browse = True
        if root != default:
            row.operator("catani.library_use", text="기본 위치로", icon="LOOP_BACK").path = ""
        layout.separator()
        guide = layout.box().column(align=True)
        guide.label(text="애드온을 업데이트해도 받은 모션은 그대로입니다", icon="INFO")
        _lines(guide, "받은 파일은 애드온 설치 폴더가 아니라 Blender 사용자 데이터 폴더에 남습니다. "
                      "그래서 CatAni를 업데이트하거나 지웠다 다시 설치해도 지워지지 않습니다.", 78)
        _lines(guide, "다만 Blender 자체를 새 버전으로 올리면 버전별 폴더를 새로 봅니다. 이때는 모션 가져오기로 이전 버전 "
                      "폴더를 고르면 받아 둔 모션과 이름·분류 인덱스를 한 번에 옮겨 옵니다.", 78)
        guide.label(text="기본 위치")
        _lines(guide, str(default), 78)
        others = _sibling_libraries(root)
        if not others:
            return
        found = layout.box().column(align=True)
        found.label(text="다른 Blender 버전 폴더에서 받아 둔 모션을 찾았습니다", icon="DUPLICATE")
        for candidate in others:
            _lines(found, str(candidate), 78)
            buttons = found.row(align=True)
            migrate = buttons.operator("catani.library_migrate", text="여기서 가져오기", icon="IMPORT")
            migrate.directory = str(candidate)
            migrate.browse = False
            buttons.operator("catani.library_use", text="이 폴더 사용", icon="CHECKMARK").path = str(candidate)
            buttons.operator("catani.library_open", text="열기", icon="FILE_FOLDER").path = str(candidate)

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
        folder = column.row(align=True)
        folder.operator("catani.library_open", text="폴더 열기", icon="FILE_FOLDER").path = ""
        folder.operator("catani.library_guide", text="보관 위치 안내", icon="QUESTION")
        column.prop(settings, "frame_step")
        column.prop(settings, "smooth_window")
        column.prop(settings, "simplify_error")
        column.prop(settings, "use_location")
        column.prop(settings, "ground_contact")
        column.prop(settings, "use_ik")
        column.prop(settings, "hide_source")
        column.prop(settings, "include_noncommercial")
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


class CATANI_PT_main(bpy.types.Panel):
    bl_label = "CatAni · 모션"
    bl_idname = "CATANI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CatAni"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        search = layout.row(align=True)
        search.prop(settings, "motion_query", text="", icon="VIEWZOOM")
        search.operator("catani.motion_refresh", text="", icon="FILE_REFRESH")
        filters = layout.row(align=True)
        filters.prop(settings, "motion_category", text="")
        filters.prop(settings, "local_only", toggle=True)
        layout.template_list("CATANI_UL_motions", "catani_main", settings, "motions",
                             settings, "motion_active", rows=_LIST_ROWS)
        try:
            chosen = _selected(settings)
        except ValueError as error:
            chosen = None
            layout.label(text=str(error), icon="INFO")
        else:
            info = layout.column(align=True)
            head = info.row(align=True)
            head.label(text=chosen.name, icon="ARMATURE_DATA" if chosen.available else "IMPORT")
            head.operator("catani.motion_rename", text="", icon="GREASEPENCIL")
            info.label(text=f"{chosen.file_type.upper()} · {chosen.size_bytes / 1024:.0f}KB · "
                            f"{CATEGORIES.get(chosen.category, chosen.category or '없음')}")
            length = _duration_line(chosen)
            if length:
                info.label(text=length)
        layout.prop(settings, "target_armature", text="대상")
        row = layout.row(align=True)
        if chosen is not None and not chosen.available:
            row.operator("catani.motion_preview", text=f"받아서 재생 · {chosen.size_bytes / 1024:.0f}KB", icon="IMPORT")
        else:
            row.operator("catani.motion_preview", text="뷰포트에서 재생", icon="PLAY")
        row.operator("catani.motion_info", text="출처", icon="INFO")
        button = layout.row()
        button.scale_y = 1.6
        button.operator("catani.motion_apply", text="적용", icon="CHECKMARK")
        if settings.preview_active:
            preview = layout.box()
            preview.label(text=f"미리보기 재생 중 · {settings.preview_name}"[:44], icon="HIDE_OFF")
            preview.operator("catani.preview_clear", icon="TRASH")
        if _job is not None:
            layout.progress(factor=settings.download_progress, text=settings.download_status[:48])
            layout.operator("catani.download_cancel", icon="X")
        _lines(layout, settings.motion_status)
        footer = layout.row(align=True)
        footer.operator("catani.settings", text="상세 설정", icon="PREFERENCES")
        footer.operator("catani.library_guide", text="모션 폴더", icon="FILE_FOLDER")


_classes = (
    CatAniMotionItem, CatAniSettings, CATANI_UL_motions,
    CATANI_OT_motion_refresh, CATANI_OT_motion_apply, CATANI_OT_motion_import,
    CATANI_OT_motion_preview, CATANI_OT_preview_clear,
    CATANI_OT_motion_download, CATANI_OT_download_cancel,
    CATANI_OT_motion_rename, CATANI_OT_motion_info,
    CATANI_OT_library_open, CATANI_OT_library_use, CATANI_OT_library_migrate, CATANI_OT_library_guide,
    CATANI_OT_settings,
    CATANI_PT_main,
)

_handlers = (
    (bpy.app.handlers.load_pre, _stop_download),
    (bpy.app.handlers.load_post, _refresh_after_load),
)


def register():
    _lengths.clear()
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.catani_settings = PointerProperty(type=CatAniSettings)
    for handlers, callback in _handlers:
        handlers.append(callback)
    _refresh_after_load()


def unregister():
    _stop_download()
    _lengths.clear()
    if bpy.app.timers.is_registered(_refresh_all):
        bpy.app.timers.unregister(_refresh_all)
    for handlers, callback in _handlers:
        if callback in handlers:
            handlers.remove(callback)
    if hasattr(bpy.types.Scene, "catani_settings"):
        del bpy.types.Scene.catani_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
