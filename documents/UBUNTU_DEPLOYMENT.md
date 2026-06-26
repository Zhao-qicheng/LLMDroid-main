# PIPA / LLMDroid-Droidbot Ubuntu 服务器部署说明

本文档说明如何在 Ubuntu 服务器上部署并运行本仓库中的 `LLMDroid-Droidbot`。适用于两类常见场景：

- 独立运行 LLMDroid-Droidbot，对 APK 做 UI 自动探索和 LLM Guidance。
- 配合 MobSF Dynamic Analyzer，将 LLMDroid-Droidbot 作为外部 UI 驱动器接入同一个 Android 设备。

> 建议 Ubuntu 版本：Ubuntu 20.04 / 22.04 / 24.04。以下命令默认在仓库根目录 `PIPA/` 下执行。

## 1. 环境要求

服务器需要具备：

- Python 3.9 或更高版本。
- Git、curl、unzip 等基础工具。
- Android Debug Bridge，即 `adb`。
- JDK 11 或 17。使用 JaCoCo 覆盖率模式时必须安装。
- 一台可通过 `adb devices` 访问的 Android 模拟器或真机。
- 可访问所配置大模型服务的网络环境。

如果使用 AndroLog 或 JaCoCo 覆盖率模式，还需要使用已经插桩的 APK。

## 2. 安装系统依赖

```bash
sudo apt update
sudo apt install -y \
  git curl unzip wget \
  python3 python3-venv python3-pip \
  openjdk-17-jdk \
  android-tools-adb \
  build-essential \
  libgl1 libglib2.0-0
```

检查版本：

```bash
python3 --version
java -version
adb version
```

如果服务器上安装了 Android SDK，也可以使用 SDK 自带的 `platform-tools/adb`。此时建议把它加入 `PATH`：

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
```

可以把上面两行写入 `~/.bashrc`，重新登录后生效。

## 3. 获取代码

从 Git 仓库拉取代码，或把本项目目录上传到服务器：

```bash
git clone <your-repo-url> PIPA
cd PIPA
```

如果是从本地复制，请确保目录结构类似：

```text
PIPA/
  LLMDroid-Droidbot/
  ExperimentalDataset/
  JacocoBridge/
  README.md
```

## 4. 创建 Python 虚拟环境

```bash
cd LLMDroid-Droidbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

可选：以可编辑模式安装本地包。

```bash
pip install -e .
```

验证依赖是否可导入：

```bash
python - <<'PY'
import openai
import androguard
import networkx
import PIL
import jpype
print("Python dependencies OK")
PY
```

## 5. 配置大模型和 App 信息

编辑 `LLMDroid-Droidbot/config.json`：

```json
{
  "AppName": "Your App Name",
  "Description": "Brief description of the app under test.",
  "ApiKey": "",
  "BaseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "Model": "your-model-name",
  "TotalMethod": 0,
  "Tag": "",
  "Window": 100,
  "LLMAgent": {
    "OverviewWorkers": 5,
    "ReanalysisWorkers": 3,
    "GuidanceWaitTimeout": 45
  }
}
```

推荐不要把真实 API Key 写入仓库文件，而是在服务器环境变量中配置：

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

代码会按顺序读取 `config.json` 中的 `ApiKey`，以及以下环境变量：

```text
DASHSCOPE_API_KEY
BAILIAN_API_KEY
GLM_API_KEY
ZHIPUAI_API_KEY
```

如果使用 OpenAI-compatible 服务，需要确认 `BaseUrl` 和 `Model` 与服务提供方一致。

## 6. 准备 APK

本仓库已有示例数据集：

```text
ExperimentalDataset/apk-without-instrumentation/fse-dataset/
ExperimentalDataset/apk-after-instrumentation/FSE-dataset-wcx-log/
```

也可以自行创建 APK 输入目录：

```bash
cd ..
mkdir -p input_apk
cp /path/to/your_app.apk input_apk/
cd LLMDroid-Droidbot
```

注意：

- `time` 模式可以使用普通 APK。
- `androlog` 模式需要 AndroLog 插桩 APK，并在 `config.json` 中配置 `Tag` 和 `TotalMethod`。
- `jacoco` 模式需要 JaCoCo 插桩 APK，并配置 `EcFilePath` 和 `ClassFilePath`。

## 7. 连接 Android 设备

真机 USB 连接时：

```bash
adb devices
```

远程模拟器或 MobSF 使用的网络设备：

```bash
adb connect 10.30.58.20:6555
adb devices
```

确认输出中设备状态为 `device`：

```text
List of devices attached
10.30.58.20:6555    device
```

建议运行 AndroLog 模式时只连接一台设备。当前 AndroLog 监听逻辑内部使用 `adb logcat`，没有显式指定设备序列号，多设备同时在线时可能读取到错误设备。

## 8. 独立运行：AndroLog 示例

当前 `run_example_androlog.sh` 默认运行：

- 设备：`emulator-5554`
- APK：`ExperimentalDataset/apk-after-instrumentation/FSE-dataset-wcx-log/WishShop.apk`
- 策略：`dfs_greedy`
- 覆盖率模式：`androlog`
- 输出目录：`LLMDroid-Droidbot/output/androlog/WishShop/dfs_greedy`

首次运行前赋予脚本执行权限：

```bash
cd LLMDroid-Droidbot
chmod +x run_example_androlog.sh
```

运行默认示例：

```bash
./run_example_androlog.sh
```

指定设备和 APK：

```bash
./run_example_androlog.sh \
  --device-serial 10.30.58.20:6555 \
  --apk-path ../ExperimentalDataset/apk-after-instrumentation/FSE-dataset-wcx-log/WishShop.apk \
  --output-dir output/androlog/WishShop/dfs_greedy \
  --timeout 1800 \
  --interval 2 \
  --count 1000
```

等价的手动命令：

```bash
python start.py \
  -d 10.30.58.20:6555 \
  -a ../ExperimentalDataset/apk-after-instrumentation/FSE-dataset-wcx-log/WishShop.apk \
  -o output/androlog/WishShop/dfs_greedy \
  -timeout 1800 \
  -interval 2 \
  -count 1000 \
  -policy dfs_greedy \
  -grant_perm \
  -keep_app \
  -code_coverage androlog
```

## 9. 独立运行：普通 time 模式

如果只是验证环境或运行未插桩 APK，推荐先使用 `time` 模式：

```bash
python start.py \
  -d 10.30.58.20:6555 \
  -a ../ExperimentalDataset/apk-without-instrumentation/fse-dataset/fing.apk \
  -o output/time/fing \
  -timeout 3600 \
  -interval 5 \
  -count 100 \
  -policy dfs_greedy \
  -grant_perm \
  -code_coverage time
```

`time` 模式不读取真实代码覆盖率，而是按固定时间间隔触发 LLM Guidance，适合先确认 Python、ADB、模型接口和 UI 探索流程是否可用。

## 10. 配合 MobSF 运行外部驱动模式

该模式用于让 MobSF 继续负责动态安全分析，LLMDroid-Droidbot 只负责向同一台 Android 设备发送 UI 事件。

执行顺序必须是：

1. 在 MobSF 中上传 APK。
2. 启动 Dynamic Analyzer。
3. 确认 MobSF 已安装并启动目标 App。
4. 在服务器上确认同一设备可通过 `adb devices` 看到。
5. 启动 LLMDroid-Droidbot 外部驱动。

赋予脚本执行权限：

```bash
cd LLMDroid-Droidbot
chmod +x run_mobsf_external_driver.sh
```

运行：

```bash
./run_mobsf_external_driver.sh \
  --device-serial 10.30.58.20:6555 \
  --apk-path ../input_apk/your_app.apk \
  --output-dir output-mobsf-external \
  --policy dfs_greedy \
  --code-coverage time \
  --timeout 3600 \
  --interval 3 \
  --count 100000
```

等价的手动命令：

```bash
python start.py \
  -d 10.30.58.20:6555 \
  -a ../input_apk/your_app.apk \
  -o output-mobsf-external \
  -external_driver \
  -policy dfs_greedy \
  -code_coverage time \
  -timeout 3600 \
  -interval 3 \
  -count 100000
```

关键参数是 `-external_driver`。启用后，LLMDroid-Droidbot 会跳过 APK 安装、避免主动卸载目标 App，并尽量避免破坏 MobSF 当前动态分析会话。

## 11. JaCoCo 模式配置

使用 JaCoCo 时需要：

- 目标 APK 已经集成 JaCoCo runtime。
- App 内注册了 `com.llmdroid.jacoco.COLLECT_COVERAGE` broadcast receiver。
- 服务器安装 JDK。
- `LLMDroid-Droidbot/JacocoBridge.jar` 存在。
- `config.json` 配置以下字段：

```json
{
  "EcFilePath": "/sdcard/Android/data/<package>/files",
  "ClassFilePath": "/path/to/classes"
}
```

运行示例：

```bash
python start.py \
  -d 10.30.58.20:6555 \
  -a ../input_apk/your_jacoco_app.apk \
  -o output/jacoco/your_app \
  -policy dfs_greedy \
  -grant_perm \
  -keep_app \
  -code_coverage jacoco
```

更详细的插桩说明见：

```text
documents/Instrumentation.md
JacocoBridge/README.md
```

## 12. 输出目录

运行结果会写入 `-o` 指定目录，常见文件包括：

```text
events/
states/
utg.js
utg.json
debug_state.json
LLM_QA.txt
LLM-Interaction.txt
coverage.txt
log.txt
```

其中：

- `states/` 保存页面状态、截图和 UI 结构。
- `utg.json` / `utg.js` 保存 UI Transition Graph。
- `LLM_QA.txt` 保存发送给模型的 prompt 和模型响应，排查模型格式错误时很有用。
- `coverage.txt` 保存覆盖率变化，使用 `androlog` 或 `jacoco` 时更有参考价值。

## 13. 后台运行

长时间实验建议使用 `tmux`：

```bash
sudo apt install -y tmux
tmux new -s llmdroid
cd ~/PIPA/LLMDroid-Droidbot
source .venv/bin/activate
./run_example_androlog.sh --device-serial 10.30.58.20:6555
```

常用操作：

```text
Ctrl+b d       退出 tmux 会话但保持任务运行
tmux attach -t llmdroid
```

也可以使用 `nohup`：

```bash
nohup ./run_example_androlog.sh --device-serial 10.30.58.20:6555 \
  > run_androlog.log 2>&1 &
```

## 14. 常见问题

### adb devices 看不到设备

检查设备是否连接、端口是否可达：

```bash
adb kill-server
adb start-server
adb connect 10.30.58.20:6555
adb devices
```

如果是真机，确认已开启 USB 调试并授权服务器。

### APK does not exist

检查 `-a` 或 `--apk-path` 指向的路径。相对路径通常建议从 `LLMDroid-Droidbot/` 目录开始写，例如：

```bash
../input_apk/your_app.apk
```

### ApiKey is empty

设置环境变量，或在 `config.json` 中配置 `ApiKey`：

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

### AndroLog 没有覆盖率增长

检查三点：

- APK 是否为 AndroLog 插桩后的 APK。
- `config.json` 中 `Tag` 是否和插桩日志 tag 一致。
- `TotalMethod` 是否大于 0。

可以手动查看日志：

```bash
adb logcat -s <your-tag>
```

### 多设备环境下结果异常

尽量只保留一台目标设备在线：

```bash
adb devices
adb disconnect <unused-device-serial>
```

尤其是 AndroLog 模式，因为覆盖率监听内部没有把 `-d` 设备序列号传给所有 `adb logcat` 命令。

### UI 一直卡在权限页或登录页

可以尝试：

- 增加 `-grant_perm`。
- 在 `script_samples/` 中参考脚本机制，为欢迎页、登录页或权限页编写输入脚本。
- 先用 `manual` 策略保存页面状态，再调整自动探索策略。

## 15. 推荐部署检查清单

部署完成后按顺序确认：

```bash
cd PIPA/LLMDroid-Droidbot
source .venv/bin/activate
python -m pip check
adb devices
python start.py -h
```

然后先用 `time` 模式跑一个短任务：

```bash
python start.py \
  -d 10.30.58.20:6555 \
  -a ../ExperimentalDataset/apk-without-instrumentation/fse-dataset/fing.apk \
  -o output/smoke/fing \
  -timeout 120 \
  -interval 3 \
  -count 20 \
  -policy dfs_greedy \
  -grant_perm \
  -code_coverage time
```

如果能生成 `output/smoke/fing`，且其中包含状态、截图、UTG 或 LLM 日志，说明 Ubuntu 服务器基础部署已经完成。
