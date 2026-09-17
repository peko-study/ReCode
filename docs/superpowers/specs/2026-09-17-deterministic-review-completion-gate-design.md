# 阶段 1：确定性审查完成门控

## 目标

在阶段 0 的纯目标状态机之上，实现不依赖 LLM 的 `ReviewGoalController` 与 `ReviewCompletionGate`。它只根据结构化审查快照判定报告是否可以发布，保证完成标准稳定、可解释且可测试。

## 范围

本阶段新增最小 Pydantic 领域契约和完成门控：

```text
app/
  domain/
    __init__.py
    contracts.py
  review/
    __init__.py
    completion_gate.py
  runtime/
    goal.py                 # 保留通用 GoalController，不写审查规则
tests/
  unit/
    test_contracts.py
    test_completion_gate.py
```

不实现 Diff parser、预筛规则、真实 Agent、LLM Runner、工作流并发、journal、数据库或 HTTP API。调用方在本阶段构造审查快照；阶段 2 以后由固定工作流生成它。

## 领域契约

`app/domain/contracts.py` 使用 Pydantic v2 定义以下模型：

- `Severity`：`high`、`medium`、`low`。
- `ReviewAgent`：`security`、`consistency`、`test_impact`。
- `Finding`：`category`、`severity`、`file_path`、`line_start`、`evidence`、`rule_id`、`recommendation`、`confidence`、`source_agents` 均为必填字段；`line_start >= 1`，`confidence` 位于 `[0, 1]`。
- `AgentReport`：一个专职 Agent 的 `agent`、`completed`、`findings` 与可选 `warning`。正常完成可以返回空 findings；未完成必须在 Gate 层附带非空 warning 才能作为可容忍失败。
- `ReviewReport`：`prefilter_completed`、三个 `agent_reports`、聚合后的 `findings`、`warnings`、`aggregation_completed`。
- `ReviewCompletionSnapshot`：一个 `ReviewReport` 加上 `added_lines`，后者是由文件路径到新增行号集合的映射。

Pydantic 负责类型、必填字段、枚举和值域。空白字符串（如空 evidence）保持为结构合法但业务不完整，由 Gate 返回 `block`，而非把可修复的报告判为无效输入。

## 完成门控

`ReviewCompletionGate` 实现阶段 0 的 `GoalEvaluator` 协议：`evaluate(condition, snapshot) -> GoalEvaluation`。`condition` 由通用目标状态机保存，Gate 不从自然语言推断结论。

评估顺序固定如下：

1. 将原始 `snapshot` 用 `ReviewCompletionSnapshot.model_validate()` 解析。解析失败代表调用方提供无效输入，返回 `GoalEvaluation(ok=False, impossible=True)`，从而得到 `failed`。
2. `prefilter_completed` 为 `False` 时返回 `block`。
3. 检查恰好存在 security、consistency、test_impact 三份 AgentReport；遗漏、重复或未知 Agent 均返回 `block`。
4. 每份 `completed=False` 的报告必须有非空 warning；否则返回 `block`。有 warning 的单 Agent 失败可继续。
5. 若三个专职 Agent 都未完成，则工作流无法取得审查结果，返回 `failed`；这与后续核心工作流的失败语义一致。
6. `aggregation_completed` 为 `False` 时返回 `block`。
7. 对聚合后的每个 Finding 检查业务完整性：所有文本字段非空、来源 Agent 非空、行号有效、confidence 合法。任一缺失返回 `block`。
8. 将 Finding 的 `file_path` 和 `line_start` 与 `added_lines` 核对。文件不存在或该行不是新增行时返回 `block`。
9. 所有检查通过，返回 `achieved`。

Gate 按首个失败条件给出稳定原因字符串，便于日志、测试和后续 API 返回。它不修改报告、不删除 Finding，也不重试 Agent。

## 控制器适配

`ReviewGoalController` 是 `GoalController` 的窄适配层：默认完成条件为“review report is publishable”，内部注入 `ReviewCompletionGate`。它复用阶段 0 的事件、恢复、`block_cap`、`defer`、`limit` 与状态映射；新方法 `evaluate_review(snapshot, background_running=False)` 仅将结构化快照传入既有 `evaluate()`。

这使审查业务规则不污染通用目标状态机，也让阶段 2 的 workflow runtime 能继续通过同一协议调用 Gate。

## 状态语义

| 条件 | Goal 决策 | 对外状态 |
| --- | --- | --- |
| Pydantic 解析失败；三个 Agent 都失败 | `failed` | `failed` |
| 阶段、Agent、warning、证据、行号或聚合缺失 | `block` | `incomplete` |
| 后台 Agent 仍在运行 | `defer` | `incomplete` |
| 所有条件满足 | `achieved` | `achieved` |

`limit` 与 `error` 沿用阶段 0：前者在连续 block 超限后出现，后者仅代表 Gate 自身的未预期异常；两者均映射为 `incomplete`。

## 测试与验收

新增单元测试将覆盖：

1. Pydantic 对缺少必填字段、非法 severity、`line_start=0`、越界 confidence 的拒绝；
2. 缺失 test impact Agent 时 Gate 返回 `block`；
3. 空 evidence 的 Finding 返回 `block`；
4. Finding 的行号不属于 `added_lines` 时返回 `block`；
5. 三个 Agent 完成、high Finding 完整且聚合结束时返回 `achieved`；
6. 一个 Agent `completed=False` 且有 warning 时仍可 `achieved`；
7. 一个 Agent 失败但没有 warning 时返回 `block`；
8. 三个 Agent 均失败时返回 `failed`；
9. 非法快照返回 `failed`；
10. `ReviewGoalController` 保留阶段 0 的 `defer` 与三种对外状态映射。

验收命令：

```powershell
python -m pytest -v
```

所有阶段 0 的 7 项测试与阶段 1 测试均应通过；Gate 模块不得包含 Anthropic、subprocess、文件访问或命令执行能力。

## 后续衔接

阶段 2 将提供工作流、进度与 resume；阶段 3 将扩展本阶段的 Pydantic 契约并提供 Unified Diff parser，成为 `added_lines` 的唯一可信来源。阶段 1 不假设这些组件已经存在。
