"""CatAni: 비용 없이 실행하는 캐주얼 동작 생성기."""

import bpy
import json
import textwrap
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .core import MotionSpec
from . import engine
from .agent_plan import DEFAULT_PLAN, parse_plan
from .agent_bridge import AgentJob

_agent_job = None
_agent_scene = None


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _poll_agent():
    global _agent_job, _agent_scene
    if _agent_job is None:
        return None
    try:
        plan = _agent_job.poll()
        if plan is None:
            return 0.3
        _agent_scene.catani_settings.plan_json = json.dumps(plan, ensure_ascii=False)
        _agent_scene.catani_settings.agent_status = "명세 수신 완료 · 검토 후 미리보기를 누르세요." if plan["supported"] else "지원 범위 밖 요청 · 명세 설명을 확인하세요."
    except Exception as error:
        _agent_job.close()
        if _agent_scene is not None:
            _agent_scene.catani_settings.agent_status = str(error)[:250]
    finally:
        if _agent_job is not None and _agent_job._closed:
            _agent_job = None
            _agent_scene = None
    _redraw()
    return 0.3 if _agent_job is not None else None


@bpy.app.handlers.persistent
def _stop_agent(_unused=None):
    global _agent_job, _agent_scene
    if _agent_job is not None:
        _agent_job.close()
        if _agent_scene is not None:
            _agent_scene.catani_settings.agent_status = "에이전트 요청을 취소했습니다."
    _agent_job = None
    _agent_scene = None
    if bpy.app.timers.is_registered(_poll_agent):
        bpy.app.timers.unregister(_poll_agent)


class CatAniSettings(bpy.types.PropertyGroup):
    recipe: EnumProperty(name="동작", items=[("natural_wave", "전신 인사 · 팔 IK", "얼굴 앞 손 경로와 발 접촉을 IK로 제어하는 전신 인사"), ("idle", "대기 / 호흡", "제자리 호흡 동작"), ("wave", "단순 손 흔들기 · 기존 FK", "비교용 기존 FK 동작이며 전신 인사에는 팔 IK 항목을 사용하세요")], default="natural_wave")
    side: EnumProperty(name="손", items=[("R", "오른손", "캐릭터 오른손"), ("L", "왼손", "캐릭터 왼손")], default="R")
    duration: FloatProperty(name="전체 길이(초)", default=2.0, min=0.5, max=10.0)
    intensity: FloatProperty(name="동작 강도", default=0.7, min=0.1, max=1.0)
    repeat: IntProperty(name="구간 내 반복", default=2, min=1, max=8)
    prompt: StringProperty(name="동작 요청", default="친근하게 오른손으로 두 번 인사해줘. 시선과 몸통, 체중 이동을 자연스럽게 연결해줘.", maxlen=2000)
    codex_path: StringProperty(name="Codex 실행 파일", subtype="FILE_PATH")
    plan_json: StringProperty(name="검토할 동작 명세", default=json.dumps(DEFAULT_PLAN, ensure_ascii=False))
    agent_status: StringProperty(name="상태", default="기본 전신 인사 프리셋 · 에이전트 호출 없이 미리보기 가능")


class CATANI_OT_agent_generate(bpy.types.Operator):
    bl_idname = "catani.agent_generate"
    bl_label = "에이전트로 전신 인사 설계"
    bl_description = "기존 Codex 로그인과 계정 사용량을 사용합니다. 요청 텍스트만 전송하며 장면 파일은 전송하지 않습니다"

    @classmethod
    def poll(cls, context):
        return _agent_job is None and engine.get_session() is None

    def execute(self, context):
        global _agent_job, _agent_scene
        settings = context.scene.catani_settings
        try:
            _agent_job = AgentJob(settings.prompt, bpy.path.abspath(settings.codex_path) if settings.codex_path else "", previous_plan=parse_plan(settings.plan_json))
            _agent_scene = context.scene
            settings.agent_status = "에이전트 설계 중 · 장면은 변경하지 않습니다."
            bpy.app.timers.register(_poll_agent, first_interval=0.3)
        except Exception as error:
            _stop_agent()
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_agent_cancel(bpy.types.Operator):
    bl_idname = "catani.agent_cancel"
    bl_label = "에이전트 요청 취소"

    def execute(self, context):
        _stop_agent()
        return {"FINISHED"}


class CATANI_OT_plan_default(bpy.types.Operator):
    bl_idname = "catani.plan_default"
    bl_label = "기본 전신 인사 명세"

    def execute(self, context):
        context.scene.catani_settings.plan_json = json.dumps(DEFAULT_PLAN, ensure_ascii=False)
        context.scene.catani_settings.agent_status = "기본 프리셋으로 복원했습니다."
        return {"FINISHED"}


class CATANI_OT_plan_import(bpy.types.Operator, ImportHelper):
    bl_idname = "catani.plan_import"
    bl_label = "명세 JSON 가져오기"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            with open(self.filepath, "rb") as stream:
                data = stream.read(16385)
            plan = parse_plan(data.decode("utf-8"))
            context.scene.catani_settings.plan_json = json.dumps(plan, ensure_ascii=False)
            context.scene.catani_settings.agent_status = "JSON 명세 검증 완료 · 검토 후 미리보기를 누르세요."
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_plan_export(bpy.types.Operator, ExportHelper):
    bl_idname = "catani.plan_export"
    bl_label = "명세 JSON 내보내기"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            plan = parse_plan(context.scene.catani_settings.plan_json)
            with open(self.filepath, "w", encoding="utf-8") as stream:
                json.dump(plan, stream, ensure_ascii=False, indent=2)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class CATANI_OT_inspect(bpy.types.Operator):
    bl_idname = "catani.inspect_rig"
    bl_label = "선택 리그 검사"
    bl_description = "Player v1 샘플 리그의 본 구조와 레스트 방향을 검사합니다"

    def execute(self, context):
        errors = engine.inspect_rig(context.active_object)
        if errors:
            self.report({"ERROR"}, " / ".join(errors))
            return {"CANCELLED"}
        self.report({"INFO"}, "Player v1 프로필을 사용할 수 있습니다.")
        return {"FINISHED"}


class CATANI_OT_preview(bpy.types.Operator):
    bl_idname = "catani.preview"
    bl_label = "동작 미리보기 생성"
    bl_description = "리그·바인딩 메시 복사본에 동작을 생성합니다. 제약으로 연결된 소품은 제외합니다"

    @classmethod
    def poll(cls, context):
        return _agent_job is None and engine.get_session() is None and context.mode == "OBJECT" and context.active_object is not None and context.active_object.type == "ARMATURE"

    def execute(self, context):
        settings = context.scene.catani_settings
        try:
            spec = MotionSpec(recipe=settings.recipe, side=settings.side, duration=settings.duration, intensity=settings.intensity, repeat=settings.repeat, fps=context.scene.render.fps / context.scene.render.fps_base, plan=parse_plan(settings.plan_json) if settings.recipe == "natural_wave" else None)
            engine.begin_preview(context, context.active_object, spec)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "미리보기 생성 완료. 타임라인을 재생하고 확정 또는 취소하세요.")
        return {"FINISHED"}


class CATANI_OT_confirm(bpy.types.Operator):
    bl_idname = "catani.confirm"
    bl_label = "복사본으로 확정"
    bl_description = "생성 결과와 독립 Action을 보관합니다. 원본은 Outliner에서 다시 표시할 수 있습니다"

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
    bl_description = "생성 복사본을 삭제하고 원본 표시·선택·프레임 범위를 복원합니다"

    @classmethod
    def poll(cls, context):
        return engine.get_session() is not None and context.mode == "OBJECT"

    def execute(self, context):
        engine.cancel_preview(context)
        self.report({"INFO"}, "미리보기를 취소하고 원본 상태를 복원했습니다.")
        return {"FINISHED"}


class CATANI_PT_main(bpy.types.Panel):
    bl_label = "CatAni · 로컬 동작"
    bl_idname = "CATANI_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CatAni"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.catani_settings
        layout.label(text="Player v1 샘플 리그 전용", icon="ARMATURE_DATA")
        layout.label(text="제약으로 연결된 소품은 생성에서 제외")
        layout.label(text="최소 키 · Graph Editor 곡선 편집")
        layout.operator("catani.inspect_rig")
        if engine.get_session():
            layout.label(text="복사본 미리보기 · 타임라인 재생")
            layout.operator("catani.confirm", icon="CHECKMARK")
            layout.operator("catani.cancel", icon="X")
            layout.label(text="확정하면 원본은 숨김으로 유지")
            layout.label(text="저장·Undo 전에 미리보기 자동 취소")
        else:
            layout.prop(settings, "recipe")
            if settings.recipe == "natural_wave":
                box = layout.box()
                box.label(text="한 손 전신 인사 전용 · 양발 접촉 유지")
                box.label(text="팔 IK · 손목 위치와 팔꿈치 방향 제어")
                box.label(text="손 경로 편집: IK_Arm.L / IK_Arm.R")
                box.label(text="기존 Codex 계정 사용량 사용 · 요청만 전송")
                box.prop(settings, "prompt")
                box.prop(settings, "codex_path")
                box.operator("catani.agent_generate")
                if _agent_job is not None:
                    box.operator("catani.agent_cancel", icon="X")
                for line in textwrap.wrap(settings.agent_status, 30):
                    box.label(text=line)
                tools = box.column()
                tools.enabled = _agent_job is None
                tools.operator("catani.plan_default")
                row = tools.row(align=True)
                row.operator("catani.plan_import", text="JSON 가져오기")
                row.operator("catani.plan_export", text="JSON 내보내기")
                review = layout.box()
                review.label(text="적용 전 동작 명세 검토")
                try:
                    plan = parse_plan(settings.plan_json)
                    style_label = {"friendly": "친근함", "shy": "수줍음", "energetic": "활기참"}[plan["style"]]
                    review.label(text=f"{'오른손' if plan['side'] == 'R' else '왼손'} · {plan['duration']:.1f}초 · {plan['repeat']}회 · {style_label}")
                    for line in textwrap.wrap(plan["reason"], 30):
                        review.label(text=line)
                    review.label(text=f"체중 이동 {plan['weight_shift'] * 100:.1f}% · 몸통 {plan['torso_turn']:.1f}°")
                    review.label(text=f"시선 {plan['head_turn']:.1f}° · 팔 {plan['arm_lift']:.1f}°")
                    if not plan["supported"]:
                        review.label(text="지원하지 않는 요청: 미리보기 불가", icon="ERROR")
                except ValueError:
                    review.label(text="잘못된 명세 · JSON을 다시 가져오세요", icon="ERROR")
                review.label(text="세부 수치는 JSON 내보내기 후 편집 가능")
            else:
                if settings.recipe == "wave":
                    layout.prop(settings, "side", expand=True)
                layout.prop(settings, "duration")
                layout.prop(settings, "intensity")
                layout.prop(settings, "repeat")
            layout.operator("catani.preview", icon="PLAY")
            layout.label(text="오브젝트 모드에서 리그를 선택하세요")


_classes = (CatAniSettings, CATANI_OT_agent_generate, CATANI_OT_agent_cancel, CATANI_OT_plan_default, CATANI_OT_plan_import, CATANI_OT_plan_export, CATANI_OT_inspect, CATANI_OT_preview, CATANI_OT_confirm, CATANI_OT_cancel, CATANI_PT_main)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.catani_settings = PointerProperty(type=CatAniSettings)
    bpy.app.handlers.load_pre.append(_stop_agent)
    bpy.app.handlers.load_pre.append(engine.clear_before_load)
    bpy.app.handlers.save_pre.append(engine.cancel_before_save)
    bpy.app.handlers.undo_pre.append(engine.cancel_before_save)
    bpy.app.handlers.redo_pre.append(engine.cancel_before_save)


def unregister():
    _stop_agent()
    if _stop_agent in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_stop_agent)
    engine.cancel_preview(bpy.context)
    for handlers, callback in ((bpy.app.handlers.load_pre, engine.clear_before_load), (bpy.app.handlers.save_pre, engine.cancel_before_save), (bpy.app.handlers.undo_pre, engine.cancel_before_save), (bpy.app.handlers.redo_pre, engine.cancel_before_save)):
        if callback in handlers:
            handlers.remove(callback)
    if hasattr(bpy.types.Scene, "catani_settings"):
        del bpy.types.Scene.catani_settings
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
