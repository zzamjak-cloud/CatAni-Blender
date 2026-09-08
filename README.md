# CatAni

CatAni 0.3.0은 로컬 모션 샘플을 Blender로 가져오고, 필요한 경우 기존 최소 곡선 보정 기능으로 다듬는 방향의 Extension입니다. 절차 코드만으로 자연스러운 인체 동작을 새로 만드는 대신 BVH/FBX 모션 라이브러리를 검색·가져오기 위한 기반을 제공합니다. 기본 프리셋과 저장된 JSON은 오프라인으로 생성할 수 있으며, 자연어 설계에는 기존 로그인된 Codex CLI를 선택적으로 사용합니다. 별도 API 키를 받지 않지만 Codex 요청은 클라우드 계정의 구독·사용량 조건이 적용됩니다.

제공된 샘플 `Blender/Player_Animation_01.blend`의 `Amature_Player` 전용 프로필에서 `natural_wave`(전신 인사), `idle`, `wave`를 생성하는 기존 기능은 유지합니다. 다만 이 경로는 제한된 제스처 보정용이며, 걷기·점프·앉기 같은 많은 동작은 `motions/` 폴더에 넣은 실제 모션 캡처 샘플을 가져와 리타게팅 기준으로 사용하는 흐름을 우선합니다. 현재 모션 라이브러리 기능은 BVH/FBX 검색과 가져오기까지 제공하며, 선택 리그로 자동 리타게팅하는 단계는 다음 범위입니다.

## 모션 라이브러리 사용

1. 저장소 루트의 `motions/` 폴더에는 기본 확인용 `데모 손 인사` BVH가 들어 있습니다. 실제 작업용 모션은 이 폴더에 BVH 또는 FBX 파일을 추가합니다.
2. 필요한 경우 `motions/motions.json`에 이름·태그·설명을 기록합니다. 아무 검색어 없이 목록을 갱신하면 현재 폴더의 전체 모션을 보여줍니다.
3. 개발 실행기로 Blender를 열고 3D View의 `N` 사이드바에서 `CatAni` → `CatAni · 로컬 동작` 패널을 엽니다.
4. **모션 라이브러리 · BVH/FBX 샘플 기반** 영역에서 모션 폴더와 검색어를 지정하고 **모션 목록 갱신**을 누릅니다.
5. 검색 결과에서 모션을 선택한 뒤 **선택 모션 가져오기**를 누릅니다. 가져온 모션은 `CatAni 모션 원본` 컬렉션에 따로 생성되며, 현재 캐릭터에 바로 덮어쓰지 않습니다.

포함된 기본 예제는 기능 확인용으로 직접 작성한 짧은 BVH입니다. 자연스러운 고품질 동작을 확보하려면 별도의 모션 캡처 샘플을 추가해야 합니다. `motions.json` 예시는 다음과 같습니다.

```json
{
  "motions": [
    {
      "file": "greeting/friendly_wave.bvh",
      "name": "친근한 손 인사",
      "tags": ["wave", "greeting", "friendly"],
      "description": "상대에게 가볍게 손을 흔드는 전신 모션"
    }
  ]
}
```

## 에이전트로 전신 인사 만들기

1. 개발 실행기로 샘플을 열고 오브젝트 모드에서 리그를 선택합니다.
2. CatAni 패널의 **전신 인사 · 팔 IK**를 선택하고 동작 요청을 입력합니다. 예: “친구에게 오른손으로 두 번 인사해 줘. 먼저 상대를 보고 체중을 옮긴 뒤 팔을 올려 줘.”
3. 에이전트 설계를 실행합니다. 현재 로그인된 Codex CLI를 사용하며 Blender 파일·메시를 전달하지 않습니다. 요청 문장과 현재 명세만 사용합니다. CLI 탐지가 안 되면 실행 파일 경로를 지정합니다.
4. 받은 설명·숫자 명세를 검토하고 미리보기를 생성합니다. 설계 중에는 장면을 바꾸지 않으며 요청을 취소할 수 있습니다. 생성 실패나 180초 제한 시간 초과는 상태에 표시합니다.
5. 재생 후 미리보기를 취소하고 “현재보다 팔을 5도 낮춰”, “몸통 회전을 줄여”처럼 다시 요청하면 현재 명세를 기준으로 수정합니다. 만족하면 복사본으로 확정합니다.

CLI가 없어도 기본 명세로 전신 인사를 생성할 수 있습니다. JSON 가져오기·내보내기를 통해 명세를 보관하거나 다른 에이전트가 만든 같은 스키마의 명세를 사용할 수 있습니다. 허용 범위 밖 값, 실행 코드, 알 수 없는 필드와 지원하지 않는 동작은 적용하지 않습니다.

에이전트는 현재 제한된 전신 인사 레시피의 타이밍·진폭을 설계합니다. 임의의 새 동작 코드를 실행하거나 렌더를 보고 스스로 품질을 평가하는 기능은 아닙니다. 전체적인 연기 품질은 실제 재생 결과를 보고 조정해야 합니다. CLI의 비대화형 실행과 JSON 스키마 출력은 [공식 Codex 문서](https://developers.openai.com/codex/noninteractive/)를 바탕으로 연결했습니다.

### 전신 동작의 편집과 검증

기본 전신 인사는 팔 폴의 위치 곡선을 포함해 전체 204개 키이며 24/60FPS에서 키 수가 같습니다. 팔은 상완·전완 FK 회전 키 없이 `IK_Arm.L` / `IK_Arm.R`의 위치 곡선으로 제어합니다. 결과 리그의 Pose Mode에서 해당 손목 컨트롤러를 움직이거나 Graph Editor에서 위치 곡선을 수정하세요. 몸통 각도와 골반 위치 곡선도 별도로 편집할 수 있습니다.

팔꿈치 방향은 생성 결과 리그의 Pose Mode에서 **`IK_Pole_Arm.L` / `IK_Pole_Arm.R`**을 이동해 제어합니다. `IK_Pole.L` / `IK_Pole.R`는 다리용 폴이므로 구분하세요. 폴의 위치 곡선은 Graph Editor에서 편집할 수 있습니다. IK가 계산한 자세는 실제 본의 방향과 팔꿈치 위치로 확인합니다. 상완·전완의 회전 입력값 자체가 바뀌는 방식은 아닙니다. 손목 방향은 별도 보조 오브젝트의 Action 슬롯에 작은 수의 회전 키로 저장합니다. 양팔·양다리 IK와 손목·발 방향 제약은 유지하세요. 완전 FK 내보내기는 후속 범위입니다.

초기 0.2.1 구현은 기존 팔 폴을 숨겨진 오브젝트로 대체하고 양쪽에 같은 폴 각도를 적용해 폴 컨트롤러가 반응하지 않고 팔이 비틀리는 문제가 있었습니다. 수정본은 기존 팔 폴을 연결하고 좌우 레스트 축을 반영합니다. 수정 전 확정·저장한 결과는 자동 변환하지 않습니다. 개발 실행기로 Blender를 재시작한 뒤 원본 리그에서 새로 생성하세요.

0.2.0의 팔 FK 방식은 인사 중 손이 얼굴 앞에 있다는 조건을 보장하지 못했습니다. 0.2.1은 머리의 실제 평가된 위치·방향을 따라 앞쪽 손목 경로를 만들며, 팔꿈치 폴과 손목 방향을 함께 제어합니다. 기존에 저장한 0.2.0 결과는 자동 변환하지 않으므로 원본 리그에서 새로 생성하거나 갱신된 전신 예제를 사용하세요. **단순 손 흔들기 · 기존 FK**는 비교용 동작입니다.

팔 회귀 검사는 양손과 머리·몸통 회전의 경계 설정 6가지를 각각 전체 동작 301개 시점에서 확인합니다. 시작·끝의 상완·전완 회전은 레스트 자세와 일치했고, 손목 목표 추종 오차는 0.000087 Blender 단위 미만이었습니다. Action을 연결한 상태에서 기존 팔 폴을 양방향으로 움직였을 때 팔꿈치가 최소 0.0589 단위 반응했으며 손목 목표는 유지됐습니다. 인사 구간의 얼굴 앞쪽 여유와 팔꿈치 방향, 빠른 상승 구간을 세분화한 연속성도 검사합니다. 정면·측면 렌더, 별도 프로세스 재로드와 GUI 재생도 확인했습니다.

실제 Blender에서 양손·24/60FPS를 301개 시점으로 검사했을 때 기본 명세의 골반 좌우 이동은 0.028904 Blender 단위, 몸통 회전은 약 9.02°, 발 접촉점 최대 이동은 0.0000173 단위였습니다. 이 수치는 접촉과 움직임 검증이며 자연스러움에 대한 자동 점수는 아닙니다.

`artifacts/Agent_Natural_Wave_Plan.json`은 실제 Codex CLI 응답이며, `artifacts/CatAni_Natural_Wave_Demo.blend`는 그 명세로 생성한 결과입니다. 기본 명세의 측정값과 에이전트 응답의 파라미터는 구분합니다.

## 개발 실행

소스는 `catani/`에 있으며 매니페스트 ID는 `catani`입니다. 실행기는 저장소 소스를 격리된 프로필의 `extensions/user_default/catani`에 연결합니다. 일반 Blender 설정이나 설치된 릴리스에는 연결하지 않습니다. ZIP을 다시 설치할 필요 없이 실행기를 통해 Blender를 재시작하면 수정한 소스를 읽습니다.

### macOS

개발 기준은 Blender 5.2이며 기본 실행 파일은 `/Applications/Blender.app/Contents/MacOS/Blender`입니다. 저장소 루트에서 실행합니다.

```bash
bash scripts/dev_run.sh
bash scripts/dev_run.sh Blender/Player_Animation_01.blend
BLENDER_BINARY=/Applications/Blender.app/Contents/MacOS/Blender bash scripts/dev_run.sh --background --python-expr 'import bpy; print(bpy.app.version_string)'
```

프로필: `~/Library/Application Support/Blender/CatAniDev/<Blender 주.부 버전>/`.

### Windows

PowerShell에서 실행 파일 경로를 설정합니다. `blender.exe`가 PATH에 있으면 설정을 생략할 수 있습니다.

```powershell
$env:BLENDER_BINARY = 'C:\Blender\blender.exe'
.\scripts\dev_run.ps1
.\scripts\dev_run.ps1 --background --python-expr 'import bpy; print(bpy.app.version_string)'
```

명령 프롬프트에서는 `scripts\dev_run.bat`을 사용합니다. 추가 Blender 인자와 종료 코드를 전달합니다.

```bat
set "BLENDER_BINARY=C:\Blender\blender.exe"
scripts\dev_run.bat --background --python-expr "import bpy; print(bpy.app.version_string)"
```

프로필: `<프로젝트>/.blender-dev/CatAniDev/<Blender 주.부 버전>/`. 연결할 자리에 일반 파일이나 디렉터리가 있으면 보호를 위해 실행을 중단합니다. Windows PowerShell 스크립트는 한국어 메시지 호환을 위해 UTF-8 BOM을 사용합니다. Windows 실제 실행은 별도 검증이 필요합니다.

## 사용 흐름

1. 개발 실행기로 `Blender/Player_Animation_01.blend`를 열고 오브젝트 모드에서 `Amature_Player`를 선택합니다.
2. 3D View의 N 사이드바에서 `CatAni` → `CatAni · 로컬 동작` 패널을 열고 **선택 리그 검사**를 실행합니다. 샘플 전용 프로필의 본 계층과 레스트 방향을 검사합니다.
3. **대기/호흡**(`idle`) 또는 **손 흔들기**(`wave`)를 선택합니다. 좌우, 전체 길이(0.5~10초), 강도(0.1~1), 구간 내 반복(1~8)을 조절하고 **동작 미리보기 생성**을 실행합니다.
4. 타임라인을 재생해 확인한 후 **복사본으로 확정** 또는 **미리보기 취소**를 실행합니다. 확정하면 복제한 결과 캐릭터와 새 Action을 유지합니다. 원본은 삭제하지 않고 숨기며 Outliner에서 다시 표시할 수 있습니다. 취소하면 원본의 숨김·선택 상태와 프레임을 복원합니다.

확정 전 파일 저장·실행 취소·다시 실행은 미리보기를 자동으로 취소합니다. 결과를 유지하려면 먼저 확정한 후 파일을 저장하세요. 생성 결과는 일반 Blender Action과 키프레임으로 편집할 수 있습니다. 확정한 원본은 뷰포트와 렌더에서 숨겨집니다. 원본을 다시 사용할 때는 Outliner의 표시와 렌더 아이콘을 모두 복원하세요.

## 로컬 검증

### Graph Editor에서 동작 수정

0.1.1부터 매 프레임 키를 생성하지 않습니다. 주요 포즈와 반복 동작의 전환점에만 키를 만들고, Bézier 곡선과 좌우 핸들로 중간 움직임을 연결합니다. 각 본의 움직임은 축-각도 회전의 **각도 채널 하나**(`rotation_axis_angle[0]`)로 편집합니다. 축 좌표의 고정 채널은 실수로 바꾸지 않도록 잠겨 있습니다.

결과 캐릭터를 선택하고 Graph Editor에서 수정할 본의 곡선을 선택하세요. 전신 인사의 팔은 IK 컨트롤러 위치 곡선을, 몸통과 기존 FK 동작은 각도 곡선을 편집합니다. 키를 좌우로 이동하면 타이밍, 위아래로 이동하면 위치 또는 회전량, 핸들을 조절하면 가감속을 변경할 수 있습니다. 양쪽 핸들이 독립적인 FREE 방식이므로 자세 진입과 이탈의 속도를 각각 조절할 수 있습니다. 각도 곡선의 축-각도 회전 모드는 유지하세요.

3초·60FPS·오른손 인사 2회 기준으로 전체 키가 **3,954개에서 63개**로 줄었습니다. 움직이는 각도 키는 44개이고, 나머지는 회전축 고정 15개와 IK 비활성화 4개입니다. 상완의 팔 올리기·유지·내리기는 4개 키로 구성됩니다. 같은 조건의 대기는 전체 28개 키입니다. FPS에 따라 키 수가 늘어나지 않으며, 반복 횟수를 늘릴 때만 필요한 전환점이 추가됩니다. 키는 동작 타이밍을 보존하기 위해 소수 프레임에도 놓일 수 있습니다.

기존 샘플러와 실제 Blender 평가 포즈를 259개 시점에서 비교했습니다. 위 인사 예제의 최대 회전 차이는 약 0.153°, 본 위치 차이는 0.000778 Blender 단위입니다. 반복 8회·최대 강도를 포함한 검사에서는 최대 회전 차이가 0.186° 미만이었습니다. 새 생성 결과부터 적용되며 이전에 확정한 Action의 키를 자동 삭제하지 않습니다.

저장소 루트에서 격리 프로필을 통해 핵심 기능과 재등록 검사를 실행합니다. Python 예외는 종료 코드 1로 전달됩니다.

```bash
bash scripts/dev_run.sh --background --python tests/blender_smoke.py
bash scripts/dev_run.sh --background --python tests/blender_reload.py
bash scripts/dev_run.sh --background --python tests/blender_operators.py
bash scripts/dev_run.sh --background --python tests/blender_curves.py
bash scripts/dev_run.sh --background --python tests/blender_natural.py
bash scripts/dev_run.sh --background --python tests/blender_arm_ik.py
bash scripts/dev_run.sh --background --python tests/blender_agent_ui.py
bash scripts/dev_run.sh --background --python tests/blender_motion_library.py
bash scripts/dev_run.sh --background --python tests/render_preview.py
bash scripts/dev_run.sh --python tests/gui_preview.py
python3 tests/test_agent_bridge.py
python3 tests/test_motion_library.py
```

실제 CLI 검사는 기존 Codex 계정의 사용량을 사용합니다. `python3 tests/agent_live.py`로 생성하고 `python3 tests/agent_live.py --refine`으로 현재 명세의 상대적 수정을 검사합니다. `blender_agent_ui.py`는 저장된 실제 응답이 있으면 사용하고, 없으면 `tests/fixtures/natural_wave_plan.json`을 사용합니다. 테스트의 비동기 UI 상태·취소 부분은 가짜 프로세스로 검사하며 CLI 호출 성공과 구분합니다.

전신 예제의 재로드·렌더·GUI 검사에는 macOS에서 다음처럼 파일명을 지정합니다.

```bash
CATANI_DEMO_NAME=CatAni_Natural_Wave_Demo.blend bash scripts/dev_run.sh --background --python tests/blender_reload.py --python tests/render_preview.py
CATANI_DEMO_NAME=CatAni_Natural_Wave_Demo.blend bash scripts/dev_run.sh --python tests/gui_preview.py
```

Windows에서는 같은 인자를 `scripts\dev_run.bat` 또는 `scripts\dev_run.ps1`에 전달합니다.

macOS Blender 5.2.0에서 대기·양손 흔들기, 동일 입력 재현, 취소 후 원본 상태 복원, UI 연산자, 저장 시 미리보기 취소, 등록 해제·재등록을 확인했습니다. 별도 프로세스에서 재로드한 대표 프레임의 포즈 최대 오차는 0이었습니다. 정면·측면 렌더와 실제 GUI의 패널 호출·프레임 재생도 검사했습니다. Windows는 실행기 정적 검사만 수행했습니다.

`artifacts/CatAni_Wave_Demo.blend`는 검사에서 생성한 기존 단순 인사 예제입니다. 전신 예제는 `CatAni_Natural_Wave_Demo.blend`입니다. `render_preview.py`는 정면·측면 이미지 12개를 만들며, `gui_preview.py`는 기본 화면 구성에서 결과를 재생한 후 검증용 Blender를 자동 종료합니다. 원본 샘플 파일에는 저장하지 않습니다.

초기 GUI 검증에서 콘솔로 비활성 VIEW_3D 공간의 `show_region_ui`를 변경하면 Blender 5.2 네이티브 충돌이 발생했습니다. 애드온은 해당 호출을 사용하지 않으며, GUI 검사는 타이머에서 활성 영역만 설정하도록 구성했습니다.

## 개발 자료

- [제품 구상](Blender/CatAni_Plan.md)
- [구현 계획](Blender/CatAni_Implementation_Plan.md)

## 패키징과 릴리즈 준비

배포 후보 버전은 **0.3.0**입니다. 이전 버전은 로컬 개발 이력이며 공개 릴리스가 아닙니다. Python 3.11 이상과 Blender 5.2.0 이상을 준비하고 저장소 루트에서 실행합니다.

```bash
python3 scripts/validate_release.py --tag v0.3.0
python3 scripts/run_tests.py
python3 scripts/package.py --tag v0.3.0
```

Windows에서는 `python3` 대신 `python`을 사용합니다. Blender 경로는 `BLENDER_BINARY` 또는 각 실행 명령의 `--blender`로 지정합니다. 전체 검사기는 임시 복사본과 독립 프로필에서 실행하므로 기존 개발 결과를 덮어쓰지 않습니다. 실시간 Codex 호출은 포함하지 않습니다.

`dist/catani-v0.3.0.zip`과 SHA-256 파일이 생성됩니다. 패키지에는 런타임 Python 파일, 매니페스트, GPL 라이선스와 기본 데모 BVH만 포함합니다. 샘플 `.blend`, 테스트, 개발 프로필, 계정 정보, 외부 모션 샘플은 포함하지 않습니다. 소스와 ZIP 모두 Blender 공식 Extension 검증을 거칩니다. 로컬 ZIP은 별도 검증용 Blender 프로필의 **Install from Disk**로 설치할 수 있습니다.

현재 macOS Blender 5.2.0에서 격리 회귀 검사 11개, 배포 무결성 검사 4개, 공식 소스·ZIP 검증을 통과했습니다. BVH는 합성 테스트 파일로 실제 Blender 가져오기를 확인했고, FBX는 인덱스·검색 경로만 검사했습니다. Windows/Linux 원격 CI와 실제 Pages 원격 설치는 아직 실행하지 않았습니다.

### GitHub 배포 구성

예정 저장소는 `zzamjak-cloud/CatAni-Blender`입니다. 현재는 로컬 Git과 워크플로 설정을 준비한 상태이며 공개 저장소·Release·Pages는 아직 생성하지 않았습니다.

| 워크플로 | 실행 조건 | 수행 내용 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | main push, PR, 수동 | 공식 Blender 체크섬 확인, Ubuntu/Windows 전체 회귀 검사, ZIP 검증 |
| `.github/workflows/release.yml` | 새 `v*` 태그 push | 동일 CI 성공 및 버전 일치 후 ZIP·SHA-256 Release 게시 |
| `.github/workflows/pages.yml` | Release 워크플로 성공, 수동 | 공개 정식 릴리스의 검증된 ZIP으로 공식 `server-generate` 실행 및 Pages 게시 |

실제 배포 단계에서는 공개 저장소 생성과 최초 push 후 GitHub Pages의 **Build and deployment → Source → GitHub Actions**를 설정합니다. 양쪽 OS의 원격 CI, Windows 개발 실행기, ZIP 설치 및 실제 재생을 확인한 뒤 사용하지 않은 `v0.3.0` 태그로 초기 릴리스를 시작합니다. 기존 태그나 릴리스를 덮어쓰지 않습니다. 이후 버전은 매니페스트와 엔진 버전·변경 이력을 함께 올립니다.

배포 후 사용할 원격 저장소 주소는 `https://zzamjak-cloud.github.io/CatAni-Blender/index.json`입니다. **아직 활성화된 설치 주소가 아닙니다.** Pages 게시 후 HTTP 응답·버전·ZIP 다운로드와 별도의 깨끗한 프로필에서 원격 설치를 확인해야 합니다.

사용자는 Blender **Preferences → Get Extensions → Repositories → Add Remote Repository**에 위 주소를 등록합니다. **Check for Updates on Startup**을 켜면 시작 시 업데이트를 확인하며 설치는 사용자가 승인합니다. 개발용 소스 연결 프로필과 사용자용 원격 설치 프로필을 분리합니다.
