param(
    [Parameter(Mandatory = $true)]
    [string]$DeviceSerial,

    [string]$Python = "D:\DesignSoftware\Python\python.exe",
    [string]$OutputDir = "$PSScriptRoot\output-tomato-glm",
    [int]$Timeout = 3600,
    [int]$Interval = 3,
    [int]$Count = 100000
)

$apkFile = Get-ChildItem -Path (Join-Path $PSScriptRoot "..") -Filter "*ToDo.apk" -File |
    Select-Object -First 1
$apkPath = if ($apkFile) { $apkFile.FullName } else { Join-Path $PSScriptRoot "..\TomatoToDo.apk" }

if (-not (Test-Path $apkPath)) {
    throw "APK not found: $apkPath"
}

$configPath = Join-Path $PSScriptRoot "config.json"
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json

if (-not $config.ApiKey -and -not $env:DASHSCOPE_API_KEY -and -not $env:BAILIAN_API_KEY -and -not $env:GLM_API_KEY -and -not $env:ZHIPUAI_API_KEY) {
    throw "Set ApiKey in config.json or define DASHSCOPE_API_KEY/BAILIAN_API_KEY/GLM_API_KEY/ZHIPUAI_API_KEY before running this script."
}

& $Python "$PSScriptRoot\start.py" `
    -d $DeviceSerial `
    -a $apkPath `
    -o $OutputDir `
    -timeout $Timeout `
    -interval $Interval `
    -count $Count `
    -keep_app `
    -keep_env `
    -policy dfs_greedy `
    -grant_perm `
    -code_coverage time
