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
      Android device serial. Default: 10.30.58.20:6555
  -Python, --Python, --python VALUE
      Python executable. Default: \$PYTHON, then active conda python, then python/python3
  -ApkPath, --ApkPath, --apk-path VALUE
      Explicit APK path. If omitted, the first APK in ../input_apk is used.
  -OutputDir, --OutputDir, --output-dir VALUE
      Output directory. Default: output-mobsf-external
  -Policy, --Policy, --policy VALUE
      Input policy. Default: dfs_greedy
  -CodeCoverage, --CodeCoverage, --code-coverage VALUE
      Coverage mode: time, androlog, or jacoco. Default: time
  -Timeout, --Timeout, --timeout VALUE
      Timeout in seconds. Default: 3600
  -Interval, --Interval, --interval VALUE
      Event interval in seconds. Default: 3
  -Count, --Count, --count VALUE
      Event count. Default: 100000
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

default_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        printf '%s\n' "$PYTHON"
    elif [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then
        printf '%s\n' "$CONDA_PREFIX/bin/python"
    elif command -v python >/dev/null 2>&1; then
        printf '%s\n' python
    else
        printf '%s\n' python3
    fi
}

check_python_dependency() {
    local module_name="$1"
    local install_hint="$2"
    "$Python" - "$module_name" <<'PY' >/dev/null 2>&1 || die "Missing Python module '$module_name' in $("$Python" -c 'import sys; print(sys.executable)'). Install it with: $install_hint"
import importlib.util
import sys

sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)
PY
}

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

DeviceSerial="10.30.58.20:6555"
Python="$(default_python)"
ApkPath=""
OutputDir="output-mobsf-external"
Policy="dfs_greedy"
CodeCoverage="time"
Timeout=3600
Interval=3
Count=100000

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
        -Policy|--Policy|--policy)
            require_value "$1" "${2-}"
            Policy="$2"
            shift 2
            ;;
        --Policy=*|--policy=*)
            Policy="${1#*=}"
            shift
            ;;
        -CodeCoverage|--CodeCoverage|--code-coverage)
            require_value "$1" "${2-}"
            CodeCoverage="$2"
            shift 2
            ;;
        --CodeCoverage=*|--code-coverage=*)
            CodeCoverage="${1#*=}"
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

case "$CodeCoverage" in
    time|androlog|jacoco)
        ;;
    *)
        die "CodeCoverage must be one of: time, androlog, jacoco"
        ;;
esac

check_command "$Python"
check_python_dependency "pkg_resources" "python -m pip install 'setuptools<81'"
check_command adb

cd "$ScriptDir"

if is_blank "$ApkPath"; then
    DefaultApkDir="$ScriptDir/../input_apk"
    shopt -s nullglob
    ApkFiles=("$DefaultApkDir"/*.apk)
    shopt -u nullglob
    if (( ${#ApkFiles[@]} == 0 )); then
        die "No APK file found in $DefaultApkDir. Pass -ApkPath explicitly."
    fi
    ResolvedApkPath="${ApkFiles[0]}"
else
    CandidateApkPath="$ApkPath"
    if [[ "$CandidateApkPath" != /* ]]; then
        CandidateApkPath="$PWD/$CandidateApkPath"
    fi
    [[ -f "$CandidateApkPath" ]] || die "APK does not exist: $CandidateApkPath"
    ResolvedApkPath="$CandidateApkPath"
fi

ResolvedApkPath="$(resolve_file_path "$ResolvedApkPath")"

echo "[MobSF External Driver] Start MobSF dynamic analysis first, then keep the target app/emulator running."
echo "[MobSF External Driver] Using APK: $ResolvedApkPath"
echo "[MobSF External Driver] Python: $("$Python" -c 'import sys; print(sys.executable)')"
echo "[MobSF External Driver] adb connect $DeviceSerial"
adb connect "$DeviceSerial"

echo "[MobSF External Driver] Starting LLMDroid external driver"
"$Python" start.py \
    -d "$DeviceSerial" \
    -a "$ResolvedApkPath" \
    -o "$OutputDir" \
    -external_driver \
    -policy "$Policy" \
    -code_coverage "$CodeCoverage" \
    -timeout "$Timeout" \
    -interval "$Interval" \
    -count "$Count"
