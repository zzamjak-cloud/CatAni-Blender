"""Blender 안에서 검색 → 목록 → 적용 한 흐름과 실패 경로를 검사한다."""

from dataclasses import replace
from pathlib import Path
import hashlib
import io
import json
import tempfile
from unittest.mock import patch

import bpy
import bl_ext.user_default.catani as addon
from bl_ext.user_default.catani import motion_downloader
from bl_ext.user_default.catani.source_catalog import CATALOG


BVH_TEXT = """HIERARCHY
ROOT Hips
{
    OFFSET 0.00 0.00 0.00
    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
    JOINT Spine
    {
        OFFSET 0.00 4.00 0.00
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT RightArm
        {
            OFFSET -3.00 3.00 0.00
            CHANNELS 3 Zrotation Xrotation Yrotation
            JOINT RightForeArm
            {
                OFFSET -5.00 0.00 0.00
                CHANNELS 3 Zrotation Xrotation Yrotation
                End Site
                {
                    OFFSET -4.00 0.00 0.00
                }
            }
        }
    }
}
MOTION
Frames: 3
Frame Time: 0.0416667
0.00 12.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00
0.00 12.00 0.00 0.00 0.00 0.00 0.00 4.00 0.00 -25.00 0.00 0.00 -12.00 0.00 0.00
0.00 12.00 0.00 0.00 0.00 0.00 0.00 8.00 0.00 -45.00 0.00 0.00 -20.00 0.00 0.00
"""

MANIFEST = ('{"motions":[{"file":"friendly_wave.bvh","name":"테스트 손 인사",'
            '"tags":["wave","greeting","friendly"],"description":"테스트용 상반신 BVH"}]}')


def expect_cancelled(operator, **kwargs):
    """ERROR 보고가 Python 호출에서는 RuntimeError로 전달되는 경로도 확인한다."""
    try:
        assert operator(**kwargs) == {"CANCELLED"}
    except RuntimeError:
        pass


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
temporary = tempfile.TemporaryDirectory(prefix="catani-motion-ui-")
library = Path(temporary.name)
(library / "friendly_wave.bvh").write_text(BVH_TEXT, encoding="utf-8")
(library / "motions.json").write_text(MANIFEST, encoding="utf-8")

settings = bpy.context.scene.catani_settings
settings.motion_library_path = str(library)

# 검색은 로컬 파일과 아직 받지 않은 공개 카탈로그를 한 목록에 담는다.
settings.motion_query = ""
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assert len(settings.motions) == 1 + len(CATALOG), [item.name for item in settings.motions]
assert sum(1 for item in settings.motions if item.available) == 1
pending = next(item for item in settings.motions if not item.available)
assert pending.source_id and pending.download_url, "공개 항목의 출처 정보가 비었습니다"
assert pending.sha256 or pending.blob_sha1, "공개 항목에 검증 가능한 체크섬이 없습니다"

# 검색어는 즉시 목록을 좁힌다. 별도의 갱신 버튼이 필요하지 않다.
settings.motion_query = "wave friendly"
assert len(settings.motions) == 1, [item.name for item in settings.motions]
assert settings.motions[0].name == "테스트 손 인사"
assert settings.motion_active == 0
settings.motion_query = "없는검색어"
assert len(settings.motions) == 0
settings.motion_query = "friendly"
assert len(settings.motions) == 1

# 적용: 모션을 가져와 캐릭터에 굽는다. 원본 장면과 이전 Action은 보존한다.
target = bpy.data.objects["Amature_Player"]
previous_action = target.animation_data.action
visibility = {obj.name: (obj.hide_get(), obj.hide_render) for obj in bpy.data.objects}
before = set(bpy.data.objects)
settings.target_armature = target
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
created = [obj for obj in bpy.data.objects if obj not in before]
assert any(obj.type == "ARMATURE" for obj in created), "모션 원본 아마추어가 없습니다"
assert any(obj.get("catani_motion_source") for obj in created), "모션 출처 속성이 없습니다"
assert any(collection.name.startswith("CatAni 모션 원본") for collection in bpy.data.collections)
assert target.animation_data.action is not previous_action
assert previous_action.use_fake_user, "이전 Action이 보존되지 않았습니다"
assert "적용됨" in settings.motion_status, settings.motion_status
assert "본 매핑: 4" in settings.apply_report, settings.apply_report
assert before.issubset(set(bpy.data.objects)), "적용이 기존 오브젝트를 제거했습니다"
assert visibility[target.name] == (target.hide_get(), target.hide_render), "적용이 캐릭터 표시 상태를 바꿨습니다"
assert all(obj.hide_get() for obj in created if obj.type == "ARMATURE"), "모션 원본 리그를 숨기지 않았습니다"

# 리타게팅 없이 원본만 가져오는 보조 경로.
after_apply = set(bpy.data.objects)
assert bpy.ops.catani.motion_import() == {"FINISHED"}, settings.motion_status
assert len(set(bpy.data.objects) - after_apply) >= 1
assert "리타게팅은 하지 않았습니다" in settings.motion_status

# 실패 경로: 선택 없음, 대상 없음, 파일 사라짐. 어느 경우도 장면을 늘리지 않는다.
stable = set(bpy.data.objects)
settings.motion_query = "없는검색어"
expect_cancelled(bpy.ops.catani.motion_apply)
assert "선택하세요" in settings.motion_status, settings.motion_status
settings.motion_query = "friendly"
settings.target_armature = None
bpy.context.view_layer.objects.active = None
expect_cancelled(bpy.ops.catani.motion_apply)
assert "대상으로 지정" in settings.motion_status, settings.motion_status
settings.target_armature = target
# 이미 가져온 원본이 장면에 있으면 파일을 다시 읽지 않고 재사용한다.
(library / "friendly_wave.bvh").unlink()
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
assert set(bpy.data.objects) == stable, "재사용 경로가 원본 리그를 중복 생성했습니다"
# 원본까지 지우면 파일이 없으므로 장면을 늘리지 않고 실패해야 한다.
bpy.data.batch_remove(ids=[obj for obj in bpy.data.objects if obj.get("catani_motion_source")])
remaining = set(bpy.data.objects)
expect_cancelled(bpy.ops.catani.motion_apply)
assert set(bpy.data.objects) == remaining, "사라진 모션 파일이 장면에 잔여 객체를 남겼습니다"
assert "찾을 수 없습니다" in settings.motion_status, settings.motion_status
(library / "motions.json").write_text("{broken", encoding="utf-8")
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assert len(settings.motions) == 0 and "motions.json" in settings.motion_status, settings.motion_status

# 다운로드 → 자동 적용: 응답 바이트만 합성 BVH로 바꾸고 실제 작업 경로를 그대로 쓴다.
download_directory = library / "downloads"
settings.motion_library_path = str(download_directory)
settings.motion_query = ""
payload = BVH_TEXT.encode("utf-8")
requests = []


def memory_opener(request, timeout=None):
    requests.append(request.full_url)
    return io.BytesIO(payload)


def synthetic_job(entry, directory):
    synthetic = replace(entry, sha256=hashlib.sha256(payload).hexdigest(),
                        blob_sha1=motion_downloader.git_blob_sha1(payload), size_bytes=len(payload))
    return motion_downloader.DownloadJob(synthetic, directory)


entry = CATALOG[0]
settings.motion_active = next(index for index, item in enumerate(settings.motions) if item.source_id == entry.id)
assert not settings.motions[settings.motion_active].available
scene_objects = set(bpy.data.objects)
with patch.object(motion_downloader, "urlopen", memory_opener), patch.object(addon, "DownloadJob", synthetic_job):
    assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
    job = addon._job["download"]
    job._thread.join(timeout=10)
    assert job.done and job.error is None, job.error
    assert addon._poll_download() is None
assert requests == [entry.download_url]
assert addon._job is None
downloaded = next(item for item in settings.motions if item.source_id == entry.id)
assert downloaded.available and Path(downloaded.path).read_bytes() == payload
assert "적용됨" in settings.motion_status, settings.motion_status
assert len(set(bpy.data.objects) - scene_objects) >= 1, "자동 적용이 모션을 가져오지 않았습니다"
assert downloaded.path in settings.apply_report, "리포트에 실제 사용한 파일 경로가 없습니다"
assert "검증:" in settings.apply_report and "방향 오차" in settings.apply_report

# 미리보기: 임시 리그를 불러와 재생 구간을 잡고, 정리하면 장면과 프레임 범위를 되돌린다.
bpy.data.batch_remove(ids=[obj for obj in bpy.data.objects if obj.get("catani_motion_source")])
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 250
before_preview = set(bpy.data.objects)
settings.motion_active = next(index for index, item in enumerate(settings.motions) if item.source_id == entry.id)
assert bpy.ops.catani.motion_preview() == {"FINISHED"}, settings.motion_status
assert settings.preview_active and settings.preview_collection
collection_name = settings.preview_collection
assert bpy.data.collections[collection_name].objects, "미리보기 리그를 불러오지 않았습니다"
assert (scene.frame_start, scene.frame_end) != (1, 250), "미리보기가 재생 구간을 잡지 않았습니다"
assert "미리보기 재생 중" in settings.motion_status, settings.motion_status
assert bpy.ops.catani.preview_clear() == {"FINISHED"}
assert not settings.preview_active and not settings.preview_collection
assert (scene.frame_start, scene.frame_end) == (1, 250), "미리보기 정리가 프레임 범위를 되돌리지 않았습니다"
assert set(bpy.data.objects) == before_preview, "미리보기 정리가 임시 리그를 남겼습니다"
assert collection_name not in bpy.data.collections, "미리보기 정리가 컬렉션을 남겼습니다"

# 미리보기 뒤 적용하면 같은 임시 리그를 그대로 모션 원본으로 넘긴다.
assert bpy.ops.catani.motion_preview() == {"FINISHED"}, settings.motion_status
collection_name = settings.preview_collection
assert bpy.ops.catani.motion_apply() == {"FINISHED"}, settings.motion_status
assert "적용됨" in settings.motion_status, settings.motion_status
assert not settings.preview_active and not bpy.ops.catani.preview_clear.poll()
assert collection_name in bpy.data.collections, "적용이 미리보기 리그를 지웠습니다"

# 이미 적용해 숨겨 둔 원본을 다시 미리보면 드러냈다가 정리할 때 숨김으로 되돌린다.
source = next(obj for obj in bpy.data.objects if obj.get("catani_motion_source") and obj.type == "ARMATURE")
assert source.hide_get(), "적용 뒤 모션 원본이 숨겨지지 않았습니다"
assert bpy.ops.catani.motion_preview() == {"FINISHED"}, settings.motion_status
assert not source.hide_get(), "재사용한 원본을 미리보기에서 드러내지 않았습니다"
assert not settings.preview_collection, "이미 있던 원본을 정리 대상으로 잡았습니다"
assert bpy.ops.catani.preview_clear() == {"FINISHED"}
assert source.hide_get(), "재사용한 원본을 다시 숨기지 않았습니다"

# 이름 바꾸기: motions.json에 적히고 목록에 바로 반영되며 선택도 유지된다.
settings.motion_library_path = str(download_directory)
settings.motion_query = ""
addon.refresh(bpy.context.scene)
settings.motion_active = next(index for index, item in enumerate(settings.motions) if item.source_id == entry.id)
identifier = settings.motions[settings.motion_active].identifier
assert bpy.ops.catani.motion_rename(new_name="  내가 고른   걷기  ") == {"FINISHED"}, settings.motion_status
renamed = settings.motions[settings.motion_active]
assert renamed.identifier == identifier, "이름을 바꾼 뒤 선택이 옮겨갔습니다"
assert renamed.name == "내가 고른 걷기", renamed.name
assert renamed.source_id == entry.id, "이름만 바꿨는데 출처가 사라졌습니다"
assert json.loads((download_directory / "motions.json").read_text(encoding="utf-8"))["motions"][0]["name"] == "내가 고른 걷기"
addon.refresh(bpy.context.scene)
assert settings.motions[settings.motion_active].name == "내가 고른 걷기", "다시 읽었을 때 이름이 사라졌습니다"
expect_cancelled(bpy.ops.catani.motion_rename, new_name="   ")
# 아직 받지 않은 모션은 적어 둘 파일이 없으므로 버튼이 잠긴다.
settings.local_only = False
addon.refresh(bpy.context.scene)
pending_index = next((index for index, item in enumerate(settings.motions) if not item.available), None)
assert pending_index is not None, "받지 않은 공개 모션이 목록에 없습니다"
settings.motion_active = pending_index
assert not bpy.ops.catani.motion_rename.poll(), "받지 않은 모션에 이름 바꾸기가 열렸습니다"

addon.unregister()
assert not hasattr(bpy.types.Scene, "catani_settings")
addon.register()
assert hasattr(bpy.types.Scene, "catani_settings")
temporary.cleanup()
print("CATANI_PASS 통합 목록·즉시 검색·적용·원본 보존·mock 다운로드 후 자동 적용·미리보기 세션·이름 바꾸기·실패 경로")
