可行，而且比“只改 s16”更容易讲出完整的工程故事：**用 s17 作为外层的目标与完成门控，用 s16 的工作流机制作为内层的并行审查执行器。**

但不能直接保留 s17 的原样 AgentSession。它本质是一个可读写代码仓库的通用 Coding Agent；我们的项目应是只读风险审查服务。s17 负责“什么时候算完成”，s16 负责“多个审查步骤如何并发、记录与恢复”。[s17 源码](https://github.com/shareAI-lab/learn-claude-code/blob/main/s17_goal_loop/code.py) [s16 源码](https://github.com/shareAI-lab/learn-claude-code/tree/main/s16_workflow_runtime)

## 最终架构

```text
POST /v1/reviews
      │
      ▼
ReviewGoalController（s17 思想）
设定完成条件：报告完整、证据有效、阶段已闭环
      │
      ▼
ReviewWorkflowRuntime（s16 思想）
解析 → 预筛 → 三 Agent 并行 → 验证 → 聚合
      │
      ▼
Completion Gate
完整：completed
缺失：failed / incomplete，并给出原因
      │
      ▼
报告、runId、journal、评测指标、追踪事件
```

## 新项目目录

```text
code-change-review-agent/
  app/
    api/
      routes.py
      schemas.py
    runtime/
      workflow.py
      journal.py
      task.py
      locks.py
      runner.py
      registry.py
      goal.py
    domain/
      contracts.py
      rules.py
    review/
      diff_parser.py
      prefilter.py
      context_builder.py
      prompts.py
      agents.py
      verifier.py
      aggregation.py
      workflow.py
      completion_gate.py
    tools/
      diff_tool.py
      rules_tool.py
      test_summary_tool.py
    storage/
      models.py
      repositories.py
    observability.py
    main.py
  evals/
    dataset.py
    run.py
  tests/
    unit/
    integration/
    fixtures/
  docker-compose.yml
  pyproject.toml
  .env.example
  README.md
```

## 阶段 0：建立 s17 改造基线

新项目中复制或 Fork `s17_goal_loop`，保留 README 的学习来源说明。

保留：

- `GoalState`
- `GoalEvaluation`
- `StopDecision`
- `GoalController`
- 目标状态事件
- 状态恢复思想
- 目标长度、迭代上限、失败/不可能完成状态

删除：

- `bash`
- `read_file`
- `write_file`
- `edit_file`
- `glob`
- 通用 Coding Agent 的 `AgentSession`
- 用户在命令行输入 `/goal` 的交互模式
- 对仓库文件的读写与 destructive command 检查

原因：审查系统不应给模型修改代码的能力，用户只提交 Diff 和 CI 摘要。

验收：运行一个固定假目标，能得到 `achieved`、`failed`、`incomplete` 三种状态。

提交建议：

```text
chore: initialize review workflow from s17 goal loop
```

## 阶段 1：把 s17 改为审查完成门控

创建 `ReviewGoalController`，不再让另一个 LLM 根据完整聊天记录判断完成，而是用确定性规则判断：

```text
完成条件：
- 预筛已执行；
- 三类 Agent 均有合法结果，或记录了失败 warning；
- 每个 Finding 都有文件、行号、证据、规则编号；
- Finding 引用的行号确实属于输入 Diff 的新增行；
- 聚合已经完成；
- 最终报告符合 Pydantic Schema。
```

保留 s17 的语义：

- `achieved`：报告可发布；
- `block`：仍缺阶段或证据；
- `failed`：输入无效或工作流无法完成；
- `limit`：超过允许的补偿次数；
- `defer`：等待后台 Agent 结果。

这里不要直接复用 s17 的 LLM Goal Evaluator。代码审查报告的完成标准是明确的，确定性 Gate 更稳定、成本更低，也更容易解释。

测试：

- 缺少测试影响 Agent 的结果时，Gate 返回 `block`；
- Finding 缺少 `evidence` 时，Gate 返回 `block`；
- 高风险 Finding 完整且所有阶段结束时，Gate 返回 `achieved`；
- 一个 Agent 超时但 warning 已记录时，允许完成。

提交建议：

```text
feat: add deterministic review completion gate
```

## 阶段 2：引入 s16 的工作流运行时

从 s16 吸收并拆分：

- `WorkflowTool`
- `ExecutionState`
- `parallel()`
- `pipeline()`
- `WorkflowJournal`
- stable call key
- `LocalWorkflowTask`
- 进度事件
- token 预算
- workflow registry
- resume 逻辑

注意：s16 使用的 `fcntl` 不兼容 Windows。`locks.py` 要改成跨平台锁，或使用 Windows 可用的文件锁库。

工作流注册表只注册一个可信工作流：

```python
WORKFLOWS = {
    "review-backend-change": (REVIEW_META, review_backend_change),
}
```

模型不能提交任意 workflow 名或任意脚本。

测试：

- 未知工作流被拒绝；
- 三个 async task 真正并发启动；
- 同一 `runId` 不可重复并发执行；
- resume 后已记录的 Agent 调用不重复执行；
- 错误的 runId、变更后的参数、损坏的 journal 都被拒绝。

提交建议：

```text
feat: add resumable review workflow runtime
```

## 阶段 3：建立审查领域模型与 Diff 解析

实现 Pydantic 模型：

```text
Severity
Finding
AgentReport
ReviewContext
ReviewReport
StaticRuleHit
ReviewRunStatus
```

`Finding` 必须包含：

```text
category
severity
file_path
line_start
evidence
rule_id
recommendation
confidence
source_agents
```

实现 Unified Diff parser：

- 仅提取新增行；
- 保留文件路径与新文件行号；
- 不接受空 Diff、二进制 Diff、超过 500 KB 的输入；
- 所有后续证据必须对应 parser 产出的新增行。

测试：

- 正确提取多文件、新增行与行号；
- 删除行不被当作审查目标；
- `/dev/null` 文件被正确处理；
- 不存在于 Diff 中的 Finding 行号被 Completion Gate 拒绝。

提交建议：

```text
feat: add typed review context and unified diff parser
```

## 阶段 4：实现确定性预筛

先实现五条规则：

```text
SEC-001  字符串拼接 SQL
SEC-002  日志打印 access token / Authorization / Bearer
CON-001  支付或退款改动缺少幂等性标记
CON-002  缓存或 Redis 改动缺少事务标记
TST-001  服务代码变更但没有测试变更
```

每次命中返回：

```text
rule_id
file_path
line_start
excerpt
target_agent
```

预筛不替代 LLM 审查；它负责缩小上下文、提供可追溯的确定性证据。

测试：每条规则对应一个 fixture，并增加“相似但不应误报”的 fixture。

提交建议：

```text
feat: add deterministic backend risk prefilter
```

## 阶段 5：建立受限只读工具

先实现内部工具契约：

```text
DiffTool.read_diff()
RulesTool.search_rules(query, domain, limit)
TestSummaryTool.get_test_summary()
```

规则库使用 MySQL：

- Docker Compose 启动 MySQL；
- `review_rules` 表包含 `rule_id`、`domain`、`content`、`created_at`；
- 关键词检索必须使用参数化查询；
- 按 domain 限制检索结果；
- Agent 不直接持有数据库连接。

这一阶段可以先使用普通 Python 工具类。等内部工具接口稳定后，再用 FastMCP 暴露为真正的 MCP Server；在完成前，README 和简历不能写“已实现 MCP”。

测试：

- security Agent 无法查询 consistency 规则；
- 工具接口不存在 `insert`、`update`、`delete`；
- 查询 `SQL injection` 能返回 `SEC-001`；
- 环境变量缺失或数据库无法连接时，返回明确错误。

提交建议：

```text
feat: add read-only engineering rule tools
```

## 阶段 6：实现三个专职 Agent

创建：

```text
SecurityReviewer
ConsistencyReviewer
TestImpactReviewer
```

每个 Agent 使用独立的上下文、独立 prompt 与限定工具：

| Agent | 可见上下文 | 可用规则 |
|---|---|---|
| Security | Diff、security 命中 | security |
| Consistency | Diff、consistency 命中 | consistency |
| Test Impact | Diff、CI 摘要、测试命中 | testing |

Prompt 必须要求：

- 仅基于输入事实；
- 证据不足则返回空数组；
- 不得编造位置；
- 不得执行代码；
- 只返回符合 `AgentReport` 的 JSON。

先用 Fake Runner 测试；再接入 PydanticAI Runner。真实模型输出不合法时，运行时只重试一次，仍失败则转为 warning。

测试：

- 每个 Agent 针对自己的 fixture 返回至少一个有效 Finding；
- domain 越权的规则检索失败；
- 无风险 fixture 返回空 Finding；
- 不合法 JSON 触发一次重试；
- 第二次仍不合法则记录 warning。

提交建议：

```text
feat: add bounded specialist review agents
```

## 阶段 7：实现核心审查工作流

固定工作流：

```text
Build Context
    ↓
Static Prefilter
    ↓
parallel(
  SecurityReviewer,
  ConsistencyReviewer,
  TestImpactReviewer
)
    ↓
parallel(Verify each candidate Finding)
    ↓
Aggregate
    ↓
ReviewGoalController / Completion Gate
```

验证阶段使用独立的 Verifier，职责只有一个：检查候选 Finding 是否被输入 Diff 和规则证据支持。

聚合规则：

```text
去重键：(rule_id, file_path, line_start)
风险等级：high > medium > low
来源：合并所有 source_agents
排序：severity → confidence → rule hit
高风险：requires_human_review = true
```

一个 Agent 出错不会中断整体审查；它成为 warning。三个 Agent 都失败则整个 run failed。

测试：

- 三个 Agent 并发；
- 两个 Agent 命中同一 `SEC-001`，最终只保留一条；
- Agent 失败不抹掉其他发现；
- 任一 Finding 无法验证时被移除或降级为 warning；
- Gate 阻止未聚合的报告发布。

提交建议：

```text
feat: orchestrate and verify parallel review workflow
```

## 阶段 8：API、runId 与恢复

实现：

```text
POST /v1/reviews
GET  /v1/reviews/{run_id}
POST /v1/reviews/{run_id}/resume
```

`POST /v1/reviews` 返回：

```json
{
  "run_id": "wf_review-backend-change_...",
  "status": "completed",
  "risk_level": "high",
  "findings": [],
  "warnings": []
}
```

恢复逻辑：

- 使用原始 runId；
- 参数必须与首次请求一致；
- 已完成 Agent 从 journal 命中；
- 只有失败或新增的下游步骤重新运行；
- 输出事件包含 cached / done / failed 状态。

提交建议：

```text
feat: expose resumable review API
```

## 阶段 9：评测、观测与面试演示

准备 12–24 个 Diff fixture：

- security、consistency、test impact 各至少 4 个；
- 至少 3 个无风险样例；
- 每个样例定义预期规则、风险等级、目标行号。

指标：

```text
Schema-validity rate
High-risk recall
Rule-ID precision
Evidence location validity
Tool-call correctness
Agent latency
Resume cache-hit rate
```

OpenTelemetry 至少记录：

```text
review.run
review.prefilter
review.agent
review.verifier
review.aggregate
review.completion_gate
review.tool.rules
```

禁止记录完整 Diff；只记录 runId、Agent 名、耗时、Finding 数、错误类型。

最终演示脚本：

1. 提交 `unsafe_sql.diff`；
2. 展示三个 Agent 并行进度；
3. 得到 `SEC-001`、文件、行号、证据和 high 风险；
4. 展示 Gate 判定 `achieved`；
5. 用同一 runId resume；
6. 展示 Agent 调用被 journal 缓存复用。

## 面试时的项目定位

你可以这样讲：

> 我以 Goal Loop 作为审查报告的完成门控，以可恢复 Workflow Runtime 作为多 Agent 编排内核。系统不是让 Agent 自由聊天，而是把解析、预筛、并行审查、证据验证和确定性聚合写成固定工作流；所有 Agent 只共享受控的只读上下文，最终由确定性 Gate 判断报告是否具备发布条件。

等你新建仓库并把源码下载好，把项目绝对路径发给我。我们就按阶段 0 开始：先将 s17 的通用读写 Coding Agent 收缩为只读审查运行时。