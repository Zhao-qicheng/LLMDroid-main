package org.jacoco.examples;

import org.jacoco.core.analysis.*;
import org.jacoco.core.tools.ExecFileLoader;
import org.jacoco.core.data.ExecutionDataStore;

import java.io.*;


public class JacocoBridge implements ICoverageVisitor {

    /**
     * Command line arguments
     */
    private static String[] mArgs;

    /**
     * Current argument being parsed
     */
    private static int mNextArg;

    /**
     * Data of current argument
     */
    private static String mCurArgData;

    private int sumCoveredCount = 0;
    private int sumMissedCount = 0;
    private int sumTotalCount = 0;

    private String udid;
    private String adbPullPath;    // The store path after pulling ec file, must be an absolute path!

    public JacocoBridge(String udid_, String pullPath) {
        udid = udid_;
        adbPullPath = (!pullPath.isEmpty()) ? pullPath: ".";
    }

    public float getMethodCoverage(String ecFileName, String ecFilePath, File classFile) throws IOException, InterruptedException {
        sendBroadcast(ecFileName);
        Thread.sleep(300);

        String targetPath = ecFilePath + "/" + ecFileName;
        adbPullFile(targetPath);

        // ec file to ExecutionDataStore
        System.out.println("Load ec file");
        ExecFileLoader execFileLoader = new ExecFileLoader();
        File ecFile = new File(adbPullPath + "/" + ecFileName);
        execFileLoader.load(ecFile);
        ExecutionDataStore store = execFileLoader.getExecutionDataStore();

        // analyzer
        System.out.println("Begin analyzing...");
        Analyzer analyzer = new Analyzer(store, this);
        analyzer.analyzeAll(classFile);

        // print result
        System.out.printf("[Final]: covered: %d; missed: %d, total: %d\n",
                sumCoveredCount, sumMissedCount, sumTotalCount);

        return (float)sumCoveredCount / sumTotalCount;

    }

    private void executeCommand(String command) {
        try {
            System.out.println("Execute: " + command);
            Process process = Runtime.getRuntime().exec(command);
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            while ((line = reader.readLine()) != null) {
                System.out.println(line);
            }
            int exitCode = process.waitFor();
            if (exitCode == 0) {
                System.out.println("Command executed successfully.");
            } else {
                System.out.println("Failed to execute command.");
            }
        } catch (IOException | InterruptedException e) {
            e.printStackTrace();
        }
    }

    private void sendBroadcast(String ecFileName) {
        String command;
        if (udid.isEmpty()) {
            command = "adb ";
        } else {
            command = String.format("adb -s %s ", udid);
        }
        command += String.format("shell am broadcast -a com.llmdroid.jacoco.COLLECT_COVERAGE --es coverageFile %s", ecFileName);
        executeCommand(command);
    }

    private void adbPullFile(String path) {
        String command;
        if (udid.isEmpty()) {
            command = String.format("adb pull %s %s", path, adbPullPath);
        }
        else {
            command = String.format("adb -s %s pull %s %s", udid, path, adbPullPath);
        }

        executeCommand(command);
    }

    @Override
    public void visitCoverage(IClassCoverage iClassCoverage) {
        ICounter methodCounter = iClassCoverage.getMethodCounter();
//        ICounter lineCounter = iClassCoverage.getLineCounter();
        int coveredCount = methodCounter.getCoveredCount();
        int missedCount = methodCounter.getMissedCount();
        int totalCount = methodCounter.getTotalCount();

        sumCoveredCount += coveredCount;
        sumMissedCount += missedCount;
        sumTotalCount += totalCount;
//        System.out.printf("[%s]: covered: %d; missed: %d, total: %d\n", iClassCoverage.getName(),
//                lineCounter.getCoveredCount(), lineCounter.getMissedCount(), lineCounter.getTotalCount());
    }

    private static String nextOption() {
        if (mNextArg >= mArgs.length) {
            return null;
        }
        String arg = mArgs[mNextArg];
        if (!arg.startsWith("-")) {
            return null;
        }
        mNextArg++;
        if (arg.equals("--")) {
            return null;
        }
        if (arg.length() > 1 && arg.charAt(1) != '-') {
            if (arg.length() > 2) {
                mCurArgData = arg.substring(2);
                return arg.substring(0, 2);
            } else {
                mCurArgData = null;
                return arg;
            }
        }
        mCurArgData = null;
        return arg;
    }

    /**
     * Return the next data associated with the current option.
     *
     * @return Returns the data string, or null of there are no more arguments.
     */
    private static String nextOptionData() {
        if (mCurArgData != null) {
            return mCurArgData;
        }
        if (mNextArg >= mArgs.length) {
            return null;
        }
        String data = mArgs[mNextArg];
        mNextArg++;
        return data;
    }

    /**
     * Returns a long converted from the next data argument, with error handling
     * if not available.
     *
     * @param opt The name of the option.
     * @return Returns a long converted from the argument.
     */
    private static long nextOptionLong(final String opt) {
        long result;
        try {
            result = Long.parseLong(nextOptionData());
        } catch (NumberFormatException e) {
            System.out.println(opt + " is not a number");
            throw e;
        }
        return result;
    }

    public static void main(String[] args) {
        mArgs = args;
        mNextArg = 0;

        long runTime = -1;
        String classFilePath = "";
        String ecFilePath = "";
        String ecFileName = "";
        String udid_ = "";
        String pullPath = ".";
        String outputPath = "";

        String opt;
        while ((opt = nextOption()) != null) {
            switch (opt) {
                case "-t":
                case "--time":
                    runTime = nextOptionLong("time");
                    break;
                case "--classFile":
                    classFilePath = nextOptionData();
                    break;
                case "--ecFilePath":
                    ecFilePath = nextOptionData();
                    break;
                case "--ecFileName":
                    ecFileName = nextOptionData();
                    break;
                case "-s":
                case "--udid":
                    udid_ = nextOptionData();
                    break;
                case "--pullPath":
                    pullPath = nextOptionData();
                    break;
                case "-o":
                case "--output":
                    outputPath = nextOptionData();
                    break;
            }
        }
        if (classFilePath.isEmpty() || ecFilePath.isEmpty() || ecFileName.isEmpty()) {
            System.out.println("usage: java -jar JacocoBridge.jar <classFile> <ecFilePath> <ecFileName>");
            System.exit(1);
        }

//        System.out.println(classFilePath);
//        System.out.println(ecFilePath);
//        System.out.println(ecFileName);
//        System.out.println(udid_);
//        System.out.println(runTime);
//        System.out.println(pullPath);
//        System.exit(0);

        if (outputPath.isEmpty()) {
            outputPath = "coverage.txt";
        }
        File classFile = new File(classFilePath);

        long startTime = System.nanoTime();
        long endTime = startTime + runTime * 1_000_000_000;
        try (BufferedWriter bw = new BufferedWriter(new FileWriter(outputPath, true))) {
            do {
                try {
                    long t1 = System.nanoTime();
                    JacocoBridge attempt = new JacocoBridge(udid_, pullPath);
                    float coverage = attempt.getMethodCoverage(ecFileName, ecFilePath, classFile);
                    long t2 = System.nanoTime();
                    double durationInSeconds = (t2 - t1) / 1_000_000_000.0;
                    System.out.println("耗时: " + durationInSeconds + " 秒");
                    bw.write(String.format("%.5f%%\n", coverage * 100));
                } catch (IOException e) {
                    System.out.println(e.getMessage());
                }
                Thread.sleep(3000);
            } while (System.nanoTime() < endTime);
        } catch (IOException | InterruptedException e) {
            e.printStackTrace();
        }
    }

}
