import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


SCRIPT_DIR = Path(__file__).resolve().parent
TERMINAL_STATUSES = {"finished", "failed", "stopped"}
ACTIVE_STATUSES = {"starting", "running", "stopping"}

DEFAULT_POLICY = os.getenv("LLMDROID_DEFAULT_POLICY", "dfs_greedy")
DEFAULT_CODE_COVERAGE = os.getenv("LLMDROID_DEFAULT_CODE_COVERAGE", "androlog")
DEFAULT_TIMEOUT = int(os.getenv("LLMDROID_DEFAULT_TIMEOUT", "3600"))
DEFAULT_INTERVAL = int(os.getenv("LLMDROID_DEFAULT_INTERVAL", "3"))
DEFAULT_COUNT = int(os.getenv("LLMDROID_DEFAULT_COUNT", "100000"))
OUTPUT_ROOT = Path(os.getenv("LLMDROID_OUTPUT_ROOT", str(SCRIPT_DIR / "output" / "llmdroid")))
PYTHON_EXECUTABLE = os.getenv("LLMDROID_PYTHON", sys.executable)
ADB_COMMAND = os.getenv("LLMDROID_ADB", "adb")
CALLBACK_ATTEMPTS = int(os.getenv("LLMDROID_CALLBACK_ATTEMPTS", "3"))
CALLBACK_TIMEOUT_SECONDS = int(os.getenv("LLMDROID_CALLBACK_TIMEOUT_SECONDS", "10"))
STOP_GRACE_SECONDS = int(os.getenv("LLMDROID_STOP_GRACE_SECONDS", "10"))


app = FastAPI(title="LLMDroid Internal Click Job API", version="1.0.0")


class StartClickJobRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    mobsf_hash: Optional[str] = None
    package_name: str = Field(..., min_length=1)
    apk_path: str = Field(..., min_length=1)
    device_identifier: str = Field(..., min_length=1)
    finished_callback_url: Optional[str] = None


class StopClickJobRequest(BaseModel):
    reason: Optional[str] = "control_center_cancelled"


@dataclass
class JobRecord:
    job_id: str
    mobsf_hash: Optional[str]
    package_name: str
    apk_path: str
    device_identifier: str
    output_dir: str
    finished_callback_url: Optional[str]
    status: str
    stage: str
    done: bool
    started_at: Optional[str]
    finished_at: Optional[str]
    reason: Optional[str]
    error: Optional[Dict[str, Any]]
    log_path: str
    process: Optional[subprocess.Popen] = None
    callback_sent: bool = False
    callback_attempts: int = 0

    def public_dict(self, accepted: Optional[bool] = None, message: Optional[str] = None) -> Dict[str, Any]:
        data = {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "done": self.done,
            "mobsf_hash": self.mobsf_hash,
            "package_name": self.package_name,
            "device_identifier": self.device_identifier,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "reason": self.reason,
            "error": self.error,
        }
        if accepted is not None:
            data["accepted"] = accepted
        if message is not None:
            data["message"] = message
        return {key: value for key, value in data.items() if value is not None}


jobs: Dict[str, JobRecord] = {}
jobs_lock = threading.RLock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def success_response(data: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": True, "data": data})


def error_response(
    code: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
    status_code: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "detail": detail or {},
            },
        },
    )


def stage_for_status(status: str) -> str:
    return "llmdroid_%s" % status


def safe_job_dir_name(job_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", job_id).strip("._") or "job"


def resolve_apk_path(apk_path: str) -> Path:
    candidate = Path(apk_path)
    if not candidate.is_absolute():
        candidate = SCRIPT_DIR / candidate
    return candidate.resolve()


def ensure_command(command: str) -> None:
    if os.path.sep in command or (os.path.altsep and os.path.altsep in command):
        if not Path(command).exists():
            raise ValueError("Command does not exist: %s" % command)
        return
    if shutil.which(command) is None:
        raise ValueError("Command not found: %s" % command)


def run_command(args, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(SCRIPT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )


def ensure_device_connected(device_identifier: str) -> None:
    ensure_command(ADB_COMMAND)

    if ":" in device_identifier and not device_identifier.startswith("emulator-"):
        connect_result = run_command([ADB_COMMAND, "connect", device_identifier], timeout=30)
        if connect_result.returncode != 0:
            raise ValueError("adb connect failed: %s" % connect_result.stdout.strip())

    devices_result = run_command([ADB_COMMAND, "devices"], timeout=20)
    if devices_result.returncode != 0:
        raise ValueError("adb devices failed: %s" % devices_result.stdout.strip())

    for line in devices_result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == device_identifier and parts[1] == "device":
            return
    raise ValueError("ADB device not found or not ready: %s" % device_identifier)


def get_apk_package(apk_path: Path) -> str:
    from droidbot.app import App

    return App(str(apk_path)).get_package_name()


def validate_start_request(path_job_id: str, body: StartClickJobRequest) -> Path:
    if path_job_id != body.job_id:
        raise ValueError("Path job_id and body job_id must be the same.")

    resolved_apk = resolve_apk_path(body.apk_path)
    if not resolved_apk.is_file():
        raise ValueError("APK does not exist: %s" % resolved_apk)

    apk_package = get_apk_package(resolved_apk)
    if apk_package and apk_package != body.package_name:
        raise ValueError(
            "package_name does not match APK package: request=%s, apk=%s"
            % (body.package_name, apk_package)
        )

    ensure_device_connected(body.device_identifier)
    return resolved_apk


def build_start_command(job: JobRecord) -> list:
    return [
        PYTHON_EXECUTABLE,
        str(SCRIPT_DIR / "start.py"),
        "-d",
        job.device_identifier,
        "-a",
        job.apk_path,
        "-o",
        job.output_dir,
        "-external_driver",
        "-policy",
        DEFAULT_POLICY,
        "-code_coverage",
        DEFAULT_CODE_COVERAGE,
        "-timeout",
        str(DEFAULT_TIMEOUT),
        "-interval",
        str(DEFAULT_INTERVAL),
        "-count",
        str(DEFAULT_COUNT),
    ]


def start_process(job: JobRecord) -> subprocess.Popen:
    Path(job.output_dir).mkdir(parents=True, exist_ok=True)
    log_file = open(job.log_path, "a", encoding="utf-8")
    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        return subprocess.Popen(
            build_start_command(job),
            cwd=str(SCRIPT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            **popen_kwargs,
        )
    finally:
        log_file.close()


def make_callback_event_id(job: JobRecord) -> str:
    raw = "%s:%s:%s" % (job.job_id, job.status, job.finished_at or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def callback_payload(job: JobRecord) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": job.stage,
        "done": job.done,
        "reason": job.reason,
        "error": job.error,
    }


def post_finished_callback(job_snapshot: JobRecord) -> None:
    if not job_snapshot.finished_callback_url:
        return

    payload = json.dumps(callback_payload(job_snapshot)).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Callback-Event": "llmdroid.finished",
        "X-Callback-Id": make_callback_event_id(job_snapshot),
    }

    for attempt in range(1, CALLBACK_ATTEMPTS + 1):
        headers["X-Callback-Attempt"] = str(attempt)
        callback_request = urlrequest.Request(
            job_snapshot.finished_callback_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urlrequest.urlopen(callback_request, timeout=CALLBACK_TIMEOUT_SECONDS) as response:
                if 200 <= response.status < 300:
                    with jobs_lock:
                        current = jobs.get(job_snapshot.job_id)
                        if current:
                            current.callback_sent = True
                            current.callback_attempts = attempt
                    return
        except (urlerror.URLError, TimeoutError, OSError):
            pass

        with jobs_lock:
            current = jobs.get(job_snapshot.job_id)
            if current:
                current.callback_attempts = attempt
        time.sleep(min(attempt * 2, 10))


def snapshot_job(job: JobRecord) -> JobRecord:
    return JobRecord(
        job_id=job.job_id,
        mobsf_hash=job.mobsf_hash,
        package_name=job.package_name,
        apk_path=job.apk_path,
        device_identifier=job.device_identifier,
        output_dir=job.output_dir,
        finished_callback_url=job.finished_callback_url,
        status=job.status,
        stage=job.stage,
        done=job.done,
        started_at=job.started_at,
        finished_at=job.finished_at,
        reason=job.reason,
        error=job.error.copy() if job.error else None,
        log_path=job.log_path,
        process=None,
        callback_sent=job.callback_sent,
        callback_attempts=job.callback_attempts,
    )


def mark_terminal(job_id: str, status: str, reason: str, error: Optional[Dict[str, Any]] = None) -> None:
    job_snapshot = None
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.done:
            return
        job.status = status
        job.stage = stage_for_status(status)
        job.done = True
        job.finished_at = utc_now_iso()
        job.reason = reason
        job.error = error
        job_snapshot = snapshot_job(job)

    if job_snapshot.finished_callback_url:
        threading.Thread(target=post_finished_callback, args=(job_snapshot,), daemon=True).start()


def monitor_process(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        process = job.process if job else None

    if not process:
        return

    returncode = process.wait()
    with jobs_lock:
        current = jobs.get(job_id)
        if not current or current.done:
            return
        stopping = current.status == "stopping"

    if stopping:
        mark_terminal(job_id, "stopped", "control_center_cancelled")
    elif returncode == 0:
        mark_terminal(job_id, "finished", "internal_timeout")
    else:
        mark_terminal(
            job_id,
            "failed",
            "runtime_error",
            {
                "code": "LLMDROID_CLICK_FAILED",
                "message": "LLMDroid click automation failed",
                "detail": {"returncode": returncode},
            },
        )


def stop_process_async(job_id: str, reason: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        process = job.process if job else None

    if not job:
        return

    try:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=STOP_GRACE_SECONDS)
        mark_terminal(job_id, "stopped", reason)
    except Exception as exc:
        mark_terminal(
            job_id,
            "failed",
            "runtime_error",
            {
                "code": "LLMDROID_STOP_FAILED",
                "message": "failed to stop LLMDroid click job",
                "detail": {"exception": str(exc)},
            },
        )


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "data": {"status": "ok"}}


@app.post("/api/v1/internal/click-jobs/{job_id}/start")
def start_click_job(job_id: str, request_body: StartClickJobRequest) -> JSONResponse:
    with jobs_lock:
        existing = jobs.get(job_id)
        if existing:
            accepted = False
            message = "job already exists"
            if existing.status in ACTIVE_STATUSES:
                message = "job already running"
            return success_response(existing.public_dict(accepted=accepted, message=message), status_code=202)

    try:
        resolved_apk_path = validate_start_request(job_id, request_body)
    except Exception as exc:
        return error_response(
            "LLMDROID_START_FAILED",
            "failed to start LLMDroid click job",
            {"job_id": job_id, "reason": str(exc)},
            status_code=400,
        )

    output_dir = OUTPUT_ROOT / safe_job_dir_name(job_id)
    log_path = output_dir / "llmdroid_process.log"
    job = JobRecord(
        job_id=request_body.job_id,
        mobsf_hash=request_body.mobsf_hash,
        package_name=request_body.package_name,
        apk_path=str(resolved_apk_path),
        device_identifier=request_body.device_identifier,
        output_dir=str(output_dir),
        finished_callback_url=request_body.finished_callback_url,
        status="starting",
        stage="llmdroid_starting",
        done=False,
        started_at=utc_now_iso(),
        finished_at=None,
        reason=None,
        error=None,
        log_path=str(log_path),
    )

    with jobs_lock:
        if job_id in jobs:
            existing = jobs[job_id]
            return success_response(
                existing.public_dict(accepted=False, message="job already exists"),
                status_code=202,
            )
        jobs[job_id] = job

    try:
        process = start_process(job)
    except Exception as exc:
        mark_terminal(
            job_id,
            "failed",
            "runtime_error",
            {
                "code": "LLMDROID_START_FAILED",
                "message": "failed to start LLMDroid click job",
                "detail": {"exception": str(exc)},
            },
        )
        with jobs_lock:
            failed_job = jobs[job_id]
        return error_response(
            "LLMDROID_START_FAILED",
            "failed to start LLMDroid click job",
            failed_job.public_dict(),
            status_code=500,
        )

    with jobs_lock:
        job.process = process
        job.status = "running"
        job.stage = "llmdroid_running"

    threading.Thread(target=monitor_process, args=(job_id,), daemon=True).start()
    return success_response(job.public_dict(accepted=True), status_code=202)


@app.get("/api/v1/internal/click-jobs/{job_id}")
def get_click_job(job_id: str) -> JSONResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return error_response(
                "LLMDROID_JOB_NOT_FOUND",
                "LLMDroid click job not found",
                {"job_id": job_id},
                status_code=404,
            )
        return success_response(job.public_dict())


@app.post("/api/v1/internal/click-jobs/{job_id}/stop")
def stop_click_job(job_id: str, request_body: StopClickJobRequest) -> JSONResponse:
    reason = request_body.reason or "control_center_cancelled"
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return error_response(
                "LLMDROID_JOB_NOT_FOUND",
                "LLMDroid click job not found",
                {"job_id": job_id},
                status_code=404,
            )
        if job.status in TERMINAL_STATUSES or job.done:
            return success_response(job.public_dict(accepted=False, message="job already finished"))
        job.status = "stopping"
        job.stage = "llmdroid_stopping"
        job.reason = reason
        response_data = job.public_dict(accepted=True)

    threading.Thread(target=stop_process_async, args=(job_id, reason), daemon=True).start()
    return success_response(response_data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "llmdroid_api:app",
        host=os.getenv("LLMDROID_API_HOST", "0.0.0.0"),
        port=int(os.getenv("LLMDROID_API_PORT", "8000")),
    )
