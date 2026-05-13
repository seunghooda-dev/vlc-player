param(
    [string]$SetFile = "",
    [string]$Root = ""
)

$ErrorActionPreference = "Continue"

$AppName = "MXF QC Player"
$AppVersion = "V.1.0"
$PackageName = "$AppName $AppVersion"

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$Root = [System.IO.Path]::GetFullPath($Root)

if ([string]::IsNullOrWhiteSpace($SetFile)) {
    $SetFile = Join-Path $Root "BROADCAST_SAMPLE_SET.txt"
} elseif (-not [System.IO.Path]::IsPathRooted($SetFile)) {
    $SetFile = Join-Path $Root $SetFile
}
$SetFile = [System.IO.Path]::GetFullPath($SetFile)

$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
    $LocalAppData = $env:TEMP
}
$ReportDir = Join-Path $LocalAppData "$PackageName\reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Report = Join-Path $ReportDir "broadcast-sample-set-$Stamp.txt"

function Add-ReportLine {
    param([string]$Line = "")
    Add-Content -LiteralPath $Report -Encoding UTF8 -Value $Line
}

Write-Host "================================================"
Write-Host "  $PackageName - broadcast sample set validation"
Write-Host "================================================"
Write-Host ""
Write-Host "Sample set:"
Write-Host "  $SetFile"
Write-Host "Report:"
Write-Host "  $Report"
Write-Host ""

if (-not (Test-Path -LiteralPath $SetFile -PathType Leaf)) {
    Write-Host "[FAIL] Sample set file was not found."
    exit 2
}

$SmokeScript = Join-Path $Root "smoke_mxf_test.bat"
if (-not (Test-Path -LiteralPath $SmokeScript -PathType Leaf)) {
    Write-Host "[FAIL] smoke_mxf_test.bat was not found next to this script."
    exit 2
}

Set-Content -LiteralPath $Report -Encoding UTF8 -Value @(
    "$PackageName broadcast sample set validation",
    "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Root: $Root",
    "Sample set: $SetFile",
    "",
    "Result table",
    "------------",
    ""
)

$SampleCount = 0
$PassCount = 0
$FailCount = 0
$MissingCount = 0
$SetDir = Split-Path -Parent $SetFile

foreach ($Line in Get-Content -LiteralPath $SetFile -Encoding UTF8) {
    $Trimmed = $Line.Trim()
    if (-not $Trimmed) {
        continue
    }
    if ($Trimmed.StartsWith("#")) {
        continue
    }

    $Parts = $Line -split "\|", 3
    if ($Parts.Count -lt 2) {
        continue
    }
    $Label = $Parts[0].Trim()
    $Sample = $Parts[1].Trim()
    $Notes = if ($Parts.Count -ge 3) { $Parts[2].Trim() } else { "" }
    if (-not $Label -or -not $Sample) {
        continue
    }

    if (-not [System.IO.Path]::IsPathRooted($Sample)) {
        $Sample = Join-Path $SetDir $Sample
    }
    $Sample = [System.IO.Path]::GetFullPath($Sample)

    $SampleCount += 1
    Write-Host ""
    Write-Host "[$SampleCount] $Label"
    Write-Host "  $Sample"
    Add-ReportLine "------------------------------------------------------------"
    Add-ReportLine "Label: $Label"
    Add-ReportLine "Sample: $Sample"
    Add-ReportLine "Notes: $Notes"

    if (-not (Test-Path -LiteralPath $Sample -PathType Leaf)) {
        $FailCount += 1
        $MissingCount += 1
        Write-Host "  [FAIL] missing file"
        Add-ReportLine "[FAIL] $Label | missing | $Sample"
        Add-ReportLine "Result: FAIL missing file"
        continue
    }

    $CmdLine = '"' + $SmokeScript + '" "' + $Sample + '"'
    $Output = & $env:ComSpec /d /c $CmdLine 2>&1
    $Rc = $LASTEXITCODE
    foreach ($OutLine in $Output) {
        Add-ReportLine ([string]$OutLine)
    }
    if ($Rc -eq 0) {
        $PassCount += 1
        Write-Host "  [PASS]"
        Add-ReportLine "[PASS] $Label | smoke ok | $Sample"
        Add-ReportLine "Result: PASS"
    } else {
        $FailCount += 1
        Write-Host "  [FAIL] exit=$Rc"
        Add-ReportLine "[FAIL] $Label | exit=$Rc | $Sample"
        Add-ReportLine "Result: FAIL exit=$Rc"
    }
}

Add-ReportLine ""
Add-ReportLine "Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Add-ReportLine "Summary: total=$SampleCount pass=$PassCount fail=$FailCount missing=$MissingCount"

Write-Host ""
Write-Host "Summary:"
Write-Host "  total=$SampleCount pass=$PassCount fail=$FailCount missing=$MissingCount"
Write-Host "Report:"
Write-Host "  $Report"

if ($SampleCount -eq 0) {
    Write-Host ""
    Write-Host "[FAIL] No sample rows were found."
    exit 2
}

if ($FailCount -ne 0) {
    Write-Host ""
    Write-Host "[FAIL] One or more samples failed validation."
    exit 8
}

Write-Host ""
Write-Host "[PASS] Broadcast sample set validation completed."
exit 0
