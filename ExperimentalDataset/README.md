# Experimental Dataset

We selected 14 apps from GooglePlay's top charts and their recommended similar apps, and instrumented them using the [AndroLog](https://github.com/JordanSamhi/AndroLog) tool. 

The instrumented APKs can be found in the `ExperimentalDataset` directory.

Below is information about the 14 apps, including their names, categories, download counts, etc. More detailed information such as package names, instrumented log tags, total method counts, and so on can be found [below](# APK Information).

|  ID  |            App Name            |   Category    | Downloads | Apk Size |
| :--: | :----------------------------: | :-----------: | :-------: | :------: |
|  1   |      Wish: Shop and Save       |   Shopping    |   500M+   |   43MB   |
|  2   |     Twitch: Live Streaming     | Entertainment |   100M+   |  157MB   |
|  3   |           Wikipedia            |   Education   |   50M+    |  33.2MB  |
|  4   | Quora: the knowledge platform  |   Education   |   50M+    |  10.3MB  |
|  5   |      Fing - Network Tools      |     Tools     |   50M+    |  41.5MB  |
|  6   |          Lefun Health          |    Health     |   10M+    |  142MB   |
|  7   |  Red Bull TV: Videos & Sports  |    Sports     |   10M+    |  19.3MB  |
|  8   | Time Planner: Schedule & Tasks |     Tools     |    5M+    |  12.5MB  |
|  9   |            NewPipe             | Entertainment |    5M+    |  13.7MB  |
|  10  |        NHK WORLD-JAPAN         |     News      |    1M+    |  7.39MB  |
|  11  |         Renpho Health          |    Health     |    1M+    |  100MB   |
|  12  | Mood Tracker: Self-Care Habits |     Life      |   500K+   |  42.9MB  |
|  13  | CafeNovel - Fiction & Webnovel |     Book      |   10K+    |  19.0MB  |
|  14  |            OceanEx             |  Commercial   |   10K+    |  14.9MB  |

## APKs

The instrumented APKs can be downloaded from the following link.

[Google Drive Share](https://drive.google.com/drive/folders/11-3iLHXhXTQjNG0DheRga256bWq528_e?usp=sharing)

We provide both the instrumented version and the non-instrumented version. Since some APKs have been blocked and are not visible, we have packaged them separately into two compressed archives and encrypted them using the password `securitypride`.


## APK Information
| App Name                       | Package Name                                   | TAG                           | Total Methods |
| ------------------------------ | ---------------------------------------------- | ----------------------------- | ------------- |
| Twitch                         | tv.twitch.android.app                          | TWITCH_WCX_LOG                | 444254        |
| NewPipe                        | org.schabi.newpipe                             | PIPE_SUPER_LOG                | 75480         |
| Fing                           | com.overlook.android.fing                      | FING_SUPER_LOG                | 62491         |
| Wiki                           | org.wikipedia                                  | WIKI_WCX_LOG                  | 79210         |
| Cafa Novel                     | com.xiyue.read.book.cafe.novel                 | CAFENOVEL_WCX_LOG             | 127880        |
| OceanEx                        | com.ocean.exchange                             | OCEANEX_WCX_LOG               | 95052         |
| Mood Tracker: Self-Care Habits | moodtracker.selfcare.habittracker.mentalhealth | MOOD_TRACKER_WCX_LOG          | 159905        |
| Wish: Shop and Save            | com.contextlogic.wish                          | WISH_SHOP_WCX_LOG             | 241862        |
| Quora: the knowledge platform  | com.quora.android                              | QUORA_WCX_LOG                 | 119103        |
| Time Planner: Schedule & Tasks | com.albul.timeplanner                          | TIME_PLANNER_SCHEDULE_WCX_LOG | 23280         |
| Red Bull TV: Videos & Sports   | com.nousguide.android.rbtv                     | RED_BULL_TV_WCX_LOG           | 244451        |
| NHK WORLD-JAPAN                | jp.or.nhk.nhkworld.tv                          | NHK_WORLD_JAPAN_WCX_LOG       | 51729         |
| Lefun Health                   | com.tjd.tjdmainS2                              | TJD_TJDMAINS2_WCX_LOG         | 299389        |
| Renpho Health                  | com.renpho.health                              | RENPHO_HEALTH_WCX_LOG         | 395367        |

# Experimental Results

## Tool Performance (RQ1)

The following table shows the code coverage and Activity coverage for the 14 apps tested by Monkey and three improved testing tools using the LLMDroid framework, compared to the original tools.

|      App Name       |   Monkey   |  Droidbot  | LLMDroid-Droidbot |    Impr    |  Humanoid  | LLMDroid-Huamnoid |  Improve   |  Fastbot   | LLMDroid-Fastbot |    Impr    |
| :-----------------: | :--------: | :--------: | :---------------: | :--------: | :--------: | :---------------: | :--------: | :--------: | :--------------: | :--------: |
| Wish: Shop and Save |   6.97%    |   11.53%   |      15.00%       |   40.68%   |   14.88%   |      17.57%       |   18.04%   |   9.58%    |      16.23%      |   69.37%   |
|       Twitch        |   10.05%   |   14.41%   |      19.90%       |   38.13%   |   18.46%   |      20.02%       |   8.49%    |   16.22%   |      24.64%      |   51.97%   |
|      Wikipedia      |   12.08%   |   9.73%    |      14.13%       |   45.28%   |   16.08%   |      18.98%       |   18.06%   |   16.78%   |      20.71%      |   23.39%   |
|        Quora        |   2.87%    |   2.53%    |       3.81%       |   50.58%   |   3.65%    |       4.14%       |   13.37%   |   3.79%    |      4.21%       |   11.04%   |
|        Fing         |   18.59%   |   16.32%   |      20.12%       |   23.25%   |   19.02%   |      21.93%       |   15.30%   |   16.50%   |      24.80%      |   50.30%   |
|    Lefun Health     |   2.87%    |   2.71%    |       2.96%       |   9.34%    |   2.18%    |       2.58%       |   18.18%   |   3.67%    |      3.96%       |   17.53%   |
|     Red Bull TV     |   1.47%    |   5.29%    |       6.39%       |   20.84%   |   5.27%    |       6.17%       |   17.15%   |   4.35%    |      5.88%       |   35.43%   |
|    Time Planner     |   15.39%   |   9.57%    |      14.69%       |   53.39%   |   12.69%   |      15.45%       |   21.77%   |   17.35%   |      21.98%      |   26.67%   |
|       NewPipe       |   16.75%   |   20.67%   |      24.37%       |   17.89%   |   23.04%   |      33.14%       |   43.81%   |   22.06%   |      33.86%      |   42.68%   |
|   NHK WORLD-JAPAN   |   6.77%    |   17.87%   |      18.09%       |   1.22%    |   17.23%   |      22.83%       |   32.53%   |   20.46%   |      23.03%      |   12.56%   |
|    Renpho Health    |   2.31%    |   3.14%    |       3.67%       |   16.89%   |   2.99%    |       3.03%       |   1.32%    |   3.50%    |      4.01%       |   14.61%   |
|    Mood Tracker     |   4.76%    |   4.09%    |       5.00%       |   22.29%   |   4.71%    |       5.71%       |   21.36%   |   7.78%    |      8.05%       |   3.52%    |
|      CafeNovel      |   4.20%    |   4.11%    |       4.81%       |   16.97%   |   5.01%    |       5.41%       |   57.90%   |   5.49%    |      5.81%       |   5.87%    |
|       OceanEx       |   6.40%    |   8.52%    |      10.17%       |   19.29%   |   9.44%    |      10.61%       |   12.35%   |   9.81%    |      12.38%      |   26.10%   |
|       **ACC**       | **8.86%**  | **9.21%**  |    **11.69%**     | **26.90%** | **11.05%** |    **13.04%**     | **21.29%** | **11.36%** |    **14.80%**    | **30.30%** |
|       **AAC**       | **11.34%** | **15.90%** |    **22.46%**     | **41.29%** | **19.16%** |    **23.66%**     | **23.51%** | **24.40%** |    **30.05%**    | **23.13%** |

Impr.：Improvement

ACC: Average Code Coverage

AAC: Average Activity Coverage

## Performance and Cost under Different LLMs (RQ2)

### Code Coverage

| **APP**                        | **LLMDroid-Fastbot-3.5** | **LLMDroid-Fastbot-4o-mini** | **LLMDroid-Fastbot-4o** | **DroidAgent-4o+mini** | **DroidAgent-4o+3.5** | **GPTDroid-3.5** | **GPTDroid-4o-mini** |
| ------------------------------ | ------------------------ | ---------------------------- | ----------------------- | ---------------------- | --------------------- | ---------------- | -------------------- |
| Twitch                         | 22.23%                   | 23.19%                       | 23.81%                  | 16.10%                 | 14.83%                | 11.76%           | 14.06%               |
| NewPipe                        | 21.58%                   | 22.91%                       | 28.28%                  | 26.06%                 | 23.94%                | 13.99%           | 12.66%               |
| Fing                           | 23.99%                   | 24.61%                       | 25.66%                  | 20.15%                 | 18.24%                | 12.97%           | 12.41%               |
| Wiki                           | 17.11%                   | 18.04%                       | 19.09%                  | 14.72%                 | 13.53%                | 7.03%            | 7.40%                |
| Cafa Novel                     | 5.96%                    | 5.84%                        | 5.77%                   | 4.76%                  | 4.56%                 | 2.91%            | 2.78%                |
| Ocean ex                       | 7.99%                    | 9.85%                        | 10.67%                  | 7.31%                  | 7.30%                 | 5.16%            | 4.97%                |
| Mood Tracker: Self-Care Habits | 7.64%                    | 7.82%                        | 7.96%                   | 4.98%                  | 5.06%                 | 3.97%            | 4.39%                |
| Wish: Shop and Save            | 16.10%                   | 15.41%                       | 16.33%                  | 15.93%                 | 17.15%                | 11.47%           | 10.40%               |
| Quora: the knowledge platform  | 3.86%                    | 4.26%                        | 4.23%                   | 3.10%                  | 3.79%                 | 3.12%            | 2.88%                |
| Time Planner: Schedule & Tasks | 19.43%                   | 19.81%                       | 20.50%                  | 14.34%                 | 15.63%                | 7.65%            | 8.13%                |
| Red Bull TV: Videos & Sports   | 5.69%                    | 5.87%                        | 6.86%                   | 4.11%                  | 3.88%                 | 4.54%            | 4.29%                |
| NHK WORLD-JAPAN                | 22.47%                   | 23.02%                       | 22.94%                  | 15.47%                 | 16.71%                | 15.20%           | 15.75%               |
| Lefun Health                   | 3.64%                    | 3.39%                        | 3.64%                   | 2.37%                  | 2.77%                 | 2.03%            | 1.88%                |
| Renpho Health                  | 4.40%                    | 4.50%                        | 4.90%                   | 3.02%                  | 3.39%                 | 2.16%            | 2.27%                |
| **Average**                    | **13.01%**               | **13.47%**                   | **14.33%**              | **10.89%**             | **10.77%**            | **7.43%**        | **7.45%**            |



### API Cost

(Unit: USD)

| **APP**                        | **LLMDroid-Fastbot-3.5** | **LLMDroid-Fastbot-4o-mini** | **LLMDroid-Fastbot-4o** | **DroidAgent-4o+mini** | **DroidAgent-4o+3.5** | **GPTDroid-3.5** | **GPTDroid-4o-mini** |
| ------------------------------ | ------------------------ | ---------------------------- | ----------------------- | ---------------------- | --------------------- | ---------------- | -------------------- |
| Twitch                         | 0.1400                   | 0.0901                       | 0.8578                  | 0.7965                 | 1.9814                | 0.3182           | 0.0603               |
| NewPipe                        | 0.0807                   | 0.0368                       | 0.5183                  | 0.9958                 | 1.4734                | 0.1779           | 0.0548               |
| Fing                           | 0.0843                   | 0.0262                       | 0.5520                  | 0.9465                 | 1.8882                | 0.1951           | 0.0611               |
| Wiki                           | 0.1078                   | 0.0391                       | 0.7145                  | 1.013                  | 1.8584                | 0.0793           | 0.0547               |
| Cafa Novel                     | 0.0746                   | 0.0190                       | 0.3517                  | 0.9394                 | 1.4708                | 0.1903           | 0.0628               |
| Ocean ex                       | 0.0832                   | 0.0268                       | 0.3133                  | 1.0035                 | 1.5318                | 0.1653           | 0.0478               |
| Mood Tracker: Self-Care Habits | 0.0872                   | 0.0273                       | 0.4379                  | 0.874                  | 1.6947                | 0.2905           | 0.0773               |
| Wish: Shop and Save            | 0.1135                   | 0.0336                       | 0.5229                  | 0.9702                 | 1.837                 | 0.2862           | 0.0811               |
| Quora: the knowledge platform  | 0.0743                   | 0.0350                       | 0.3927                  | 0.5768                 | 1.7273                | 0.3261           | 0.0521               |
| Time Planner: Schedule & Tasks | 0.0853                   | 0.0319                       | 0.466                   | 0.7288                 | 1.6257                | 0.1597           | 0.0666               |
| Red Bull TV: Videos & Sports   | 0.0463                   | 0.0237                       | 0.3734                  | 3.6221                 | 2.8841                | 0.1422           | 0.0454               |
| NHK WORLD-JAPAN                | 0.0570                   | 0.0244                       | 0.5297                  | 0.8453                 | 1.4472                | 0.1630           | 0.0386               |
| Lefun Health                   | 0.0847                   | 0.0216                       | 0.3682                  | 0.8662                 | 1.1283                | 0.1945           | 0.0603               |
| Renpho Health                  | 0.0978                   | 0.0311                       | 0.5177                  | 1.0249                 | 1.5455                | 0.2078           | 0.0666               |
| **Average**                    | **0.0869**               | **0.0333**                   | **0.4940**              | **1.0859**             | **1.7210**            | **0.2069**       | **0.0593**           |

