# Code Change Review Agent

一个面向后端代码变更的只读风险审查服务。本仓库当前完成阶段 0：无 I/O 的目标状态内核，为后续确定性审查完成门控提供 `achieved`、`failed` 与 `incomplete` 语义。

## 当前安全边界

阶段 0 不提供模型工具、shell 命令、文件读写、仓库访问、Diff 解析、数据库连接或 LLM 调用。`app.runtime.goal.GoalController` 只接收调用方传入的完成条件和阶段快照。

## 本地验证

```powershell
python -m pytest tests/unit/test_goal.py -v
```

## 阶段 1：确定性完成门控

`ReviewCompletionGate` 只依据 Pydantic 审查快照判定报告能否发布：预筛、三类专职 Agent、warning、Finding 证据与新增行位置、聚合和最终报告结构都必须闭环。它不调用 LLM；非法输入或全部 Agent 失败为 `failed`，可补偿的缺失为 `incomplete`，完整报告为 `achieved`。

## 学习来源

目标生命周期设计参考 [learn-claude-code 的 s17 Goal Loop](https://github.com/shareAI-lab/learn-claude-code/tree/main/s17_goal_loop)。后续可恢复工作流设计将参考同项目的 s16 Workflow Runtime。根目录中的 `s16code.py` 和 `s17code.py` 是学习参考，不被应用运行时代码导入。
