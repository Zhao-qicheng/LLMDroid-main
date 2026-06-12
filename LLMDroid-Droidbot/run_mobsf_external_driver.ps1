param(
    [string]$DeviceSerial = "10.30.58.20:6556",
    [string]$ApkPath = "",
    [string]$OutputDir = "output-mobsf-external",
    [string]$Policy = "dfs_greedy",
    [ValidateSet("time", "androlog", "jacoco")]
    [string]$CodeCoverage = "time",
    [int]$Timeout = 3600,
    [int]$Interval = 3,
    [int]$Count = 100000
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location $ScriptDir
try {
    if ([string]::IsNullOrWhiteSpace($ApkPath)) {
        $DefaultApkDir = Join-Path $ScriptDir "..\input_apk"
        $Apk = Get-ChildItem -LiteralPath $DefaultApkDir -Filter "*.apk" | Select-Object -First 1
        if (-not $Apk) {
            throw "No APK file found in $DefaultApkDir. Pass -ApkPath explicitly."
        }
        $ResolvedApkPath = $Apk.FullName
    } else {
        $CandidateApkPath = $ApkPath
        if (-not [System.IO.Path]::IsPathRooted($CandidateApkPath)) {
            $CandidateApkPath = Join-Path (Get-Location) $CandidateApkPath
        }
        if (-not (Test-Path -LiteralPath $CandidateApkPath)) {
            throw "APK does not exist: $CandidateApkPath"
        }
        $ResolvedApkPath = (Resolve-Path -LiteralPath $CandidateApkPath).Path
    }

    Write-Host "[MobSF External Driver] Start MobSF dynamic analysis first, then keep the target app/emulator running."
    Write-Host "[MobSF External Driver] Using APK: $ResolvedApkPath"
    Write-Host "[MobSF External Driver] adb connect $DeviceSerial"
    adb connect $DeviceSerial

    Write-Host "[MobSF External Driver] Starting LLMDroid external driver"
    python start.py `
        -d $DeviceSerial `
        -a $ResolvedApkPath `
        -o $OutputDir `
        -external_driver `
        -policy $Policy `
        -code_coverage $CodeCoverage `
        -timeout $Timeout `
        -interval $Interval `
        -count $Count
} finally {
    Pop-Location
}
