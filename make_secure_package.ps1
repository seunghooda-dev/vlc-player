# 배포용 릴리스 폴더를 AES-256 암호(파일 목록까지 암호화) 7z로 묶는 스크립트
#
# 사용법:
#   $env:MASTERQC_ZIP_PW = '전달용암호'; .\make_secure_package.ps1
#   (암호를 환경변수로 주지 않으면 실행 중에 입력받는다. 암호는 파일/로그에 남기지 않는다.)
#
# 7-Zip이 필요하다. PATH나 표준 설치 경로에서 찾지 못하면 SEVENZIP 환경변수로 직접 지정한다.

[CmdletBinding()]
param(
    [string]$PackageDir = (Join-Path $PSScriptRoot 'release\MasterQC V.1.1'),
    [string]$OutputDir  = (Join-Path $PSScriptRoot 'release')
)

$ErrorActionPreference = 'Stop'

function Find-SevenZip {
    if ($env:SEVENZIP -and (Test-Path -LiteralPath $env:SEVENZIP)) { return $env:SEVENZIP }
    $cmd = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
        (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

$sevenZip = Find-SevenZip
if (-not $sevenZip) {
    Write-Host '[FAIL] 7-Zip을 찾을 수 없습니다.' -ForegroundColor Red
    Write-Host '  winget install --id 7zip.7zip 로 설치하거나,'
    Write-Host '  $env:SEVENZIP = "C:\경로\7z.exe" 로 직접 지정하세요.'
    exit 2
}

if (-not (Test-Path -LiteralPath $PackageDir)) {
    Write-Host "[FAIL] 릴리스 폴더가 없습니다: $PackageDir" -ForegroundColor Red
    Write-Host '  package_release.bat 또는 update_desktop_release.bat 을 먼저 실행하세요.'
    exit 3
}

if ($env:MASTERQC_ZIP_PW) {
    $password = $env:MASTERQC_ZIP_PW
} else {
    $secure = Read-Host -Prompt '전달용 암호 입력' -AsSecureString
    $password = [System.Net.NetworkCredential]::new('', $secure).Password
}
if ([string]::IsNullOrWhiteSpace($password)) {
    Write-Host '[FAIL] 암호가 비어 있습니다.' -ForegroundColor Red
    exit 4
}

$exePath = Join-Path $PackageDir 'MasterQC.exe'
$version = if (Test-Path -LiteralPath $exePath) {
    'v' + ((Get-Item -LiteralPath $exePath).VersionInfo.ProductVersion -replace '\.\d+$', '')
} else { 'vUNKNOWN' }

$stamp   = Get-Date -Format 'yyyyMMdd_HHmmss'
$outPath = Join-Path $OutputDir "MasterQC_$($version)_secure_$stamp.7z"
if (Test-Path -LiteralPath $outPath) { Remove-Item -LiteralPath $outPath -Force }

Write-Host '================================================'
Write-Host '  MasterQC - 암호 패키지 생성'
Write-Host '================================================'
Write-Host "  7-Zip : $sevenZip"
Write-Host "  대상   : $PackageDir"
Write-Host "  출력   : $outPath"
Write-Host ''

# -mhe=on 은 파일 이름 목록까지 암호화한다(암호 없이는 내용물 구성도 못 본다).
& $sevenZip a -t7z -mhe=on "-p$password" -mx=5 -bso0 -bsp0 -- $outPath "$PackageDir\*" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 7-Zip 압축 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 5
}

# 검증 1: 올바른 암호로 무결성 검사가 통과해야 한다.
& $sevenZip t "-p$password" -bso0 -bsp0 -- $outPath | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 무결성 검사 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 6
}

# 검증 2: 암호 없이는 목록조차 보이지 않아야 한다(-mhe=on 확인).
& $sevenZip l -p'' -bso0 -bsp0 -- $outPath 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host '[FAIL] 암호 없이 목록이 열립니다 — 헤더 암호화가 적용되지 않았습니다.' -ForegroundColor Red
    exit 7
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $outPath).Length / 1MB, 1)
Write-Host "[OK] 암호 패키지 생성 완료 ($sizeMb MB)"
Write-Host '  - AES-256, 파일 목록까지 암호화됨'
Write-Host '  - 받는 PC에도 7-Zip이 필요합니다(윈도우 탐색기로는 열 수 없음).'
Write-Host '  - 암호는 파일과 다른 경로로 전달하세요.'
exit 0
