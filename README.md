# CatAni

CatAni 0.3.0은 실제 모션 캡처 샘플을 내려받아 Blender 안에서 검색하고 가져오는 Extension입니다. 이전의 자연어 JSON 명세 생성 방식은 제거했습니다. 자연스러운 인체 동작은 직접 절차 코드로 새로 만드는 대신, 공개 BVH/FBX 모션 데이터를 라이브러리로 쌓고 리타게팅 기준으로 사용하는 방향입니다.

현재 기본 카탈로그에는 CMU Graphics Lab Motion Capture Database 기반 BVH 3개가 들어 있습니다. 애드온은 선택한 항목을 HTTPS로 내려받고, SHA-256 체크섬을 검증한 뒤 `motions/motions.json`에 출처·이용 조건·태그를 기록합니다. API 키나 유료 외부 모델은 필요하지 않습니다.

## 모션 라이브러리 사용

1. 개발 실행기로 Blender를 열고 3D View의 `N` 사이드바에서 `CatAni` → `CatAni · 모션 라이브러리` 패널을 엽니다.
2. **공개 모션 받기 · CMU BVH** 영역에서 `CMU · 손 인사`, `CMU · 걷기`, `CMU · 기다리기` 중 하나를 받습니다.
3. 다운로드가 끝나면 자동으로 목록이 갱신됩니다. 검색어를 비우면 현재 폴더의 전체 모션을 보여줍니다.
4. 검색 결과에서 모션을 선택하고 **선택 모션 가져오기**를 누릅니다.
5. 가져온 모션은 `CatAni 모션 원본` 컬렉션의 독립 리그와 Action으로 생성됩니다. 현재 캐릭터에 바로 덮어쓰지 않으며, 자동 리타게팅은 다음 구현 단계입니다.

직접 보유한 BVH/FBX도 `motions/` 아래에 넣으면 같은 목록에서 검색할 수 있습니다. `motions.json` 예시는 다음과 같습니다.

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

## 공개 데이터

기본 다운로드 카탈로그는 CMU Graphics Lab Motion Capture Database의 BVH 변환본을 사용합니다. 원본 데이터는 CMU에서 제공하고, BVH 변환본은 cgspeed 변환본을 미러한 `una-dinosauria/cmu-mocap` 저장소의 고정 리비전에서 내려받습니다. CatAni는 다운로드 파일 크기와 SHA-256을 확인한 뒤 등록합니다.

카탈로그에는 현재 다음 항목이 있습니다.

| 항목 | 태그 | 크기 |
| --- | --- | --- |
| `CMU · 손 인사` | `wave`, `hello`, `greeting` | 약 228 KB |
| `CMU · 걷기` | `walk`, `walking` | 약 891 KB |
| `CMU · 기다리기` | `idle`, `waiting` | 약 571 KB |

CMU 데이터는 연구와 상업 제품에 사용할 수 있으나, 변환본을 포함한 모션 데이터 자체를 재판매하지 않아야 합니다. 애드온 UI는 출처와 이용 조건 링크를 함께 표시합니다.

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

1. 개발 실행기로 `Blender/Player_Animation_01.blend`를 엽니다.
2. 3D View의 N 사이드바에서 `CatAni` → `CatAni · 모션 라이브러리` 패널을 엽니다.
3. 모션 폴더를 확인하고 **공개 모션 받기**에서 필요한 CMU BVH를 내려받습니다.
4. 검색어를 입력하거나 비운 상태로 **모션 목록 갱신**을 누릅니다.
5. 원하는 모션을 선택하고 **선택 모션 가져오기**를 누릅니다.
6. 가져온 원본 리그의 Action을 재생해 확인합니다.

하단의 **보조 · 절차 동작 비교** 패널은 기존 샘플 리그에서 `idle`과 `wave`만 빠르게 비교하기 위한 부가 기능입니다. 새 동작 제작의 기본 흐름은 모션 라이브러리입니다.

## 로컬 검증

### Graph Editor에서 동작 수정

0.1.1부터 매 프레임 키를 생성하지 않습니다. 주요 포즈와 반복 동작의 전환점에만 키를 만들고, Bézier 곡선과 좌우 핸들로 중간 움직임을 연결합니다. 각 본의 움직임은 축-각도 회전의 **각도 채널 하나**(`rotation_axis_angle[0]`)로 편집합니다. 축 좌표의 고정 채널은 실수로 바꾸지 않도록 잠겨 있습니다.

보조 절차 동작 결과 캐릭터를 선택하고 Graph Editor에서 수정할 본의 곡선을 선택하세요. 키를 좌우로 이동하면 타이밍, 위아래로 이동하면 회전량, 핸들을 조절하면 가감속을 변경할 수 있습니다. 양쪽 핸들이 독립적인 FREE 방식이므로 자세 진입과 이탈의 속도를 각각 조절할 수 있습니다. 각도 곡선의 축-각도 회전 모드는 유지하세요.

3초·60FPS·오른손 손 흔들기 2회 기준으로 전체 키는 63개입니다. 움직이는 각도 키는 44개이고, 나머지는 회전축 고정 15개와 IK 비활성화 4개입니다. 같은 조건의 대기는 전체 28개 키입니다. FPS에 따라 키 수가 늘어나지 않으며, 반복 횟수를 늘릴 때만 필요한 전환점이 추가됩니다.

기존 샘플러와 실제 Blender 평가 포즈를 259개 시점에서 비교했습니다. 위 인사 예제의 최대 회전 차이는 약 0.153°, 본 위치 차이는 0.000778 Blender 단위입니다. 반복 8회·최대 강도를 포함한 검사에서는 최대 회전 차이가 0.186° 미만이었습니다. 새 생성 결과부터 적용되며 이전에 확정한 Action의 키를 자동 삭제하지 않습니다.

저장소 루트에서 격리 프로필을 통해 핵심 기능과 재등록 검사를 실행합니다. Python 예외는 종료 코드 1로 전달됩니다.

```bash
bash scripts/dev_run.sh --background --python tests/blender_smoke.py
bash scripts/dev_run.sh --background --python tests/blender_reload.py
bash scripts/dev_run.sh --background --python tests/blender_operators.py
bash scripts/dev_run.sh --background --python tests/blender_curves.py
bash scripts/dev_run.sh --background --python tests/blender_ui_contract.py
bash scripts/dev_run.sh --background --python tests/blender_motion_library.py
bash scripts/dev_run.sh --background --python tests/render_preview.py
bash scripts/dev_run.sh --python tests/gui_preview.py
python3 tests/test_motion_library.py
python3 tests/test_motion_download.py
```

기본 회귀 검사는 네트워크를 사용하지 않습니다. 실제 CMU 다운로드 검사는 명시적으로 허용할 때만 실행합니다.

```bash
python3 tests/motion_download_live.py --allow-network
```

Windows에서는 같은 인자를 `scripts\dev_run.bat` 또는 `scripts\dev_run.ps1`에 전달합니다.

macOS Blender 5.2.0에서 모션 라이브러리 UI, 제거된 JSON/에이전트 UI 회귀, 합성 BVH 실제 가져오기, ZIP만의 독립 런타임, 보조 절차 동작, 저장 시 미리보기 취소, 등록 해제·재등록을 확인했습니다. Windows는 실행기 정적 검사만 수행했습니다.

`artifacts/CatAni_Wave_Demo.blend`는 보조 절차 동작 검사에서 생성하는 예제입니다. `render_preview.py`는 정면·측면 이미지를 만들며, `gui_preview.py`는 기본 화면 구성에서 결과를 재생한 후 검증용 Blender를 자동 종료합니다. 원본 샘플 파일에는 저장하지 않습니다.

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

Windows에서는 `python3` 대신 `python`을 사용합니다. Blender 경로는 `BLENDER_BINARY` 또는 각 실행 명령의 `--blender`로 지정합니다. 전체 검사기는 임시 복사본과 독립 프로필에서 실행하므로 기존 개발 결과를 덮어쓰지 않습니다. 실제 CMU 다운로드는 기본 검사에 포함하지 않습니다.

`dist/catani-v0.3.0.zip`과 SHA-256 파일이 생성됩니다. 패키지에는 런타임 Python 파일, 매니페스트, GPL 라이선스와 기본 데모 BVH만 포함합니다. 샘플 `.blend`, 테스트, 개발 프로필, 계정 정보, 다운로드된 CMU 모션 파일은 포함하지 않습니다. 소스와 ZIP 모두 Blender 공식 Extension 검증을 거칩니다. 로컬 ZIP은 별도 검증용 Blender 프로필의 **Install from Disk**로 설치할 수 있습니다.

현재 macOS Blender 5.2.0에서 격리 회귀 검사 8개, 배포 무결성 검사 4개, ZIP 독립 런타임 검증을 통과했습니다. BVH는 합성 테스트 파일로 실제 Blender 가져오기를 확인했고, FBX는 인덱스·검색 경로만 검사했습니다. Windows/Linux 원격 CI와 실제 Pages 원격 설치는 아직 실행하지 않았습니다.

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
