#!/usr/bin/env bash
set -euo pipefail

die() {
    echo "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -DeviceSerial, --DeviceSerial, --device-serial VALUE
      Android device serial. Default: emulator-5554
  -Python, --Python, --python VALUE
      Python executable. Default: \${PYTHON:-python3}
  -ApkFileName, --ApkFileName, --apk-file-name VALUE
      APK file name under the default dataset directory. Default: WishShop.apk
  -ApkPath, --ApkPath, --apk-path VALUE
      Explicit APK path. Relative paths are resolved from this script directory.
  -OutputDir, --OutputDir, --output-dir VALUE
      Output directory. Default: <script-dir>/output/androlog/WishShop/dfs_greedy
  -Timeout, --Timeout, --timeout VALUE
      Timeout in seconds. Default: 1800
  -Interval, --Interval, --interval VALUE
      Event interval in seconds. Default: 2
  -Count, --Count, --count VALUE
      Event count. Default: 1000
  -h, --help
      Show this help.
EOF
}

require_value() {
    local option="$1"
    local value="${2-}"
    [[ -n "$value" ]] || die "$option requires a value."
}

is_blank() {
    [[ -z "${1//[[:space:]]/}" ]]
}

resolve_file_path() {
    local path="$1"
    local dir
    local base
    dir="$(dirname "$path")"
    base="$(basename "$path")"
    (cd "$dir" && printf '%s/%s\n' "$(pwd -P)" "$base")
}

check_command() {
    local command_name="$1"
    if [[ "$command_name" == */* ]]; then
        [[ -x "$command_name" ]] || die "Command is not executable: $command_name"
    else
        command -v "$command_name" >/dev/null 2>&1 || die "Command not found: $command_name"
    fi
}

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

DeviceSerial="emulator-5554"
Python="${PYTHON:-python3}"
ApkFileName="WishShop.apk"
ApkPath=""
OutputDir="$ScriptDir/output/androlog/WishShop/dfs_greedy"
Timeout=1800
Interval=2
Count=1000

while [[ $# -gt 0 ]]; do
    case "$1" in
        -DeviceSerial|--DeviceSerial|--device-serial)
            require_value "$1" "${2-}"
            DeviceSerial="$2"
            shift 2
            ;;
        --DeviceSerial=*|--device-serial=*)
            DeviceSerial="${1#*=}"
            shift
            ;;
        -Python|--Python|--python)
            require_value "$1" "${2-}"
            Python="$2"
            shift 2
            ;;
        --Python=*|--python=*)
            Python="${1#*=}"
            shift
            ;;
        -ApkFileName|--ApkFileName|--apk-file-name)
            require_value "$1" "${2-}"
            ApkFileName="$2"
            shift 2
            ;;
        --ApkFileName=*|--apk-file-name=*)
            ApkFileName="${1#*=}"
            shift
            ;;
        -ApkPath|--ApkPath|--apk-path)
            require_value "$1" "${2-}"
            ApkPath="$2"
            shift 2
            ;;
        --ApkPath=*|--apk-path=*)
            ApkPath="${1#*=}"
            shift
            ;;
        -OutputDir|--OutputDir|--output-dir)
            require_value "$1" "${2-}"
            OutputDir="$2"
            shift 2
            ;;
        --OutputDir=*|--output-dir=*)
            OutputDir="${1#*=}"
            shift
            ;;
        -Timeout|--Timeout|--timeout)
            require_value "$1" "${2-}"
            Timeout="$2"
            shift 2
            ;;
        --Timeout=*|--timeout=*)
            Timeout="${1#*=}"
            shift
            ;;
        -Interval|--Interval|--interval)
            require_value "$1" "${2-}"
            Interval="$2"
            shift 2
            ;;
        --Interval=*|--interval=*)
            Interval="${1#*=}"
            shift
            ;;
        -Count|--Count|--count)
            require_value "$1" "${2-}"
            Count="$2"
            shift 2
            ;;
        --Count=*|--count=*)
            Count="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

check_command "$Python"

ProjectRoot="$(cd "$ScriptDir/.." && pwd -P)"
DatasetApkDir="$ProjectRoot/ExperimentalDataset/apk-after-instrumentation/FSE-dataset-wcx-log"

if is_blank "$ApkPath"; then
    ResolvedApkPath="$DatasetApkDir/$ApkFileName"
else
    ResolvedApkPath="$ApkPath"
    if [[ "$ResolvedApkPath" != /* ]]; then
        ResolvedApkPath="$ScriptDir/$ResolvedApkPath"
    fi
fi

[[ -f "$ResolvedApkPath" ]] || die "APK not found: $ResolvedApkPath"
ResolvedApkPath="$(resolve_file_path "$ResolvedApkPath")"

ConfigPath="$ScriptDir/config.json"
[[ -f "$ConfigPath" ]] || die "config.json not found: $ConfigPath"

ConfigApiKey="$("$Python" - "$ConfigPath" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as file:
    value = json.load(file).get("ApiKey") or ""
print(str(value).strip())
PY
)"

if [[ -z "$ConfigApiKey" && -z "${DASHSCOPE_API_KEY:-}" && -z "${BAILIAN_API_KEY:-}" && -z "${GLM_API_KEY:-}" && -z "${ZHIPUAI_API_KEY:-}" ]]; then
    die "Set ApiKey in config.json or define DASHSCOPE_API_KEY/BAILIAN_API_KEY/GLM_API_KEY/ZHIPUAI_API_KEY before running this script."
fi

echo "[LLMDroid Androlog Mode] Using APK: $ResolvedApkPath"
echo "[LLMDroid Androlog Mode] Output dir: $OutputDir"

cd "$ScriptDir"
"$Python" "$ScriptDir/start.py" \
    -d "$DeviceSerial" \
    -a "$ResolvedApkPath" \
    -o "$OutputDir" \
    -timeout "$Timeout" \
    -interval "$Interval" \
    -count "$Count" \
    -policy dfs_greedy \
    -grant_perm \
    -keep_app \
    -code_coverage androlog
