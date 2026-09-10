# CatAni

CatAni 0.5.1은 공개 모션 캡처 데이터를 Blender 안에서 **검색하고, 목록에서 골라, 캐릭터에 바로 적용**하는 Extension입니다. 검색어 한 칸, 목록 하나, 적용 버튼 하나가 전체 흐름입니다. 폴더 경로·출처·이용 조건·체크섬·굽기 옵션 같은 정보는 모두 별도 팝업으로 옮겼습니다.

기본 카탈로그에는 CMU Graphics Lab Motion Capture Database 기반 BVH **485종**이 걷기·달리기·점프·춤·발차기·오르기 등 **35개 동작 분류**로 정리되어 있습니다. API 키나 유료 외부 모델은 필요하지 않습니다.

## 요구 사항

- **Blender 5.2.0 이상** (Extension 형식)
- 공개 모션을 내려받을 때만 인터넷 연결. API 키나 계정은 필요하지 않습니다.

## 설치

### 방법 1 · 원격 저장소 등록 (권장)

업데이트 알림을 받을 수 있는 방법입니다.

1. Blender에서 **Edit → Preferences → Get Extensions**를 엽니다.
2. 우측 상단의 **▼** → **Add Repository...**를 누릅니다. (또는 **Repositories** 목록 아래의 **＋** → **Add Remote Repository**)
3. **URL**에 다음 주소를 붙여넣습니다.

   ```text
   https://zzamjak-cloud.github.io/CatAni-Blender/index.json
   ```

4. **Check for Updates on Startup**을 켜고 대화상자를 확인합니다.
5. **Get Extensions**의 검색창에 `CatAni`를 입력하고 **Install**을 누릅니다.

새 버전이 나오면 Blender 시작 시 알려 주며, 갱신은 **Install Available Updates**로 사용자가 직접 승인합니다. 무인 자동 설치는 하지 않습니다.

> Blender가 온라인 접근 허용을 물어보면 허용해야 합니다. **Preferences → System → Network → Allow Online Access**에서도 켤 수 있습니다. 이 설정이 꺼져 있으면 저장소 목록은 갱신되지만 설치 단계에서 멈춥니다.

### 방법 2 · ZIP 직접 설치

1. [Releases](https://github.com/zzamjak-cloud/CatAni-Blender/releases/latest)에서 `catani-v0.5.1.zip`을 내려받습니다.
2. **Edit → Preferences → Get Extensions → ▼ → Install from Disk**를 누릅니다.
3. 내려받은 ZIP을 선택합니다.

같은 페이지의 `catani-v0.5.1.zip.sha256`으로 무결성을 확인할 수 있습니다.

```bash
shasum -a 256 -c catani-v0.5.1.zip.sha256   # macOS / Linux
```

이 방법으로 넣은 설치본은 Blender가 원격 갱신 대상으로 잡지 않습니다. 업데이트 알림을 쓰려면 방법 1을 사용하세요.

### 설치 확인

3D View에서 `N` 키로 사이드바를 열고 **CatAni** 탭이 보이면 완료입니다.

## 빠른 시작

3D View의 `N` 사이드바 → `CatAni` 탭 → `CatAni · 모션` 패널.

1. **검색** 칸에 `걷기`, `walk`, `점프`, `발차기` 같은 단어를 입력합니다. 입력하는 동안 목록이 바로 좁혀지며, 비우면 485종 전체가 보입니다. 한국어 분류 이름과 영어 원본 설명 단어가 모두 태그로 들어 있습니다.
2. **목록**에는 받아 둔 모션과 아직 받지 않은 공개 모션이 함께 나옵니다. 오른쪽에 `BVH`/`FBX`로 표시되면 로컬 파일이고, `받기 228KB`처럼 보이면 아직 내려받지 않은 공개 데이터입니다.
3. **대상**에 애니메이션을 적용할 캐릭터 아마추어를 지정합니다. 아마추어를 선택해 둔 상태면 비워 두어도 됩니다.
4. **적용**을 누릅니다. 아직 받지 않은 모션이면 먼저 내려받아 체크섬을 검증하고, 이어서 자동으로 적용까지 진행합니다.
5. 패널 아래 한 줄에 결과가 나옵니다. 예: `적용됨 · 부위 22/22 · 1~285f · 키 11,657개(-55%) · 방향 오차 1.28°`. 재생하면 캐릭터가 그 동작을 합니다.

`ⓘ 출처` 버튼은 선택 모션의 실제 다운로드 주소, git blob SHA-1, 출처, 이용 조건과 원문 링크를 팝업으로 보여 줍니다. `⚙ 상세` 버튼은 모션 폴더, 프레임 간격, 곡선 간소화 오차, 이동 적용, 바닥 관통 보정, 원본 리그 숨기기와 **마지막 적용 리포트**(본 매핑 표, 규격, 키 수와 감소율, 검증 오차, 실측 곡선 오차, 접지 보정량, 음소거한 NLA 트랙)를 담습니다.

내려받은 모션은 Blender 사용자 데이터 폴더(`.../datafiles/catani/motions`)에 쌓입니다. 설치된 애드온 폴더에는 쓰지 않으므로 읽기 전용 설치에서도 동작하며, 애드온에 동봉한 예제 모션은 항상 함께 검색됩니다.

## 적용이 실제로 무엇을 하는지

`적용`은 다음을 순서대로 수행합니다.

1. 모션 파일을 `CatAni 모션 원본` 컬렉션의 독립 리그로 가져옵니다. 같은 파일을 이미 가져왔다면 다시 읽지 않고 재사용합니다.
2. 두 리그의 본 이름을 표준 22개 부위(엉덩이·척추 3단·목·머리·양쪽 어깨/팔/팔뚝/손·양쪽 허벅지/정강이/발/발끝)에 맞춥니다. 자세한 규칙은 아래 **본 구조 차이 흡수**를 참고하세요.
3. 짝지은 본에 대해, 캐릭터 본이 **모션 본과 같은 방향을 보도록** 프레임마다 회전을 계산합니다. 레스트 자세가 서로 달라도(모션은 T 자세, 캐릭터는 팔을 내린 자세) 방향을 직접 맞추므로 자세 차이가 결과에 남지 않습니다.
4. 엉덩이 이동은 첫 프레임을 기준으로 재고 다리 길이 비율로 배율을 맞춥니다. 발이 바닥 아래로 내려가는 프레임에서는 필요한 만큼만 몸 전체를 올립니다(`바닥 관통 보정`, 끌 수 있음).
5. 결과를 새 Action에 **오토 클램프 베지어** 키로 굽습니다. 이때 `곡선 간소화 오차`(기본 0.5°) 안에서 키를 솎아내므로, 프레임마다 선형 키가 박힌 곡선이 아니라 손으로 고칠 수 있는 곡선이 나옵니다. 실제 CMU 걷기에서 키가 42,410개에서 19,063개로 줄고 방향 오차는 1.3° 안에 머물렀습니다. 0으로 두면 모든 프레임에 키를 남깁니다.
6. 기존 Action은 fake user로 보존하고, 구운 FK를 덮어쓰는 **활성 NLA 트랙은 음소거**하고 **IK 컨스트레인트 영향은 0으로 고정**합니다. 둘 다 리포트에 적히며 NLA 편집기에서 되돌릴 수 있습니다.
7. 마지막으로 구간 전체에 고르게 흩은 프레임에서 모션 본과 캐릭터 본의 방향 차이를 다시 재어 **검증 오차**로 보고합니다. 키가 놓이지 않은 프레임을 포함하므로 프레임 간격을 넓혔을 때의 보간 오차까지 드러납니다. 이 값이 0에 가까우면 실제로 적용된 것입니다. 간소화를 켜면 검증 프레임을 13개로 늘려 잽니다.
8. 손이나 머리가 바닥에 닿는 곡예 동작처럼 팔다리 비율 차이로 관통이 남으면 리포트에 깊이와 본 이름을 적습니다. 발 접지만 자동 보정하고, 팔 관통은 몸을 띄우지 않고 그대로 알립니다.

## 본 구조 차이 흡수

여러 경로로 받은 모션과 사용자 리깅은 본 이름 규칙이 서로 다릅니다. CatAni는 세 단계로 좁힙니다.

1. **이름 정규화** — 접두사(`mixamorig:`, `DEF-`, `ORG-`, `Bip01`), 구분자(`_ - . : |`), 대소문자, 장식 토큰(`fk`, `jnt`, `twist`)을 없애고 비교합니다. `upper_arm.L`, `upperarm_l`, `DEF-upper_arm.L`, `Bip01 L UpperArm`이 모두 같은 부위로 인식됩니다. `ik`는 남겨 두어 IK 컨트롤을 FK 본으로 잘못 잡지 않습니다.
2. **규격 표 대조** — CMU / cgspeed BVH, CMU ASF/AMC 원본 이름, Mixamo, Rigify / Player v1, Unreal / UE 스켈레톤, 3ds Max Biped, Daz Genesis 중 가장 많이 맞는 규격을 고릅니다.
3. **별칭 + 계층 검증 보완** — 규격으로 못 채운 부위는 별칭(`clavicle`/`collar`/`shoulder`, `calf`/`shin`/`tibia`, `ball`/`toebase`/`toes` 등)으로 찾고, 후보가 이미 확정된 부모 부위의 자손인지 확인한 뒤에만 받아들입니다. 그래서 `hip`처럼 엉덩이와 허벅지 양쪽에 쓰이는 이름도 엉뚱한 자리에 들어가지 않습니다.

세 단계로도 3개 부위를 못 채우면 이름이 완전히 같은 본만 잇고, 그것도 안 되면 지원 규격과 캐릭터 본 예시를 담은 오류를 냅니다. 부분만 맞을 때는 적용을 막지 않고 커버리지를 상태 줄과 리포트에 표시하며, 60% 미만이면 경고로 보고합니다.

검사에서 Unreal, Mixamo, 3ds Max Biped, Daz Genesis, CMU ASF/AMC, Rigify DEF- 접두사, 그리고 규격 표에 없는 임의 이름(`Waist`/`TorsoLower`/`Left_UpArm` 등) 7종 리그 모두 22개 부위를 인식하고 방향 오차 0.0000°로 적용했습니다.

직접 보유한 BVH/FBX도 `⚙ 상세`의 모션 폴더 아래에 넣으면 같은 목록에서 검색됩니다. `motions.json`으로 이름·태그·설명을 붙일 수 있습니다.

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

## 공개 데이터와 카탈로그

카탈로그는 [CMU Graphics Lab Motion Capture Database](https://mocap.cs.cmu.edu/)의 BVH 변환본을 사용합니다. 원본 데이터는 CMU에서 제공하고, BVH 변환본은 cgspeed 변환본을 미러한 [`una-dinosauria/cmu-mocap`](https://github.com/una-dinosauria/cmu-mocap) 저장소의 **고정 리비전**에서 내려받습니다.

`catani/motion_catalog.json`은 `scripts/build_catalog.py`가 생성합니다. 이 스크립트는 CMU 공식 설명 인덱스(`cmu-mocap-index-text.txt`)와 고정 리비전의 git 트리를 받아 동작 분류별로 선별하고, HTTP Range 요청으로 각 BVH 머리말의 **실제 프레임 수와 FPS**를 읽어 기록합니다. 항목마다 정확한 바이트 크기와 **git blob SHA-1**이 들어 있어, 내려받은 파일이 그 리비전의 내용과 같은지 로컬에서 확인할 수 있습니다. 애드온은 크기·해시·BVH 머리말을 모두 검증한 뒤에만 파일을 등록하고, 검증에 실패하면 임시 파일까지 지웁니다. 카탈로그를 갱신할 때만 다음을 실행합니다.

```bash
python3 scripts/build_catalog.py
```

동작 분류는 35개입니다: 걷기, 느린 걷기, 달리기, 조깅, 대기, 방향 전환, 옆걸음, 뒷걸음, 점프, 한발 뛰기, 계단, 오르기, 기기, 살금살금, 앉기, 일어서기, 춤, 발레, 스트레칭, 발차기, 펀치, 손 인사, 몸짓, 집어 들기, 운반, 던지기, 농구, 구기 운동, 수영 동작, 균형 잡기, 넘어짐, 밀고 당기기, 험한 지형, 생활 동작, 탈것.

CMU 데이터는 연구와 상업 제품에 사용할 수 있으나, 변환본을 포함한 모션 데이터 자체를 재판매하지 않아야 합니다. `ⓘ 출처` 팝업이 출처와 이용 조건 링크를 함께 표시합니다.

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
bash scripts/dev_run.sh --background --python tests/blender_retarget.py
bash scripts/dev_run.sh --background --python tests/blender_rig_variants.py
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

macOS Blender 5.2.0에서 통합 목록·즉시 검색, 다운로드 후 자동 적용, 22부위 리타게팅, 리그 규격 7종 인식, 주 패널 단순화 계약, ZIP만의 독립 런타임, 보조 절차 동작, 저장 시 미리보기 취소, 등록 해제·재등록을 확인했습니다. Windows는 실행기 정적 검사만 수행했습니다.

`blender_retarget.py`는 22개 관절을 가진 합성 CMU 규격 BVH를 실제로 가져와 캐릭터에 굽고, 모든 프레임에서 본 방향 오차가 0.5° 미만인지, 발이 바닥을 파고들지 않는지, 접지 보정을 끄면 첫 프레임 엉덩이가 레스트와 정확히 같은지, NLA와 IK가 결과를 덮지 않는지, 프레임 간격이 키 수에 반영되는지, 본 이름이 맞지 않는 리그가 거부되는지를 검사합니다. 곡선 간소화를 켠 경로도 따로 검사합니다: 키가 절반 이하로 줄고, 모든 키가 오토 클램프 베지어이고, 한 부위의 쿼터니언 4채널 키 위치가 일치하고, 모든 프레임의 방향 오차가 3° 미만이며 발이 바닥 아래로 내려가지 않는지 확인합니다.

`blender_rig_variants.py`는 Unreal, Mixamo, 3ds Max Biped, Daz Genesis, CMU ASF/AMC, Rigify DEF- 접두사, 규격 밖 임의 이름까지 7종 리그를 만들어 22개 부위 인식과 적용, 방향 오차를 검사합니다.

실제 CMU 데이터로는 걷기·달리기·점프·대기·앉기·춤·발차기·펀치·오르기·기기·손 인사·운반·던지기·계단·뒷걸음·방향 전환 **16개 동작 분류**를 내려받아 적용했습니다. 전부 22/22 부위 매핑, 방향 오차 0.000°, 실패 0건입니다. 그 과정에서 프레임 간격을 넓혔을 때 검증이 보간 오차를 놓치던 문제와 발 바닥 관통을 찾아 고쳤습니다. 손이 바닥을 짚는 곡예 동작(재주넘기 발차기)은 팔다리 비율 차이로 관통이 남으며, 리포트에 깊이와 본 이름으로 보고합니다.

`artifacts/CatAni_Wave_Demo.blend`는 보조 절차 동작 검사에서 생성하는 예제입니다. `render_preview.py`는 정면·측면 이미지를 만들며, `gui_preview.py`는 기본 화면 구성에서 결과를 재생한 후 검증용 Blender를 자동 종료합니다. 원본 샘플 파일에는 저장하지 않습니다.

초기 GUI 검증에서 콘솔로 비활성 VIEW_3D 공간의 `show_region_ui`를 변경하면 Blender 5.2 네이티브 충돌이 발생했습니다. 애드온은 해당 호출을 사용하지 않으며, GUI 검사는 타이머에서 활성 영역만 설정하도록 구성했습니다.

## 개발 자료

- [제품 구상](Blender/CatAni_Plan.md)
- [구현 계획](Blender/CatAni_Implementation_Plan.md)

## 패키징과 릴리즈 준비

현재 공개 버전은 **0.5.1**입니다. 새 버전을 준비할 때는 Python 3.11 이상과 Blender 5.2.0 이상을 갖추고 저장소 루트에서 실행합니다.

```bash
python3 scripts/validate_release.py --tag v0.5.1
python3 scripts/run_tests.py
python3 scripts/package.py --tag v0.5.1
```

Windows에서는 `python3` 대신 `python`을 사용합니다. Blender 경로는 `BLENDER_BINARY` 또는 각 실행 명령의 `--blender`로 지정합니다. 전체 검사기는 임시 복사본과 독립 프로필에서 실행하므로 기존 개발 결과를 덮어쓰지 않습니다. 실제 CMU 다운로드는 기본 검사에 포함하지 않습니다.

`dist/catani-v0.5.1.zip`과 SHA-256 파일이 생성됩니다. 패키지에는 런타임 Python 파일, 매니페스트, GPL 라이선스와 기본 데모 BVH만 포함합니다. 샘플 `.blend`, 테스트, 개발 프로필, 계정 정보, 다운로드된 CMU 모션 파일은 포함하지 않습니다. 소스와 ZIP 모두 Blender 공식 Extension 검증을 거칩니다. 로컬 ZIP은 별도 검증용 Blender 프로필의 **Install from Disk**로 설치할 수 있습니다.

macOS Blender 5.2.0 로컬, 그리고 GitHub Actions의 Ubuntu·Windows 원격 CI에서 격리 회귀 검사 10개, 배포 무결성 검사 4개, ZIP 독립 런타임 검증을 모두 통과했습니다. BVH는 합성 테스트 파일과 실제 CMU 데이터로 Blender 가져오기·리타게팅을 확인했고, FBX는 인덱스·검색 경로만 검사했습니다. Pages 원격 저장소 등록·동기화·설치·업데이트는 깨끗한 인수 프로필에서 실제로 확인했습니다.

### GitHub 배포 구성

공개 저장소는 [`zzamjak-cloud/CatAni-Blender`](https://github.com/zzamjak-cloud/CatAni-Blender)입니다. `v0.5.0`과 `v0.5.1` Release, GitHub Pages 원격 저장소가 모두 게시되어 있습니다.

| 워크플로 | 실행 조건 | 수행 내용 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | main push, PR, 수동 | 공식 Blender 체크섬 확인, Ubuntu/Windows 전체 회귀 검사, ZIP 검증 |
| `.github/workflows/release.yml` | 새 `v*` 태그 push | 동일 CI 성공 및 버전 일치 후 ZIP·SHA-256 Release 게시 |
| `.github/workflows/pages.yml` | Release 워크플로 성공, 수동 | 공개 정식 릴리스의 검증된 ZIP으로 공식 `server-generate` 실행 및 Pages 게시 |

저장소를 처음 만들 때는 push 후 GitHub Pages의 **Build and deployment → Source → GitHub Actions**를 한 번 설정해야 합니다. 이 설정 전에는 Pages 워크플로의 빌드 단계는 성공하고 배포 단계만 404로 실패합니다. 이후 버전은 매니페스트와 엔진 버전·변경 이력을 함께 올리고, 새 `v*` 태그만 push합니다. 기존 태그나 릴리스는 덮어쓰지 않습니다.

사용자 설치 방법은 문서 상단의 [설치](#설치)에 있습니다. 원격 저장소 주소는 `https://zzamjak-cloud.github.io/CatAni-Blender/index.json`입니다.

깨끗한 인수 프로필에서 다음을 확인했습니다: 저장소 등록 → 동기화(원격이 `0.5.0`·`0.5.1` 두 버전을 알림) → 0.5.0 설치 → 0.5.1로 교체 → 카탈로그 485종 로드 → 한국어·영어 검색(`발차기` 14건, `walk` 130건, `점프` 14건) → 동봉 예제로 실제 리타게팅. Release 자산의 SHA-256은 `index.json`에 적힌 값과 실제 다운로드 바이트에서 모두 일치했습니다.

개발용 소스 연결 프로필, 사용자용 원격 설치 프로필, 배포 인수 프로필은 서로 분리해 씁니다.
