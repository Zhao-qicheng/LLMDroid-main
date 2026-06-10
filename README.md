# LLMDroid

**LLMDroid** is a novel testing framework designed to enhance existing automated mobile GUI testing tools by leveraging LLMs more efficiently.

- We applied LLMDroid to three popular open-source Android automated testing tools: **Droidbot**, **Humanoid** (based on Droidbot), and **Fastbot2**. See [Usage](#usage) for details.

- If you want to adapt LLMDroid to other testing tools, refer to the documentation: [`Adapting LLMDroid to other tools `](./documents/Adapting_LLMDroid_to_Other_Tools.md)

- LLMDroid supports instrumented APKs using **AndroLog** and **Jacoco**. For detailed steps, check: [`Instrumentation Documentation`](./documents/Instrumentation.md).



## :file_folder:File Structure

```text
LLMDroid/
├── ExperimentalDataset/
│   ├── configs/           		# Pre-configured 'config.json' files for dataset apps
│   └── README.md         		# Google Drive link for instrumented APKs and detailed experimental results
├── LLMDroid-Droidbot/			# Directory for source code of LLMDroid-Droidbot
├── LLMDroid-Humanoid/			# Directory for source code of LLMDroid-Humanoid
├── LLMDroid-Fastbot/			# Directory for source code of LLMDroid-Fastbot
├── JacocoBridge/				# The Jacoco implementation to computes real-time code coverage from '.ec files'. 
	│   ├── src/           		# Source code of JacocoBridge
	│   ├── JacocoBridge.jar    # JAR file
│   └── README.md         		# Workflow and Usage of JacocoBridge
├── documents/
└── README.md
```



## :computer:Experimental Environment

Here is the experimental environment we have tested.

### Operating System

- Ubuntu 20.04
- Also tested on Windows 10/11

### Python

- LLMDroid-Droidbot and LLMDroid-Humanoid is compatible with **Python >= 3.9**

### Android Environment

- Command Line Tool Used: ADB, AAPT, AAPT2



## :rocket:Usage

### Config

First, you need to prepare a `config.json` file before you test an app. 

```json
{
  "AppName": "Fing",
  "Description": "This app is a networking toolset app that can scan devices on the network, assess network status, and analyze network security. It also provides many useful utilities such as ping, port scanning, and speed test.",
  "ApiKey": "",
  "TotalMethod": 62491,
  "Tag": "FING_SUPER_LOG"
}
```

- **AppName**: The app you want to test.
- **Description**: A brief introduction to the app, including its main features and purposes. This helps the LLM better understand the task and improve the testing effectiveness.
- **ApiKey**: The API Key used to invoke the LLM.
- **TotalMethod**: The total number of methods in the app after instrumentation. For apps in the Dataset, this can be found in the table within `ExperimentalDataset`. For other apps, it can be obtained through the AndroLog tool after instrumentation is completed.
- **Tag**: The log tag specified during the app’s instrumentation, used for real-time code coverage statistics. For apps in the Dataset, this can be found in the table within `ExperimentalDataset`. For other apps, it can be specified before using the AndroLog tool for instrumentation.
- **ClassFilePath**: The **`.class`** files generated during APK compilation. You can find them in the `app\\build\\intermediates\\javac\\debug\\classes `directory under your app project. You may copy this directory to another location, as long as LLMDroid can access it.
- **EcFilePath**: The directory where the coverage file is generated during runtime when using Jacoco instrumentation. This must match the location specified when modifying the app's source code. It is recommended to use the path returned by `getExternalFilesDir(null).getPath()`, typically `/storage/emulated/0/Android/data/<package name>/files`.
- **Model: ** The model used, defaults to `gpt-4o-mini`.
- **BaseUrl:** The base URL for API calls. This parameter, along with the "Model" parameter, allows you to call non-OpenAI models as long as the third-party service supports the OpenAI API specification.



**Note:**

- **AndroLog-instrumented apps**: Set `Tag` + `TotalMethod`.  (`ClassFilePath` and `EcFilePath` are not required)
- **Jacoco-instrumented apps**: Set `ClassFilePath` + `EcFilePath`.  (`Tag` and `TotalMethod` are not required)
- Config templates are available in `ExperimentalDataset/configs` (rename to `config.json` before use).



### LLMDroid-Droidbot

- Install required modules

```shell
pip install openai androguard networkx Pillow
```

- Make sure the `config.json` file is under the root path of LLMDroid-Droidbot.

- Make sure the `JacocoBridge.jar` file is under the root path of LLMDroid-Droidbot.

- Enter the `LLMDroid-Droidbot` directory and run the following comand:

```shell
python start.py -d <AVD_SERIAL> -a <APK_FILE> -o <result_dir> -timeout 3600 -interval 3 -count 100000 -keep_app -keep_env -policy dfs_greedy -grant_perm
```

(Parameters are same as Droidbot)	



### LLMDroid-Humanoid

- Install required modules

```shell
pip install openai androguard networkx Pillow
```

- Make sure the `config.json` file is under the root path of LLMDroid-Humanoid.
- Make sure the `JacocoBridge.jar` file is under the root path of LLMDroid-Humanoid.
- Deploy and start the Humanoid agent. (For more details, see [Humanoid](https://github.com/the-themis-benchmarks/Humanoid))

- Enter the `LLMDroid-Humanoid` directory and run the following comand:

```shell
python start.py -d <AVD_SERIAL> -a <APK_FILE> -o <result_dir> -timeout 3600 -interval 3 -count 100000 -keep_app -keep_env -policy dfs_greedy -grant_perm -humanoid 192.168.50.133:50405
```

(Parameters are same as Humanoid)	

The only difference from LLMDroid-Droidbot is the addition of the parameter `-humanoid`, which indicates the IP address and the listening port of the humanoid agent. 



### LLMDroid-Fastbot

If you are simply running the LLMDroid-Fastbot tool, the steps are quite straightforward.

- Push artifacts into your device:  
    - The `faruzan` directory can be renamed as desired.  
    - The `config.json` file must be placed in `/sdcard` and cannot be renamed.  
    - If you are using a Jacoco-instrumented APK, you need to copy the **classes files** to the `/sdcard` directory so that LLMDroid-Fastbot can access them during runtime. Additionally, ensure that the **`ClassFilePath`** in `config.json` is correctly set to this location.

```shell
adb shell mkdir /sdcard/faruzan
adb push config.json /sdcard/config.json
adb push monkey/libs/* /sdcard/faruzan
adb push monkeyq.jar /sdcard/faruzan/monkeyq.jar
adb push fastbot-thirdpart.jar /sdcard/faruzan/fastbot-thirdpart.jar
adb push framework.jar /sdcard/faruzan/framework.jar
adb push libs/* /data/local/tmp/
```

- Run LLMDroid-Fastbot with the following command:

```shell
adb shell CLASSPATH=/sdcard/faruzan/monkeyq.jar:/sdcard/faruzan/framework.jar:/sdcard/faruzan/fastbot-thirdpart.jar:/sdcard/faruzan/org.jacoco.core-0.8.8.jar:/sdcard/faruzan/asm-9.2.jar:/sdcard/faruzan/asm-analysis-9.2.jar:/sdcard/faruzan/asm-commons-9.2.jar:/sdcard/faruzan/asm-tree-9.2.jar exec app_process /system/bin com.android.commands.monkey.Monkey -p $app_package_name --agent reuseq --use-code-coverage androlog --running-minutes 5 --throttle 3000 --output-directory $mobile_output_dir -v -v --bugreport
```

- Special Parameters: (Other parameters are consistent with Fastbot2. For more details, refer to the [Fastbot_Android](https://github.com/bytedance/Fastbot_Android).)  
    - `--use-code-coverage`: Specifies the real-time code coverage monitoring method. The following values are supported:  
        - `androlog`: Uses the androlog method. For closed-source apps, the APK must be instrumented using the androlog tool. Additionally, `Tag` and `TotalMethod` must be set in `config.json`.  
        - `jacoco`: Uses the jacoco method. For open-source apps, the source code must be modified and recompiled.  
        - `time`: Disables real-time code coverage monitoring. Used for debugging, where LLM Guidance mode is triggered at specified intervals.



However, if you wish to modify the code and compile it, you will need to install additional dependencies. For detailed steps, please refer to the README file under LLMDroid-Fastbot.

## :book:Publications

If you use our work in your research, please kindly cite us as:

```bibtex
@article{wang2025llmdroid,
  title=	{LLMDroid: Enhancing Automated Mobile App GUI Testing Coverage with Large Language Model Guidance},
  author=	{Wang, Chenxu and Liu, Tianming and Zhao, Yanjie and Yang, Minghui and Wang, Haoyu},
  journal=	{Proceedings of the ACM on Software Engineering},
  volume=	{2},
  number=	{FSE},
  pages=	{1001--1022},
  year=		{2025},
  publisher={ACM New York, NY, USA}
}
```

