# LLMDroid Internal Click Job API

本文档描述 Control Center 调用 LLMDroid 动态点击服务的内部接口。

当前目标流程：

1. MobSF Middleware 已经完成动态分析环境准备，并保持模拟器和目标 App 运行。
2. Control Center 调用 LLMDroid 启动点击任务。
3. LLMDroid 使用内部默认配置执行页面遍历和点击。
4. LLMDroid 结束后可主动回调 Control Center；Control Center 也可以查询任务状态。
5. Control Center 确认 LLMDroid 结束后，再调用 MobSF Middleware dynamic/continue。

LLMDroid 不负责启动 MobSF dynamic analysis，也不负责结束 MobSF dynamic analysis。

## 通用约定

Base URL:

```text
{LLMDROID_BASE_URL}
```

通用成功响应：

```json
{
  "ok": true,
  "data": {}
}
```

通用失败响应：

```json
{
  "ok": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "human readable error message",
    "detail": {}
  }
}
```

任务状态枚举：

| status | 含义 |
| --- | --- |
| `starting` | 已接受任务，正在启动 LLMDroid |
| `running` | LLMDroid 正在点击 |
| `finished` | LLMDroid 正常结束 |
| `failed` | LLMDroid 启动或运行失败 |
| `stopping` | 已收到停止请求，正在停止 |
| `stopped` | 已被停止接口终止 |

`finished`、`failed`、`stopped` 都表示任务已经结束，Control Center 可以继续后续 MobSF 流程。

## 1. 启动点击任务

调用方向：

```text
Control Center -> LLMDroid
```

接口：

```http
POST {LLMDROID_BASE_URL}/api/v1/internal/click-jobs/{job_id}/start
Content-Type: application/json
```

请求体：

```json
{
  "job_id": "middleware_job_id",
  "mobsf_hash": "mobsf_hash",
  "package_name": "com.example.app",
  "apk_path": "/shared/apks/middleware_job_id.apk",
  "device_identifier": "192.168.100.99:6555",
  "finished_callback_url": "http://control-center/api/v1/internal/callbacks/llmdroid/finished"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `job_id` | 是 | MobSF Middleware 返回的任务 ID。必须与 path 中的 `{job_id}` 一致。 |
| `mobsf_hash` | 否 | MobSF 的文件 hash，仅用于业务关联，不能作为主键。 |
| `package_name` | 是 | 目标 App 包名，用于校验当前 App 或 APK 是否匹配。 |
| `apk_path` | 是 | LLMDroid 可访问的 APK 路径。当前 LLMDroid 运行入口需要 APK 路径来构造 App 信息。 |
| `device_identifier` | 是 | ADB 设备标识，例如 `192.168.100.99:6555`。 |
| `finished_callback_url` | 否 | LLMDroid 在 `finished`、`failed` 或 `stopped` 时主动通知 Control Center 的地址。若不传，Control Center 需要轮询状态查询接口。 |

Control Center 不需要传 `timeout_seconds`。LLMDroid 使用服务端内部默认配置。

LLMDroid 内部默认运行参数建议：

| 参数 | 建议默认值 | 对应现有启动参数 |
| --- | --- | --- |
| 输出目录 | `output/llmdroid/{job_id}` | `-o` |
| 输入策略 | `dfs_greedy` | `-policy` |
| 覆盖率模式 | ` androlog` | `-code_coverage` |
| 事件间隔 | `3` | `-interval` |
| 最大事件数 | `100000` | `-count` |
| 超时时间 | 服务配置决定 | `-timeout` |
| 外部驱动模式 | 固定开启 | `-external_driver` |

成功响应：

```http
202 Accepted
```

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "status": "running",
    "stage": "llmdroid_running",
    "accepted": true
  }
}
```

启动失败响应：

```json
{
  "ok": false,
  "error": {
    "code": "LLMDROID_START_FAILED",
    "message": "failed to start LLMDroid click job",
    "detail": {
      "job_id": "middleware_job_id"
    }
  }
}
```

建议的启动前校验：

1. 校验 `job_id` 不为空，且 path 与 body 一致。
2. 校验 `apk_path` 存在。
3. 校验 `device_identifier` 可连接。
4. 如设备标识为远程地址，执行 `adb connect {device_identifier}`。
5. 校验目标 App 已由 MobSF dynamic analysis 启动。
6. 校验 `package_name` 与 APK 或当前前台 App 匹配。
7. 若同一个 `job_id` 已在运行，返回幂等成功或 `LLMDROID_JOB_ALREADY_RUNNING`。

## 2. 查询点击任务状态

调用方向：

```text
Control Center -> LLMDroid
```

接口：

```http
GET {LLMDROID_BASE_URL}/api/v1/internal/click-jobs/{job_id}
```

运行中响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "status": "running",
    "stage": "llmdroid_running",
    "done": false,
    "mobsf_hash": "mobsf_hash",
    "package_name": "com.example.app",
    "device_identifier": "192.168.100.99:6555",
    "started_at": "2026-07-02T10:00:00+08:00"
  }
}
```

已结束响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "status": "finished",
    "stage": "llmdroid_finished",
    "done": true,
    "mobsf_hash": "mobsf_hash",
    "package_name": "com.example.app",
    "device_identifier": "192.168.100.99:6555",
    "started_at": "2026-07-02T10:00:00+08:00",
    "finished_at": "2026-07-02T10:03:20+08:00",
    "reason": "internal_timeout"
  }
}
```

任务不存在响应：

```http
404 Not Found
```

```json
{
  "ok": false,
  "error": {
    "code": "LLMDROID_JOB_NOT_FOUND",
    "message": "LLMDroid click job not found",
    "detail": {
      "job_id": "middleware_job_id"
    }
  }
}
```

Control Center 处理建议：

1. 若 `done=false`，继续等待或稍后轮询。
2. 若 `status=finished`，调用 MobSF Middleware dynamic/continue。
3. 若 `status=failed` 或 `status=stopped`，仍调用 MobSF Middleware dynamic/continue，让 MobSF 完成动态停止、代理清理和已有结果收集。
4. 若 Control Center 任务已取消，则不得继续调用 MobSF Middleware dynamic/continue。

## 3. 停止点击任务

此接口用于 Control Center 主动取消或强制停止 LLMDroid。正常情况下，如果 Control Center 让 LLMDroid 使用内部 timeout，可以不调用该接口。

调用方向：

```text
Control Center -> LLMDroid
```

接口：

```http
POST {LLMDROID_BASE_URL}/api/v1/internal/click-jobs/{job_id}/stop
Content-Type: application/json
```

请求体：

```json
{
  "reason": "control_center_cancelled"
}
```

成功响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "status": "stopping",
    "stage": "llmdroid_stopping",
    "accepted": true
  }
}
```

任务已经结束时的幂等响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "status": "finished",
    "stage": "llmdroid_finished",
    "accepted": false,
    "message": "job already finished"
  }
}
```

停止失败响应：

```json
{
  "ok": false,
  "error": {
    "code": "LLMDROID_STOP_FAILED",
    "message": "failed to stop LLMDroid click job",
    "detail": {
      "job_id": "middleware_job_id"
    }
  }
}
```

## 4. LLMDroid 完成回调

如果启动请求传入了 `finished_callback_url`，LLMDroid 在任务进入 `finished`、`failed` 或 `stopped` 终态后调用该地址。回调只通知状态，不携带 artifacts。

调用方向：

```text
LLMDroid -> Control Center
```

接口：

```http
POST {finished_callback_url}
Content-Type: application/json
X-Callback-Event: llmdroid.finished
X-Callback-Id: <stable-event-id>
X-Callback-Attempt: <1..N>
```

正常结束请求体：

```json
{
  "job_id": "middleware_job_id",
  "status": "finished",
  "stage": "llmdroid_finished",
  "done": true,
  "reason": "internal_timeout",
  "error": null
}
```

失败请求体：

```json
{
  "job_id": "middleware_job_id",
  "status": "failed",
  "stage": "llmdroid_failed",
  "done": true,
  "reason": "runtime_error",
  "error": {
    "code": "LLMDROID_CLICK_FAILED",
    "message": "LLMDroid click automation failed",
    "detail": {}
  }
}
```

被停止请求体：

```json
{
  "job_id": "middleware_job_id",
  "status": "stopped",
  "stage": "llmdroid_stopped",
  "done": true,
  "reason": "control_center_cancelled",
  "error": null
}
```

Control Center 成功响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "accepted": true,
    "next_action": "continue_mobsf"
  }
}
```

重复回调响应：

```json
{
  "ok": true,
  "data": {
    "job_id": "middleware_job_id",
    "accepted": false,
    "duplicated": true,
    "next_action": "already_processed"
  }
}
```

Control Center 处理建议：

1. 使用 `X-Callback-Event` 和 `X-Callback-Id` 去重。
2. 校验 `job_id` 是否存在。
3. 只保存 LLMDroid 的最终状态，不要求保存 LLMDroid artifacts。
4. 只要任务未取消，收到 `finished`、`failed` 或 `stopped` 后都可以调用 MobSF Middleware dynamic/continue。

## 推荐编排流程

使用回调：

1. Control Center 调用 MobSF Middleware，等待动态环境 ready。
2. Control Center 调用 LLMDroid `/start`，传入 `finished_callback_url`。
3. LLMDroid 内部按默认 timeout 和策略运行。
4. LLMDroid 结束后回调 Control Center。
5. Control Center 调用 MobSF Middleware dynamic/continue。

不使用回调：

1. Control Center 调用 MobSF Middleware，等待动态环境 ready。
2. Control Center 调用 LLMDroid `/start`，不传 `finished_callback_url`。
3. Control Center 定时调用 LLMDroid `GET /click-jobs/{job_id}`。
4. 查询到 `done=true` 后，Control Center 调用 MobSF Middleware dynamic/continue。

## 当前代码映射

LLMDroid 服务启动任务时，可以先复用现有命令行入口：

```bash
python start.py \
  -d "$device_identifier" \
  -a "$apk_path" \
  -o "output/llmdroid/$job_id" \
  -external_driver \
  -policy dfs_greedy \
  -code_coverage androlog \
  -timeout "$LLMDROID_DEFAULT_TIMEOUT" \
  -interval 3 \
  -count 100000
```

后续如果重构为可导入 Python 函数入口，HTTP API 契约不需要变化。
