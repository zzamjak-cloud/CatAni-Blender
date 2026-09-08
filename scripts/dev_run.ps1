# Windows PowerShell 5.1 호환 UTF-8 BOM 파일입니다.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$addonRoot = Join-Path $projectRoot 'catani'
$manifestPath = Join-Path $addonRoot 'blender_manifest.toml'
$blenderExecutable = $env:BLENDER_BINARY
if (-not $blenderExecutable) {
    $blenderCommand = Get-Command blender.exe -ErrorAction SilentlyContinue
    if ($blenderCommand) { $blenderExecutable = $blenderCommand.Source }
}
if (-not $blenderExecutable -or -not (Test-Path -LiteralPath $blenderExecutable -PathType Leaf)) {
    throw 'Blender 실행 파일 경로를 BLENDER_BINARY 환경 변수로 지정하세요.'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'CatAni 매니페스트를 찾을 수 없습니다.' }
$manifestText = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
if ($manifestText -notmatch '(?m)^id\s*=\s*"catani"\s*$') { throw '예상하지 못한 애드온 ID입니다.' }
$versionOutput = & $blenderExecutable --version
if ($LASTEXITCODE -ne 0 -or ($versionOutput -join "`n") -notmatch 'Blender ([0-9]+\.[0-9]+)') {
    throw 'Blender 버전을 확인하지 못했습니다.'
}
$blenderVersion = $Matches[1]
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
