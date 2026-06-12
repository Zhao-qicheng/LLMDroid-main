# PIPA: LLMDroid + MobSF Dynamic Analysis Driver

本项目基于 LLMDroid-Droidbot 做了一个面向 MobSF 动态分析的集成版本。核心目标是让 MobSF 继续负责动态安全分析环境，而让 LLMDroid 作为外部 UI 驱动器接入同一个模拟器，自动探索 App 页面，从而帮助 MobSF 收集到更完整的运行时行为、网络请求和 API 调用信息。

## 核心思路

传统 MobSF 动态分析依赖人工点击或简单自动化操作来触发 App 行为。对于页面较多、流程较深、需要连续交互的 App，这种方式容易覆盖不足。

本项目新增了 `-external_driver` 模式，使 LLMDroid 可以在 MobSF 动态分析已经启动的情况下，通过 ADB 接管 UI 探索，但不破坏 MobSF 当前的分析会话：

- MobSF 负责 APK 安装、启动动态分析、代理抓包、Frida/API Monitor、运行时日志和报告生成。
- LLMDroid 连接同一个 Android 设备，读取当前 UI 状态，构建 UTG 页面状态图，并根据 `dfs_greedy` 等策略发送点击、输入、返回等事件。
- LLMDroid 在外部驱动模式下不会安装、卸载、强制停止目标 App，避免中断 MobSF 的动态分析上下文。

一句话概括：MobSF 做安全分析，LLMDroid 做智能探索。

## 与原 LLMDroid 的主要差异

本仓库围绕 MobSF 集成增加了 `external_driver` 参数，并把它传递到 DroidBot 生命周期、输入策略和 UTG 路径规划中。

关键行为如下：

- 跳过 APK 安装：`DroidBot.start()` 中检测到 `external_driver=True` 后不再执行 `install_app()`。
- 保留目标 App：外部驱动模式下强制 `keep_app=True`，停止 LLMDroid 后不会卸载 App。
- 避免首次杀进程：`InputPolicy.start()` 中第一步不再发送 `KillAppEvent`。
- 避免探索失败时 force-stop：`dfs_greedy`、`bfs_greedy`、`dfs_naive`、`bfs_naive` 在外部驱动模式下优先发送 `BACK`，而不是停止目标 App。
- 避免 LLM/UTG 导航前插入 STOP：`UTG.convert_path()` 在外部驱动模式下不会在导航路径开头添加停止 App 的事件。
- 提供 PowerShell 启动脚本：`LLMDroid-Droidbot/run_mobsf_external_driver.ps1` 封装了常用启动参数。

## 相关文件

```text
.
├── LLMDroid-Droidbot/
│   ├── start.py                         # 命令行入口，新增 -external_driver 和 -code_coverage
│   ├── run_mobsf_external_driver.ps1    # MobSF 外部驱动模式启动脚本
│   └── droidbot/
│       ├── droidbot.py                  # 跳过安装、保留 App、传递 external_driver
│       ├── input_manager.py             # 创建策略时传递 external_driver
│       ├── desc/utg.py                  # UTG 路径规划避免 STOP
│       └── policy/
│           ├── input_policy.py          # 避免首次 KillAppEvent
│           ├── utg_greedy_search_policy.py
│           ├── utg_naive_search_policy.py
│           └── manual_policy.py
├── input_apk/                           # 可放置待分析 APK，默认已被 .gitignore 忽略
└── README.md
```

## 环境要求

- Windows 10/11 或 Linux
- Python 3.9+
- ADB 可用，并且能够连接 MobSF 使用的 Android 设备
- MobSF 已安装并可以启动 Dynamic Analyzer
- LLMDroid-Droidbot 依赖：

```bash
pip install openai androguard networkx Pillow
```

如果使用 LLM Guidance，需要在 `LLMDroid-Droidbot/config.json` 中配置 App 描述和 API Key。如果只想先配合 MobSF 做普通 UI 探索，推荐使用 `-code_coverage time`，不需要 AndroLog/Jacoco 插桩。

## 推荐运行流程

### 1. 启动 MobSF 动态分析

先在 MobSF 中上传 APK，并进入 Dynamic Analyzer。确保 MobSF 已经完成以下工作：

- 目标 App 已安装到模拟器或真机。
- MobSF 的动态分析环境已经启动。
- 需要的代理、Frida/API Monitor、证书或 Hook 环境已经配置完成。
- 设备可以通过本机 `adb devices` 看到。

示例：

```bash
adb devices
```

如果 MobSF 使用的是远程或网络设备，可以先连接：

```bash
adb connect 10.30.58.20:6556
```

### 2. 启动 LLMDroid 外部驱动

进入 `LLMDroid-Droidbot` 目录：

```powershell
cd .\LLMDroid-Droidbot
```

使用脚本启动：

```powershell
.\run_mobsf_external_driver.ps1
```

脚本默认参数如下：

```text
DeviceSerial = 10.30.58.20:6556
OutputDir    = output-mobsf-external
Policy       = dfs_greedy
CodeCoverage = time
Timeout      = 3600
Interval     = 3
Count        = 100000
```

如果没有显式传入 `-ApkPath`，脚本会自动读取仓库根目录 `input_apk` 下的第一个 `.apk` 文件。

指定 APK 和设备的示例：

```powershell
.\run_mobsf_external_driver.ps1 `
  -DeviceSerial "127.0.0.1:7555" `
  -ApkPath "..\input_apk\your_app.apk" `
  -OutputDir "output-mobsf-external" `
  -Policy "dfs_greedy" `
  -CodeCoverage "time" `
  -Timeout 3600 `
  -Interval 3 `
  -Count 100000
```

### 3. 等待 MobSF 收集动态行为

LLMDroid 启动后会通过 ADB 对同一个设备发送 UI 事件。MobSF 会继续在后台记录 App 的运行时行为，包括网络请求、文件访问、敏感 API、日志、Hook 结果等。

探索完成后，在 MobSF 页面中停止动态分析并生成报告。

## 等价的手动命令

如果不使用 PowerShell 脚本，可以直接执行：

```powershell
python start.py `
  -d 10.30.58.20:6556 `
  -a ..\input_apk\your_app.apk `
  -o output-mobsf-external `
  -external_driver `
  -policy dfs_greedy `
  -code_coverage time `
  -timeout 3600 `
  -interval 3 `
  -count 100000
```

其中最重要的是 `-external_driver`。没有这个参数时，LLMDroid 会按普通 DroidBot/LLMDroid 流程管理 App 生命周期，可能安装、停止或卸载目标 App，从而影响 MobSF 分析。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `-d` | ADB 设备序列号，例如 `127.0.0.1:7555` 或 `10.30.58.20:6556` |
| `-a` | APK 路径。外部驱动模式仍需要 APK 路径来解析包名、入口 Activity 等信息 |
| `-o` | LLMDroid 输出目录，保存状态截图、事件日志、UTG 等结果 |
| `-external_driver` | MobSF 集成核心参数，表示 LLMDroid 只作为外部 UI 驱动器运行 |
| `-policy` | 探索策略，推荐 `dfs_greedy` |
| `-code_coverage` | 覆盖率触发模式，MobSF 集成推荐 `time` |
| `-timeout` | 运行时间上限，单位秒 |
| `-interval` | 两个事件之间的间隔，单位秒 |
| `-count` | 最多发送的事件数量 |

## 探索策略

当前代码中稳定可用的策略包括：

- `dfs_greedy`：默认推荐，优先探索当前页面未触发过的事件。
- `bfs_greedy`：贪心广度优先。
- `dfs_naive`：朴素深度优先。
- `bfs_naive`：朴素广度优先。
- `manual`：人工操作并保存状态。
- `monkey`：调用 Android 系统 Monkey。
- `replay`：回放已有 DroidBot 输出。
- `none`：只启动连接流程，不主动发送事件。

`memory_guided` 和 `llm_guided` 在代码中保留，但依赖额外环境，建议单独验证后再用于 MobSF 联动。

## 覆盖率模式

`-code_coverage` 支持三个值：

- `time`：不需要插桩，按时间或探索节奏触发 LLMDroid 逻辑。MobSF 外部驱动模式推荐使用。
- `androlog`：需要 AndroLog 插桩 APK，并在 `config.json` 中配置 `Tag` 和 `TotalMethod`。
- `jacoco`：需要 Jacoco 插桩、`JacocoBridge.jar`，并在 `config.json` 中配置 `ClassFilePath` 和 `EcFilePath`。

在 MobSF 动态分析场景下，通常不需要 LLMDroid 自己统计代码覆盖率，因为 MobSF 的重点是运行时安全行为和动态分析报告。因此推荐：

```bash
-code_coverage time
```

## config.json

如果只使用 `dfs_greedy` 并设置 `-code_coverage time`，一般不需要复杂配置。

如果需要 LLM Guidance 或插桩覆盖率，可以在 `LLMDroid-Droidbot/config.json` 中配置：

```json
{
  "AppName": "ExampleApp",
  "Description": "A short description of the app and its main features.",
  "ApiKey": "",
  "Model": "gpt-4o-mini",
  "BaseUrl": "",
  "TotalMethod": 0,
  "Tag": "",
  "ClassFilePath": "",
  "EcFilePath": ""
}
```

字段说明：

- `AppName`：App 名称。
- `Description`：App 功能描述，用于帮助 LLM 理解测试目标。
- `ApiKey`：调用 LLM 的 API Key。
- `Model`：模型名称。
- `BaseUrl`：兼容 OpenAI API 格式的服务地址。
- `TotalMethod` / `Tag`：AndroLog 模式使用。
- `ClassFilePath` / `EcFilePath`：Jacoco 模式使用。

## 注意事项

- 必须先启动 MobSF 动态分析，再启动 LLMDroid 外部驱动。
- `-external_driver` 只支持普通单设备模式，不支持 distributed master/worker。
- 外部驱动模式不会安装 APK，所以 MobSF 侧必须已经安装并启动目标 App。
- `-a` 参数仍然必须传入 APK 文件，因为 LLMDroid 需要从 APK 中解析包名和启动信息。
- 如果设备序列号不一致，LLMDroid 可能连接到错误设备。运行前请用 `adb devices` 确认。
- 如果 App 长时间跳出目标页面，LLMDroid 会优先尝试 `BACK`，而不是 force-stop App。
- `input_apk/` 和 `output-mobsf-external/` 已在 `.gitignore` 中忽略，避免把 APK 和运行结果提交到仓库。
