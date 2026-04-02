# `QueryEngine` 与 SDK/非交互路径

本篇说明没有 REPL 时，系统如何通过 `QueryEngine` 复用同一套 query 内核。

## 1. 为什么还要专门讲 `QueryEngine`

前面几篇文档主要以交互式 REPL 为主线，但这个仓库并不只有一种运行方式。

当系统处于：

- SDK
- print/headless
- 某些远程/控制模式

时，核心执行入口会变成：

- `src/QueryEngine.ts`

这一层主要解释以下问题：

1. 非交互模式如何复用 `query()` 主循环。
2. 没有 REPL 时，消息、权限、transcript、structured output 怎么处理。
3. SDK 看到的消息流是如何从内部消息归一化出来的。

## 2. `QueryEngine` 的角色

关键代码：`src/QueryEngine.ts:184-207`

它维护的内部状态包括：

- `config`
- `mutableMessages`
- `abortController`
- `permissionDenials`
- `totalUsage`
- `readFileState`
- `discoveredSkillNames`
- `loadedNestedMemoryPaths`

`QueryEngine` 不是一次性的纯函数，而是：

> 面向一个 headless 会话的执行控制器

## 3. `submitMessage()` 是非交互模式的总入口

关键代码：`src/QueryEngine.ts:209-1047`

这个方法本质上是在模拟 REPL 那条交互主链路，但去掉了 UI，换成 SDKMessage 流输出。

## 4. `submitMessage()` 前半段：构造本次 headless turn

## 4.1 先拉配置并固定 cwd

关键代码：`src/QueryEngine.ts:213-240`

这一步会拿到：

- `cwd`
- `commands`
- `tools`
- `mcpClients`
- `thinkingConfig`
- `maxTurns`
- `maxBudgetUsd`
- `taskBudget`
- `customSystemPrompt`
- `appendSystemPrompt`
- `jsonSchema`

然后 `setCwd(cwd)`。

结论如下：

- 非交互模式仍然是“项目上下文敏感”的。

## 4.2 包装 `canUseTool` 以跟踪 permission denials

关键代码：`src/QueryEngine.ts:243-271`

在 SDK 模式下，权限拒绝不仅要影响执行，还要写进最终 result：

- `permission_denials`

因此实现里包了一层 wrapper。

## 4.3 预取 system prompt parts

关键代码：`src/QueryEngine.ts:284-325`

这里调用：

- `fetchSystemPromptParts(...)`

然后再拼：

- default system prompt
- custom system prompt
- memory mechanics prompt
- append system prompt

### 4.3.1 memory mechanics prompt 是一个重要区别

如果 SDK 调用者提供了 custom system prompt，且开启了 memory path override，QueryEngine 会额外注入 memory mechanics prompt。

这意味着：

- SDK 调用方可能接入了自定义 memory directory
- 因此需要显式告诉模型如何使用这套 memory 机制

## 5. structured output 在这里被专门接管

关键代码：`src/QueryEngine.ts:327-333`

如果：

- `jsonSchema` 存在
- 当前 tools 里有 synthetic output tool

则会注册 structured output enforcement。

QueryEngine 比 REPL 更强调：

- 可程序化输出约束

## 6. `processUserInputContext`：在 headless 环境里重建 ToolUseContext 近似物

关键代码：`src/QueryEngine.ts:335-395`

虽然没有 REPL，但 QueryEngine 仍然要构造一个足够完整的上下文对象，包含：

- messages
- commands/tools/mcpClients
- `getAppState / setAppState`
- `abortController`
- `readFileState`
- nested memory / dynamic skill tracking
- attribution 与 file history 更新器
- `setSDKStatus`

headless 模式不是简化版 runtime，而是“去 UI 的同内核 runtime”。

## 7. orphaned permission 在 QueryEngine 里有专门恢复逻辑

关键代码：`src/QueryEngine.ts:397-408`

如果存在 `orphanedPermission`，它会在本轮输入开始前先处理掉。

SDK/远程等模式会考虑：

- 上一次会话可能停在“等待权限”中间态

并试图恢复。

## 8. 然后它也会走 `processUserInput(...)`

关键代码：`src/QueryEngine.ts:410-428`

关键点在于：

- QueryEngine 没有另写一套输入语义逻辑。
- 它复用了与 REPL 相同的 `processUserInput(...)`。

所以 slash command、附件、技能 prompt、hook 注入等语义，在非交互模式里仍然生效。

## 9. transcript 持久化在 QueryEngine 里被非常认真地处理

关键代码：`src/QueryEngine.ts:436-463`

源码注释点明：

- 如果用户消息不在进入 query 前就写入 transcript，那么进程中途被杀时，resume 可能找不到任何有效会话。

因此 QueryEngine 会：

- 在进入 query 前就持久化用户消息
- bare 模式 fire-and-forget
- 否则必要时 await 并 flush

这是一段很值得学习的“恢复性设计”。

## 10. 然后发一个 `system_init` 给 SDK 消费方

关键代码：`src/QueryEngine.ts:529-551`

它会把当前 headless session 的能力快照发出去，包括：

- tools
- mcpClients
- model
- permissionMode
- commands
- agents
- skills
- enabled plugins
- fastMode

这让 SDK consumer 在第一条真正业务消息前，就知道当前 session 环境。

## 11. 如果本次输入不需要 query，会直接产出本地结果

关键代码：`src/QueryEngine.ts:556-637`

这和 REPL 中本地 slash command 的行为一致，只不过这里会把结果转成 SDK 可消费的消息类型：

- user replay
- local command output as assistant-style message
- compact boundary message
- 最终 success result

QueryEngine 也承担了协议转换责任。

## 12. 真正进入 query 后，它主要做三类工作

关键代码：`src/QueryEngine.ts:675-1047`

### 12.1 把内部消息记录到 `mutableMessages` 与 transcript

它会处理：

- assistant
- progress
- attachment
- user
- system compact boundary

并按需要记录 transcript。

### 12.2 把内部消息归一化成 SDKMessage

例如：

- assistant -> SDK assistant message
- progress -> SDK progress
- compact boundary -> SDK system compact message
- tool use summary -> SDK summary

### 12.3 管理 headless 模式的终止条件

包括：

- max turns
- max budget USD
- structured output retries
- result success / error_during_execution

## 13. 为什么 `mutableMessages` 与 `messages` 要并存

从实现细节可看出：

- `mutableMessages` 是 QueryEngine 自己维护的长期会话视图
- `messages` 更像本轮 query 期间使用和写 transcript 的工作数组

这样做有助于：

- 在 compact boundary 后主动裁剪旧消息
- 在 SDK 会话里减少长时间堆积

## 14. QueryEngine 与 REPL 的差异总结

| 维度 | REPL | QueryEngine |
| --- | --- | --- |
| 入口 | `onSubmit` / `handlePromptSubmit` | `submitMessage()` |
| 输出 | 更新 UI 状态 | 产出 `SDKMessage` 流 |
| 权限交互 | 可弹对话框 | 通过 handler/control channel |
| transcript | `useLogMessages` 等 UI 路径配合 | 引擎内显式控制 |
| structured output | 可用但不是主目标 | 是重要能力，专门追踪重试上限 |
| 会话环境展示 | UI 上下文 | `system_init` 消息 |

## 15. QueryEngine 与 `query()` 的关系

关系可以概括为：

- `query()` 是内核状态机。
- `QueryEngine` 是 headless 编排器与协议适配层。

它负责：

- 在进入 `query()` 前把 headless session 组织好。
- 在 `query()` 返回消息时把其翻译成 SDK 协议。

## 16. 非交互路径总体图

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A[SDK / print 调用] --> B[QueryEngine.submitMessage]
    B --> C[fetchSystemPromptParts]
    B --> D[processUserInput]
    D --> E{shouldQuery}
    E -- 否 --> F[直接产出本地 SDK 结果]
    E -- 是 --> G["query()"]
    G --> H[内部 Message 流]
    H --> I[normalize 成 SDKMessage]
    I --> J[result / progress / assistant / system_init]
```

## 17. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| QueryEngine 状态 | `src/QueryEngine.ts:184-207` | headless session 控制器内部状态 |
| submitMessage 开始 | `src/QueryEngine.ts:209-325` | system prompt parts、memory prompt、structured output enforcement |
| processUserInputContext 构造 | `src/QueryEngine.ts:335-395` | headless 下的运行时上下文 |
| processUserInput 复用 | `src/QueryEngine.ts:410-428` | 与 REPL 共享输入语义层 |
| 预先写 transcript | `src/QueryEngine.ts:436-463` | resume 正确性的关键 |
| system_init | `src/QueryEngine.ts:529-551` | 向 SDK 暴露能力快照 |
| 进入 query | `src/QueryEngine.ts:675-686` | 复用 query 内核 |
| result / budget / structured output 结束条件 | `src/QueryEngine.ts:971-1047` | headless 模式特有结果控制 |

## 18. 总结

`QueryEngine` 证明了这套工程真正复用的是“内核”，不是“界面”。

- REPL 负责交互表现。
- QueryEngine 负责 headless 编排。
- 两者共用同一个输入语义层、同一个 query 内核、同一套工具与权限机制。

从架构质量上看，这是一种很强的分层：UI 可以换，协议可以换，但对话执行内核仍然稳定复用。
