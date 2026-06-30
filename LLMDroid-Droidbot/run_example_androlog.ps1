param(
    [string]$DeviceSerial = '10.30.58.20:6555',
    # [string]$DeviceSerial = 'emulator-5554',
    [string]$Adb = "adb",
    [string]$Python = "D:\DesignSoftware\Python\python.exe",
    [string]$ApkFileName = "Wikipedia.apk",
    [string]$ApkPath = "",
    [string]$OutputDir = "$PSScriptRoot\output\androlog\Wikipedia\dfs_greedy",
    [int]$Timeout = 1800,
    [int]$Interval = 3,
    [int]$Count = 1000
)

$projectRoot = Join-Path $PSScriptRoot ".."
$datasetApkDir = Join-Path $projectRoot "ExperimentalDataset\apk-after-instrumentation\FSE-dataset-wcx-log"

if ([string]::IsNullOrWhiteSpace($ApkPath)) {
    $resolvedApkPath = Join-Path $datasetApkDir $ApkFileName
} else {
    $resolvedApkPath = $ApkPath
    if (-not [System.IO.Path]::IsPathRooted($resolvedApkPath)) {
        $resolvedApkPath = Join-Path $PSScriptRoot $resolvedApkPath
    }
}

if (-not (Test-Path -LiteralPath $resolvedApkPath)) {
    throw "APK not found: $resolvedApkPath"
}

$resolvedApkPath = (Resolve-Path -LiteralPath $resolvedApkPath).Path

$configPath = Join-Path $PSScriptRoot "config.json"
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json

if (-not $config.ApiKey -and -not $env:DASHSCOPE_API_KEY -and -not $env:BAILIAN_API_KEY -and -not $env:GLM_API_KEY -and -not $env:ZHIPUAI_API_KEY) {
    throw "Set ApiKey in config.json or define DASHSCOPE_API_KEY/BAILIAN_API_KEY/GLM_API_KEY/ZHIPUAI_API_KEY before running this script."
}

if ($DeviceSerial -match '^\d{1,3}(\.\d{1,3}){3}:\d+$') {
    Write-Host "[ADB] Connecting to remote emulator: $DeviceSerial"
    & $Adb connect $DeviceSerial | Write-Host
}

$adbDevices = & $Adb devices
if (-not ($adbDevices -match [regex]::Escape($DeviceSerial))) {
    throw "ADB device not found: $DeviceSerial. Current adb devices:`n$($adbDevices -join [Environment]::NewLine)"
}

Write-Host "[LLMDroid Time Mode] Using APK: $resolvedApkPath"
Write-Host "[LLMDroid Time Mode] Output dir: $OutputDir"

& $Python "$PSScriptRoot\start.py" `
    -d $DeviceSerial `
    -a $resolvedApkPath `
    -o $OutputDir `
    -timeout $Timeout `
    -interval $Interval `
    -count $Count `
    -policy dfs_greedy `
    -grant_perm `
    -keep_app `
    -code_coverage androlog
