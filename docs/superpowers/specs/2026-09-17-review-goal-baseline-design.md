# 阶段 0：只读审查目标状态基线

## 目标

将 `s17code.py` 中与目标生命周期有关的可靠部分提炼为纯 Python 状态机，为后续代码变更审查服务提供完成门控基础。阶段 0 不执行审查、不调用 LLM、不读取或修改被审查代码。

## 范围

本阶段直接在仓库根目录建立 Python 项目基础：

```text
app/
  runtime/
    goal.py
tests/
  unit/
    test_goal.py
pyproject.toml
README.md
```

`s16code.py`、`s17code.py` 与 `recode.md` 继续作为根目录中的学习参考，不被最终运行时导入，也不作为应用入口。

## 设计

### 纯状态内核

`app/runtime/goal.py` 将包含以下无 I/O 类型：

- `GoalState`：保存完成条件、开始时间、评估次数和最后原因。
- `GoalEvaluation`：评估结果，含 `ok`、`reason`、`impossible`。
- `StopDecision`：状态机输出，含 `action` 与 `reason`。
- `GoalController`：设置、清除、查询、评估目标以及从事件恢复。

状态机不依赖 Anthropic SDK、环境变量、文件系统、CLI、网络或用户交互。它通过一个最小 evaluator 协议接收评估结果；测试使用确定性 fake evaluator。

### 状态语义

状态机沿用 s17 的核心语义：

| 决策 | 含义 | 阶段 0 对外状态 |
| --- | --- | --- |
| `achieved` | 评估器证明完成条件已经满足 | `achieved` |
| `failed` | 输入或目标已被证明不可能完成 | `failed` |
| `block` | 条件尚未满足，仍需要后续工作 | `incomplete` |
| `limit` | 连续补偿超过上限，目标仍未完成 | `incomplete` |
| `defer` | 后台任务尚在运行 | `incomplete` |
| `error` | 评估器自身出错，目标保持活跃 | `incomplete` |

`failed` 仅用于 `impossible=True` 的明确失败；普通尚未完成不是失败。后续阶段的 `ReviewGoalController` 会以同一语义将确定性 Completion Gate 的阶段快照映射为 `GoalEvaluation`。

### 事件与恢复

每次设置、评估、清除或终止都会追加一个普通字典事件。事件至少包含目标条件、是否活跃、是否达成、是否失败、原因、评估次数及持续时间。`GoalController.restore()` 从最后一个目标状态事件还原活跃目标或最终状态；阶段 0 不负责写入 journal，阶段 2 再由 s16 的持久化运行时承接。

### 安全边界

本阶段明确不提供：

- `bash`、`read_file`、`write_file`、`edit_file`、`glob` 等模型工具；
- 通用 `AgentSession` 或 agent loop；
- 代码仓库访问、diff 解析、模型调用或数据库连接；
- 用户输入 `/goal` 的命令行模式；
- destructive command 检查，因为系统根本不执行命令。

因此任何未来审查 Agent 都必须经由受控只读上下文接入，而不能继承通用 Coding Agent 权限。

## 验收与测试

`tests/unit/test_goal.py` 将用 fake evaluator 覆盖：

1. 设置有效目标后记录活跃状态事件；
2. 固定成功评估得到 `achieved`，目标结束；
3. 固定不可完成评估得到 `failed`，目标结束；
4. 固定未完成评估得到 `block`，目标仍活跃且可映射为 `incomplete`；
5. 超过阻塞上限得到 `limit`，仍映射为 `incomplete`；
6. evaluator 抛错得到 `error`，目标保持活跃；
7. 用既有活跃事件恢复后可继续评估；用最终事件恢复后不重建活跃目标。

验收命令为：

```powershell
python -m pytest tests/unit/test_goal.py -v
```

预期所有测试通过，且代码中不存在 `AgentSession`、文件工具定义或命令执行能力。

## 后续衔接

阶段 1 在这个纯状态机之上创建 `ReviewGoalController` 与确定性 Completion Gate；阶段 2 才将 s16 的并发工作流、journal、runId 与跨平台锁引入运行时。

## 学习来源

本项目的目标生命周期设计参考 learn-claude-code 的 s17 Goal Loop；可恢复工作流设计将在后续阶段参考 s16 Workflow Runtime。两份参考源码保留在本仓库根目录，供追溯与学习使用。
