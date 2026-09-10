# Windows PowerShell 5.1 호환 UTF-8 BOM 파일입니다.
$ErrorActionPreference = 'Stop'
# 파이프나 리다이렉트로 넘길 때 한국어 메시지가 깨지지 않도록 출력을 UTF-8로 맞춘다.
# 콘솔이 없는 환경에서는 설정이 실패할 수 있으므로 무시한다.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
try { [Console]::OutputEncoding = $OutputEncoding } catch { }
$projectRoot = Split-Path -Parent $PSScriptRoot
$addonRoot = Join-Path $projectRoot 'catani'
$manifestPath = Join-Path $addonRoot 'blender_manifest.toml'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'CatAni 매니페스트를 찾을 수 없습니다.' }
$manifestText = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
if ($manifestText -notmatch '(?m)^id\s*=\s*"catani"\s*$') { throw '예상하지 못한 애드온 ID입니다.' }
if ($manifestText -notmatch '(?m)^blender_version_min\s*=\s*"([0-9]+(?:\.[0-9]+){0,2})"') {
    throw '매니페스트에서 blender_version_min을 읽지 못했습니다.'
}
$minimumVersion = [version]$Matches[1]

function Read-BlenderVersion {
    # 실행 파일에서 실제 버전을 읽는다. 폴더 이름은 실제 버전과 다를 수 있다.
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { $output = & $Path --version 2>$null } catch { return $null }
    if ($LASTEXITCODE -ne 0) { return $null }
    if (($output -join "`n") -notmatch 'Blender ([0-9]+)\.([0-9]+)(?:\.([0-9]+))?') { return $null }
    $patch = $Matches[3]
    if (-not $patch) { $patch = '0' }
    return [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], $patch)
}

function Find-BlenderInstall {
    # PATH와 흔한 설치 위치를 훑어 최소 버전을 만족하는 가장 높은 버전을 고른다.
    # 4.3과 5.2가 함께 깔린 환경에서 낮은 버전이 먼저 잡히면 애드온이 로드되지 않으므로
    # 후보를 모두 모은 뒤 실제 버전으로 비교한다.
    param([version]$Minimum)
    $searchRoots = New-Object System.Collections.Generic.List[string]
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if ($base) { $searchRoots.Add((Join-Path $base 'Blender Foundation')) }
    }
    if (${env:ProgramFiles(x86)}) { $searchRoots.Add((Join-Path ${env:ProgramFiles(x86)} 'Steam\steamapps\common')) }
    # 압축을 풀어 쓰는 포터블 설치는 드라이브 상단이나 도구 폴더에 놓이는 경우가 많다.
    foreach ($drive in [IO.DriveInfo]::GetDrives()) {
        if ($drive.DriveType -ne 'Fixed' -or -not $drive.IsReady) { continue }
        $root = $drive.RootDirectory.FullName
        $searchRoots.Add($root)
        foreach ($leaf in @('Tools', 'Apps', 'Programs', 'Program Files')) {
            $searchRoots.Add((Join-Path $root $leaf))
        }
    }
    $found = New-Object System.Collections.Generic.List[string]
    $command = Get-Command blender.exe -ErrorAction SilentlyContinue
    if ($command) { $found.Add($command.Source) }
    foreach ($searchRoot in $searchRoots) {
        if (-not (Test-Path -LiteralPath $searchRoot -PathType Container)) { continue }
        $children = Get-ChildItem -LiteralPath $searchRoot -Directory -Filter 'Blender*' -ErrorAction SilentlyContinue
        foreach ($child in $children) { $found.Add((Join-Path $child.FullName 'blender.exe')) }
    }
    $best = $null
    $tooOld = New-Object System.Collections.Generic.List[string]
    foreach ($path in ($found | Select-Object -Unique)) {
        $version = Read-BlenderVersion -Path $path
        if (-not $version) { continue }
        if ($version -lt $Minimum) { $tooOld.Add("$path ($version)"); continue }
        if (-not $best -or $version -gt $best.Version) {
            $best = [pscustomobject]@{ Path = $path; Version = $version }
        }
    }
    return [pscustomobject]@{ Best = $best; TooOld = $tooOld }
}

$blenderExecutable = $env:BLENDER_BINARY
if ($blenderExecutable) {
    if (-not (Test-Path -LiteralPath $blenderExecutable -PathType Leaf)) {
        throw "BLENDER_BINARY가 가리키는 파일이 없습니다: $blenderExecutable"
    }
    $blenderVersionValue = Read-BlenderVersion -Path $blenderExecutable
    if (-not $blenderVersionValue) { throw 'Blender 버전을 확인하지 못했습니다.' }
    if ($blenderVersionValue -lt $minimumVersion) {
        # 명시 지정은 그대로 존중하되, 애드온이 로드되지 않을 수 있음을 알린다.
        Write-Warning "Blender $blenderVersionValue 는 매니페스트 최소 버전 $minimumVersion 보다 낮습니다."
    }
} else {
    $search = Find-BlenderInstall -Minimum $minimumVersion
    if ($search.Best) {
        $blenderExecutable = $search.Best.Path
        $blenderVersionValue = $search.Best.Version
        Write-Host "Blender 자동 감지: $blenderExecutable ($blenderVersionValue)"
    } elseif ($search.TooOld.Count -gt 0) {
        throw ("Blender $minimumVersion 이상이 필요합니다. 찾은 설치: " + ($search.TooOld -join ', ') +
               ". BLENDER_BINARY 환경 변수로 직접 지정하세요.")
    } else {
        throw 'Blender 실행 파일을 찾지 못했습니다. BLENDER_BINARY 환경 변수로 경로를 지정하세요.'
    }
}
$blenderVersion = "{0}.{1}" -f $blenderVersionValue.Major, $blenderVersionValue.Minor
$previousResources = $env:BLENDER_USER_RESOURCES
$previousSource = $env:CATANI_DEV_SOURCE
try {
$env:BLENDER_USER_RESOURCES = Join-Path $projectRoot ".blender-dev\CatAniDev\$blenderVersion"
$env:CATANI_DEV_SOURCE = $addonRoot
$extensionRoot = Join-Path $env:BLENDER_USER_RESOURCES 'extensions\user_default'
$addonLink = Join-Path $extensionRoot 'catani'
New-Item -ItemType Directory -Path $extensionRoot -Force | Out-Null
$existingLink = Get-Item -LiteralPath $addonLink -Force -ErrorAction SilentlyContinue
if ($existingLink) {
    if (-not ($existingLink.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "기존 파일 또는 폴더를 보호하기 위해 중단합니다: $addonLink"
    }
    if ($existingLink.LinkType -notin @('Junction', 'SymbolicLink')) {
        throw "지원하지 않는 링크를 보호하기 위해 중단합니다: $addonLink"
    }
    if ([IO.Path]::GetFullPath([string]$existingLink.Target) -ne [IO.Path]::GetFullPath($addonRoot)) {
        [IO.Directory]::Delete($addonLink)
        $existingLink = $null
    }
}
if (-not $existingLink) { New-Item -ItemType Junction -Path $addonLink -Target $addonRoot | Out-Null }
Write-Host "CatAni 개발 프로필: $env:BLENDER_USER_RESOURCES"
& $blenderExecutable --disable-autoexec --python-exit-code 1 --python (Join-Path $PSScriptRoot 'dev_bootstrap.py') @args
$blenderExitCode = $LASTEXITCODE
} finally {
    $env:BLENDER_USER_RESOURCES = $previousResources
    $env:CATANI_DEV_SOURCE = $previousSource
}
exit $blenderExitCode
