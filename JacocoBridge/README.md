# JacocoBridge

The jar is invoked by LLMDroid-Droidbot during operation, but may also be used independently as a real-time coverage collection utility.

Make sure the app is instrumented as instructed before use. Please refer [here](../documents/Instrumentation.md) for detailed instructions on how to instrument an app using JaCoCo.



## Workflow

The workflow is as follows:

1. **Trigger EC file generation**: Send a broadcast via ADB to the instrumented app, prompting it to generate an EC file.
2. **Pull EC file**: Retrieve the EC file via ADB so JacocoBridge can access it.
3. **Calculate coverage**: Compute method-level code coverage using the EC file and the corresponding class files.
4. **Save results**: Write the results to an output file.
5. **Repeat**: Sleep for 3 seconds, then repeat the cycle until the specified time elapses.

## Usage

When running the JAR independently, use the following command:

```shell
java -jar JacocoBridge.jar -t $TIME --classFile $CLASSFILE --ecFilePath $EC_FILE_PATH --ecFileName $EC_FILE_NAME
```

### Parameters

| Parameter                      | Description                                                  |
| :----------------------------- | :----------------------------------------------------------- |
| `-t` / `--time`                | Total runtime (in seconds).                                  |
| `--classFile`                  | Path to the **`.class`** files generated during APK compilation (typically found in `app/build/intermediates/javac/debug/classes`). This directory can be copied elsewhere, but the JAR must have access to it. |
| `--ecFilePath`                 | Directory where the Jacoco-instrumented app generates runtime coverage files. Must match the path specified in the app’s modified source code. Recommended to use `getExternalFilesDir(null).getPath()` (e.g., `/storage/emulated/0/Android/data/<package_name>/files`). |
| `--ecFileName`                 | Name of the runtime coverage file. The instrumented app will generate ec file using this value as its name. |
| `-s` / `--udid` *(Optional)*   | Device serial number.                                        |
| `-o` / `--output` *(Optional)* | Output path for the result file (including filename). Default: `coverage.txt`. |
| `--pullPath` *(Optional)*      | Local directory where the EC file will be pulled from the device. Default: current directory. |