# Action Knowledge Base 内存版改造计划

## Summary

- 新建内存版 `ActionKnowledgeBase`，仅在单次运行中记录页面、动作和收益信息；测试结束后自然丢弃，不加载或保存 APK 历史记忆。
- 原功能默认不变：新增 `-action_kb {off,assist}`，默认 `off`；只有 `assist` 才启用相似度增强、重复动作降权、LLM 触发优化和局部逃逸。
- AKB 作为 UTG/LLM 状态机旁边的短期策略记忆层，不替换 UTG，不改变现有 `state_str`、`structure_str`、事件执行和 LLM prompt 主流程。
- 传统 DroidBot 主要依赖运行时生成的状态转移模型/UTG 和 greedy DFS/BFS 的未探索事件优先策略，并不是用覆盖率停滞来触发 LLM；本方案把这种 UTG 行为信号补到当前 LLMDroid 的覆盖率触发器旁边。

## Key Changes

- 新增 `droidbot/policy/action_knowledge_base.py`：
  - 维护运行内窗口：最近 state/cluster 序列、动作签名、覆盖率收益、新 state/new cluster 情况、逃逸 cooldown。
  - 不写 `events.jsonl`，不写 `snapshot.json`，不按 APK hash 恢复历史。
  - 提供只读统计摘要给日志或 `debug_states()` 使用，但不作为跨运行输入。
- 新增配置对象 `ActionKnowledgeConfig`：
  - `mode=off|assist`
  - `cluster_threshold=0.65`
  - `window_size=20`
  - `same_cluster_ratio_threshold=0.75`
  - `duplicate_action_ratio_threshold=0.55`
  - `new_state_rate_threshold=0.10`
  - `escape_cooldown_steps=8`
  - `temperature_start=0.25`
  - `temperature_reheat=1.0`
  - `temperature_cooling=0.85`

## Behavior Details

### 页面相似度

- `off` 模式保留当前 `DeviceState.compute_similarity()` 与阈值 `0.6`。
- `assist` 模式在 `__find_most_similar()` 中使用复合相似度：
  - `0.50 * widget_hash Dice`
  - `0.25 * action_signature Dice`
  - `0.15 * structure_str match`
  - `0.10 * text/resource/content-desc token Jaccard`
  - 不同 activity 的相似度封顶 `0.45`。

### 重复点击

- 采用软过滤降权，不硬禁止。
- 同 cluster 内相同 action signature、跨相似页面相同 widget/action 的候选动作优先级降低。
- 所有候选都重复时，选择重复次数最低的动作，避免卡死。

### LLM 调用时机

- `off` 模式保持现有覆盖率/时间触发。
- `assist + androlog/jacoco`：覆盖率低增长且行为停滞时进入 `ASK_GUIDANCE`。
- `assist + time`：时间到达且行为停滞时进入 `ASK_GUIDANCE`。
- 行为停滞定义：最近 20 步内同 cluster 比例大于等于 `0.75`、重复动作比例大于等于 `0.55`、新 state 比例小于等于 `0.10`。

### 模拟退火逃逸

- 仅在 `EXPLORE` 模式生效。
- 行为停滞但尚未调用 LLM 时，优先重排当前候选动作；若当前页无有效突破，则用 UTG 导航到低访问、有未探索动作、距离较远的 state/cluster。
- 不执行 STOP/START 重启应用。
- 逃逸失败后进入 8 步 cooldown，避免反复震荡。

## Integration Points

- `UtgBasedInputPolicy`：
  - 初始化内存版 AKB。
  - `__update_utg()` 后记录上一动作结果。
  - `__process_state()` 中记录 cluster 归属和相似度。
  - `__check_should_wait()` 中合并覆盖率停滞与行为停滞。
- `UtgGreedySearchPolicy`：
  - 取得 `possible_events` 后调用 `akb.rank_events()` 做降权排序。
  - 当前页无合适动作时调用 `akb.get_escape_navigation_target()`，再复用现有 `utg.get_navigation_steps()`。
- CLI/构造链路：
  - `start.py` 增加 `-action_kb off|assist`。
  - 透传到 `DroidBot`、`InputManager`、`UtgBasedInputPolicy`。
  - `adapter/droidbot.py` 同步透传，保证 worker 启动路径一致。

## Test Plan

- 单元测试：
  - 复合相似度能区分同 activity 相似页面与不同 activity 误合并页面。
  - 重复 action 被降权但不会被完全过滤。
  - 行为窗口满足阈值时返回停滞。
  - cooldown 期间不会连续触发逃逸。
- 策略测试：
  - `-action_kb off` 下聚类、LLM 触发、greedy 选择保持原逻辑。
  - `-action_kb assist` 下重复相似控件优先级下降。
  - 只有覆盖率低增长和行为停滞同时满足时才触发 LLM。
  - 退火逃逸只在 `EXPLORE` 生效，不干扰 `NAVIGATE` 和 `TEST_FUNCTION`。

## Assumptions

- 第一版只做单次运行内存，不做 APK 持久化或跨 APK 泛化。
- 重复点击采用软过滤降权。
- LLM 触发采用“覆盖率低增长 + 行为停滞”。
- 退火逃逸采用“候选重排 + UTG 导航”，不重启应用。

