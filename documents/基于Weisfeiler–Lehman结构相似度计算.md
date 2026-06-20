

## 问题

LLMDroid 将探索过程中出现的 GUI snapshot 聚合为 **StateCluster（语义页）**，并在此基础上调用 LLM 生成页面 Overview 与 Function List，进而驱动 GUIDE 导航与功能测试。  

* 新 snapshot 是否并入已有 cluster，由 `compute_similarity()` 与阈值（0.6）决定；

* 导航阶段亦用同一相似度判断「是否到达目标页布局」。



当前实现将页面表示为 **去重后的控件原型集合**，以 widget hash 的 Dice 系数度量相似度。该 hash 由控件类名、resource-id、尺寸与操作类型等组成，**不包含控件在布局树中的位置、重复次数及页面级语义**。  因此，相似度函数实际回答的是「两页控件原型 bag 的重叠程度」，而非「两页是否属于同一功能/布局类别」，导致聚类误差放大。

| 误合并               | 后果                                   |
| ----------------- | ------------------------------------ |
| 不同功能页并入同一 cluster | LLM Overview/Function List 混淆（B1/B4） |
| 应合并的动态变体被拆开       | 重复 OVERVIEW、cluster 膨胀、GUIDE 候选冗余    |
| 导航「布局像即可」判断失准     | NAVIGATE 过早成功或无故失败                   |



### 例 ：Hierarchy 不同、Dice相似度极高

**页面 A**

```text
LinearLayout → [TextView, EditText, EditText, Button]
```

**页面 B**

```text
LinearLayout → TextView → FrameLayout → [EditText, Button]
               （仅 1 个 EditText，少一层表单）
```

**hash Dice**：若可见控件 class/res-id 组合相近，Dice 仍可能很高。

## 方案

现有实现将每个 GUI snapshot 压缩为去重控件 hash 的集合，在相似度计算中仅比较控件原型的重叠率，属于 structure-agnostic的页面表示：parent–child 关系、控件重复次数与局部子树模式在 `__init_widgets` 去重过程中被丢弃。



然而，StateCluster 的目标是在 layout 级别合并动态内容不同的 snapshot，并区分控件类型相近但 hierarchy 或功能不同的页面，这要求相似度度量必须 structure-aware。



因此，基于已有的 `DeviceState.views` 恢复带属性 Widget 图，并采用 Weisfeiler–Lehman 子树核提取层次子结构特征来计算结构相似度；同时利用 `foreground_activity` 与 `Widget` 上已有的交互、文本属性构造 cannot-link 约束。



## 思路

### 1.1 整体流水线

```text
compute_similarity(self, other)
    │
    ├─ [硬约束] 上下文：foreground_activity、Dialog 启发
    │              不通过 → return 0.0
    │
    ├─ [硬约束] 交互：从 get_all_widgets() 抽动作签名
    │              冲突 → return 0.0
    │
    ├─ [硬约束] 语义：Widget 的 text / content_desc / resource_id
    │              冲突 → return 0.0
    │
    └─ [结构分] 从 self.views / other.views 建图
                   WL 迭代 → 直方图 → 余弦相似度
                   return S_struct ∈ [0, 1]
```

**原则**：硬约束只做 **否决（return 0）**；**唯一连续分数** 来自 WL。不做 `w1·A + w2·B` 加权。

### 1.2 与现有调用关系

```text
__process_state()
  → __find_most_similar()          # threshold = 0.6
       → compute_similarity(root_state)

__guide_check()
  → compute_similarity(target_state)   # __current_similarity_check ≈ 0.6
```

返回值仍是 `float`，阈值逻辑 **零改动**。

### 1.3 数据来源

| 用途              | 已有来源                                                               |
| --------------- | ------------------------------------------------------------------ |
| 图节点             | `DeviceState.views[i]`（`visible == True`）                          |
| 图边              | `views[i]['parent']`、`views[i]['children']`                        |
| 节点 class/res-id | `view['class']`、`view['resource_id']`（同 `Widget.get_class()` 规则）   |
| 节点 role         | `view['clickable']` 等（同 `Widget` 构造逻辑）                             |
| 深度              | BFS 从 `parent == -1` 根；或复用 `__calculate_depth` 写入的 `view['depth']` |
| Activity        | `DeviceState.foreground_activity`                                  |
| 动作/语义           | `DeviceState.get_all_widgets()` → `Widget` 已有方法                    |



## 实现

### Step 1：上下文兼容（cannot-link）

- `self.foreground_activity != other.foreground_activity` → `0.0`
- 扫描 `views` 中 `view['class']` 是否含 `Dialog` / `PopupWindow` → 区分 `activity` / `dialog`；类型不同 → `0.0`

### Step 2：动作冲突（cannot-link）

遍历 `get_all_widgets()`，对每个 `Widget` 根据已有属性生成签名元组，例如：

```text
(action_type, widget.get_class(), widget.get_resource_id())
```

`action_type` 由已有 `get_clickable()` / `get_editable()` / `get_scrollable()` / `get_checkable()` 决定（与 `Widget` 里 `action_mask` 一致）。

冲突规则（示例）：

- 双方签名集均 ≥2 且交集为空 → 冲突  
- 一方仅有 scroll、另一方有 click → 冲突  

### Step 3：语义冲突（cannot-link）

从 `Widget.get_text()`、`get_content_desc()`、`get_resource_id()` 抽 **稳定 token**（过滤纯数字等动态串）。

- 双方稳定锚点均 ≥2 且交集为空 → 冲突  
- 双方都有标题类文本且明显不同 → 冲突  

### Step 4：从 `views` 建 Widget 图 / 树

1. 筛 `view['visible']` 为真的节点，跳过 `navigationBarBackground` / `statusBarBackground`  
2. 用 `view['temp_id']` 建 `temp_id → 局部下标` 映射  
3. 建图方式分为两档，先保守落地，再按误合并 case 增强：

| 版本 | 表示方式 | 优点 | 风险 / 代价 | 适用阶段 |
| --- | --- | --- | --- | --- |
| 保守版 | 无向图 WL：`parent-child` 统一作为邻居 | 实现简单，对轻微层级变化更宽容，适合先替换现有 Dice 结构分 | 会弱化父子方向、兄弟顺序和容器层级语义 | 第一阶段实验 |
| 增强版 | 有向 / 有序树 WL：区分 `parent`、`children`、`sibling order` | 更贴近 Android UI hierarchy，可区分“按钮在容器下”和“按钮附近有容器”这类布局差异 | 对无意义 wrapper、Compose/RecyclerView 包装层更敏感，可能增加误拆分 | 误合并仍明显时启用 |

默认建议先实现保守版：对每个节点，若 `parent` 在映射中则连无向边，并遍历 `children` 补边。若实验发现“控件集合相同但层级关系不同”的页面仍被合并，再切到增强版，把 UI hierarchy 当作有根有序树处理。

增强版需要保留三类信息：

- `parent_label`：父节点标签，表达节点所处容器语义  
- `ordered_child_labels`：按 `children` 原始顺序排列的子节点标签，表达布局展开方式  
- `sibling_bucket`：兄弟节点位置粗分桶，表达控件在同层的大致顺序，避免完全依赖像素坐标  

### Step 5：WL 迭代（h=2）

- 初始标签：`(class_short, res_id_short, role, depth_bucket)`  
- 保守版每轮：`new_label[i] = hash(old_label[i], sorted(neighbor_labels))`  
- 增强版每轮：`new_label[i] = hash(old_label[i], parent_label, ordered_child_labels, sibling_bucket)`  
- 2 轮后得到每个节点的 WL 标签  

### Step 6：相似度

- `phi = Counter(WL标签)`  
- `S_struct = dot(phi1, phi2) / (||phi1|| * ||phi2||)`  
- 作为 `compute_similarity` 返回值  

### Step 7：退化

可见节点过少（如 <3）→ 用 `view['class']` + role 的 multiset 余弦

---

## 代码

### 3.1 辅助：从已有 `view` 取 role（与 `Widget` 一致）

```python
# 可读 view dict，逻辑对齐 widget.py 中 __init_from_view
def _view_role(view: dict) -> str:
    if DeviceState._DeviceState__safe_dict_get(view, 'editable'):
        return 'input'
    if DeviceState._DeviceState__safe_dict_get(view, 'checkable'):
        return 'check'
    if DeviceState._DeviceState__safe_dict_get(view, 'scrollable'):
        return 'scroll'
    if DeviceState._DeviceState__safe_dict_get(view, 'clickable'):
        return 'click'
    text = DeviceState._DeviceState__safe_dict_get(view, 'text', '') or \
           DeviceState._DeviceState__safe_dict_get(view, 'content_description', '')
    return 'text' if text and str(text).strip() else 'layout'
```

更干净的做法：在 `device_state.py` 内用已有的 `__safe_dict_get` 静态方法（同文件 366 行），不访问 private name：

```python
@staticmethod
def _view_role(view):
    if DeviceState.__safe_dict_get(view, 'editable'):
        return 'input'
    if DeviceState.__safe_dict_get(view, 'checkable'):
        return 'check'
    if DeviceState.__safe_dict_get(view, 'scrollable'):
        return 'scroll'
    if DeviceState.__safe_dict_get(view, 'clickable'):
        return 'click'
    return 'layout'
```

### 3.2 从 `DeviceState.views` 建图

保守版先把 UI hierarchy 当作无向图：父子关系只作为“邻居”参与 WL。这样对多一层无意义容器、少一层包装节点的页面更宽容，适合作为第一阶段替换现有结构分。

```python
from collections import Counter, deque

_SYSTEM_BARS = {
    'android:id/navigationBarBackground',
    'android:id/statusBarBackground',
}

def _build_graph_from_views(views):
    """返回: node_views(list[dict]), adj(dict[int,set[int]])"""
    node_views = []
    temp_id_to_idx = {}

    for view in views:
        if not DeviceState.__safe_dict_get(view, 'visible'):
            continue
        if DeviceState.__safe_dict_get(view, 'resource_id') in _SYSTEM_BARS:
            continue
        temp_id_to_idx[view['temp_id']] = len(node_views)
        node_views.append(view)

    adj = {i: set() for i in range(len(node_views))}

    def _link(i, j):
        adj[i].add(j)
        adj[j].add(i)

    for idx, view in enumerate(node_views):
        parent_id = DeviceState.__safe_dict_get(view, 'parent', -1)
        if parent_id in temp_id_to_idx:
            _link(idx, temp_id_to_idx[parent_id])
        for child_id in DeviceState.__safe_dict_get(view, 'children', []) or []:
            if child_id in temp_id_to_idx:
                _link(idx, temp_id_to_idx[child_id])

    return node_views, adj
```

增强版把 UI hierarchy 当作有根有序树：父节点、子节点顺序、兄弟位置分开编码。它更能区分真实布局差异，但也更容易被 wrapper 层和列表项数量影响，因此建议在保守版仍有误合并时再启用。

```python
def _build_ordered_tree_from_views(views):
    """返回: node_views, parent_idx, children_idx"""
    node_views = []
    temp_id_to_idx = {}

    for view in views:
        if not DeviceState.__safe_dict_get(view, 'visible'):
            continue
        if DeviceState.__safe_dict_get(view, 'resource_id') in _SYSTEM_BARS:
            continue
        temp_id_to_idx[view['temp_id']] = len(node_views)
        node_views.append(view)

    parent_idx = {i: -1 for i in range(len(node_views))}
    children_idx = {i: [] for i in range(len(node_views))}

    for idx, view in enumerate(node_views):
        parent_id = DeviceState.__safe_dict_get(view, 'parent', -1)
        if parent_id in temp_id_to_idx:
            parent_idx[idx] = temp_id_to_idx[parent_id]

        for child_id in DeviceState.__safe_dict_get(view, 'children', []) or []:
            if child_id in temp_id_to_idx:
                children_idx[idx].append(temp_id_to_idx[child_id])

    return node_views, parent_idx, children_idx
```

### 3.3 初始标签 + WL

```python
def _initial_label(view, depth):
    clazz = (DeviceState.__safe_dict_get(view, 'class') or 'Unknown').split('.')[-1]
    res_id = (DeviceState.__safe_dict_get(view, 'resource_id') or '').split('/')[-1]
    role = _view_role(view)
    depth_bucket = min(depth // 2, 8)
    return (clazz, res_id, role, depth_bucket)

def _bfs_depth(adj, root=0):
    depths = {root: 0}
    q = deque([root])
    while q:
        u = q.popleft()
        for v in adj.get(u, ()):
            if v not in depths:
                depths[v] = depths[u] + 1
                q.append(v)
    return depths

def _wl_histogram(node_views, adj, iterations=2):
    if not node_views:
        return Counter()

    depths = _bfs_depth(adj, root=0)
    labels = {
        i: _initial_label(node_views[i], depths.get(i, 0))
        for i in range(len(node_views))
    }

    for _ in range(iterations):
        new_labels = {}
        for i in range(len(node_views)):
            neighbor_tags = sorted(labels[j] for j in adj.get(i, ()))
            new_labels[i] = hash((labels[i], tuple(neighbor_tags)))
        labels = new_labels

    return Counter(labels.values())
```

增强版 WL 不再把所有邻居混成一个排序集合，而是显式区分父节点与有序子节点：

```python
def _sibling_bucket(index, parent_idx, children_idx):
    parent = parent_idx.get(index, -1)
    if parent == -1:
        return 'root'
    siblings = children_idx.get(parent, [])
    if not siblings:
        return 'single'
    pos = siblings.index(index)
    ratio = pos / max(1, len(siblings) - 1)
    if ratio <= 0.33:
        return 'front'
    if ratio <= 0.66:
        return 'middle'
    return 'back'

def _ordered_tree_wl_histogram(node_views, parent_idx, children_idx, iterations=2):
    if not node_views:
        return Counter()

    root = next((i for i, parent in parent_idx.items() if parent == -1), 0)
    undirected_adj = {i: set(children_idx.get(i, [])) for i in range(len(node_views))}
    for child, parent in parent_idx.items():
        if parent != -1:
            undirected_adj.setdefault(child, set()).add(parent)
            undirected_adj.setdefault(parent, set()).add(child)

    depths = _bfs_depth(undirected_adj, root=root)
    labels = {
        i: _initial_label(node_views[i], depths.get(i, 0))
        for i in range(len(node_views))
    }

    for _ in range(iterations):
        new_labels = {}
        for i in range(len(node_views)):
            parent = parent_idx.get(i, -1)
            parent_label = labels[parent] if parent != -1 else 'ROOT'
            child_labels = tuple(labels[j] for j in children_idx.get(i, []))
            sibling_pos = _sibling_bucket(i, parent_idx, children_idx)
            new_labels[i] = hash((labels[i], parent_label, child_labels, sibling_pos))
        labels = new_labels

    return Counter(labels.values())
```

### 3.4 结构相似度

```python
def _cosine_counter(c1: Counter, c2: Counter) -> float:
    if not c1 or not c2:
        return 0.0
    keys = set(c1) | set(c2)
    dot = sum(c1[k] * c2[k] for k in keys)
    n1 = sum(v * v for v in c1.values()) ** 0.5
    n2 = sum(v * v for v in c2.values()) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)

def _structural_similarity(state_a, state_b) -> float:
    views_a, adj_a = _build_graph_from_views(state_a.views)
    views_b, adj_b = _build_graph_from_views(state_b.views)
    phi_a = _wl_histogram(views_a, adj_a)
    phi_b = _wl_histogram(views_b, adj_b)
    return _cosine_counter(phi_a, phi_b)
```

### 3.5 硬约束（用已有 Widget API）

```python
def _action_signatures(state):
    sigs = set()
    for widget in state.get_all_widgets():
        clazz = widget.get_class()
        res_id = widget.get_resource_id()
        if widget.get_editable():
            sigs.add(('input', clazz, res_id))
        if widget.get_checkable():
            sigs.add(('check', clazz, res_id))
        if widget.get_scrollable():
            sigs.add(('scroll', clazz, res_id))
        if widget.get_clickable():
            sigs.add(('click', clazz, res_id))
    return sigs

def _semantic_anchors(state):
    anchors = set()
    for widget in state.get_all_widgets():
        for text in (widget.get_text(), widget.get_content_desc()):
            if text and len(text.strip()) >= 2 and not text.strip().isdigit():
                anchors.add(text.strip().lower())
        rid = widget.get_resource_id()
        if rid:
            anchors.add(rid.lower())
    return anchors

def _context_compatible(a, b) -> bool:
    if a.foreground_activity != b.foreground_activity:
        return False
    # Dialog 启发：扫 views['class']
    def _is_dialog(state):
        for view in state.views:
            if not DeviceState.__safe_dict_get(view, 'visible'):
                continue
            clazz = DeviceState.__safe_dict_get(view, 'class', '') or ''
            if 'Dialog' in clazz or 'PopupWindow' in clazz:
                return True
        return False
    return _is_dialog(a) == _is_dialog(b)

def _has_action_conflict(a, b) -> bool:
    sa, sb = _action_signatures(a), _action_signatures(b)
    if len(sa) >= 2 and len(sb) >= 2 and not (sa & sb):
        return True
    return False

def _has_semantic_conflict(a, b) -> bool:
    aa, ab = _semantic_anchors(a), _semantic_anchors(b)
    if len(aa) >= 2 and len(ab) >= 2 and not (aa & ab):
        return True
    return False
```

### 3.6 替换 `compute_similarity`（唯一对外入口）

```python
def compute_similarity(self, other: 'DeviceState') -> float:
    if not _context_compatible(self, other):
        return 0.0
    if _has_action_conflict(self, other):
        return 0.0
    if _has_semantic_conflict(self, other):
        return 0.0
    return _structural_similarity(self, other)
```

上述私有函数可放在同文件末尾，或 `desc/page_similarity.py`；**不新增** `DeviceState` 成员字段。

## 验证

1. 实现 `_structural_similarity`（仅 WL），替换 Dice，验证 cluster 行为  
2. 加 `_context_compatible`  
3. 加 `_has_action_conflict`、`_has_semantic_conflict`  
4. 在 1–2 个 app 上对比 cluster 数、误合并 case，微调 threshold（仍用 0.6 起步）
