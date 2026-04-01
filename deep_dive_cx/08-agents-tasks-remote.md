# 多代理、后台任务与远程会话

## 0. 阅读提示

- 这篇聚焦子代理、后台任务和远程会话，不建议孤立阅读。
- 最好先看 [06-tools-and-permissions.md](./06-tools-and-permissions.md) 和 [07-extension-skills-plugins-mcp.md](./07-extension-skills-plugins-mcp.md)，因为这里的大量机制都是沿着工具系统和扩展系统继续展开的。
- 阅读时重点抓住一条主线：`AgentTool` 并不是特殊后门，而是以普通工具协议接入多代理能力。

## 1. Agent 在这套系统里的真实地位

在源码中，子代理不是一个平行子系统，而是工具系统的一部分。

也就是说：

- 主模型通过 `AgentTool` 启动子代理。
- 子代理再运行自己的 `query()`。
- 后台任务、远程任务、worktree 隔离、权限模式都是围绕这一工具调用展开。

所以这篇分析的主线是：

`AgentTool -> runAgent -> LocalAgentTask / RemoteSessionManager`

## 2. `AgentTool`：把“启动子代理”包装成一个工具

关键代码：`src/tools/AgentTool/AgentTool.tsx:196-740`

## 2.1 prompt 与 description

`AgentTool` 自己也像普通工具一样有：

- `prompt(...)`
- `description()`
- `inputSchema`
- `outputSchema`
- `call(...)`

这说明它在协议层与普通工具并无本质差别。

## 2.2 输入参数透露了能力范围

从 schema 与 `call(...)` 参数可见，AgentTool 支持：

- `prompt`
- `subagent_type`
- `description`
- `model`
- `run_in_background`
- `name`
- `team_name`
- `mode`
- `isolation`
- `cwd`

这已经不是“开一个 worker”那么简单，而是完整的多代理启动 DSL。

## 3. AgentTool 先做的是策略判定

关键代码：`src/tools/AgentTool/AgentTool.tsx:254-408`

主要会判断：

- 当前 permission mode
- 当前是否 teammate
- 是否允许 team mode
- in-process teammate 是否禁止 background spawn
- 需要的 MCP servers 是否已连接并可用

### 3.1 required MCP servers 校验很关键

如果 agent 定义声明了 `requiredMcpServers`，AgentTool 会：

- 等待 pending server 一小段时间
- 收集当前“真正有工具”的 MCP servers
- 不满足时直接报错

说明 agent 定义不是纯 prompt 元数据，而会参与运行前可用性判定。

## 4. AgentTool 有三条主要分支

## 4.1 teammate spawn

关键代码：`src/tools/AgentTool/AgentTool.tsx:282-316`

如果：

- 有 `team_name`
- 有 `name`

则会走 `spawnTeammate(...)`，这是多代理团队模式。

## 4.2 本地/普通 subagent

关键代码：`src/tools/AgentTool/AgentTool.tsx:318-637`

这是最常见路径：

- 解析 `subagent_type`
- 决定是否 fork path
- 解析选中的 agent definition
- 准备 system prompt 和 prompt messages
- 组装 worker tool pool
- 可选 worktree isolation
- 构造 `runAgentParams`

## 4.3 远程隔离 agent

关键代码：`src/tools/AgentTool/AgentTool.tsx:433-482`

如果 `effectiveIsolation === 'remote'`，会：

- 校验远程 agent 前置条件
- `teleportToRemote(...)`
- `registerRemoteAgentTask(...)`
- 返回 remote launched 结果

所以“远程 agent”本质上是 AgentTool 的一种隔离模式。

## 5. fork path 为什么特别重要

关键代码：`src/tools/AgentTool/AgentTool.tsx:318-336`, `483-512`, `611-633`

fork path 的设计目标是：

- 子代理继承父代理已经渲染好的 system prompt
- 尽量继承父工具数组
- 追求 prompt cache 前缀完全一致

源码甚至明确注释说：

- 这是为了 cache-identical prefix。

这非常能体现本项目的成本意识。

## 6. worktree 隔离在 AgentTool 里是一等能力

关键代码：`src/tools/AgentTool/AgentTool.tsx:582-685`

如果 `effectiveIsolation === 'worktree'`，AgentTool 会：

- 生成 worktree slug
- 创建 agent worktree
- 在 fork path 下额外注入 worktree notice
- 在 agent 完成后决定删除还是保留 worktree

### 6.1 为什么要注入 worktree notice

因为 fork 子代理会继承父上下文中的文件路径认知，而 worktree 切换后路径语义可能变化。

所以系统显式告诉子代理：

- 现在工作目录不同了
- 某些文件需要重新读取

## 7. async agent 与 foreground agent 的差异

关键代码：`src/tools/AgentTool/AgentTool.tsx:686-740`

`shouldRunAsync` 的判定来源很多：

- `run_in_background`
- agent definition 的 `background: true`
- coordinator mode
- fork subagent experiment
- assistant mode
- proactive mode

这说明后台化不是单一用户选择，而可能是系统策略决定。

## 8. `registerAsyncAgent()`：后台 agent 任务注册

关键代码：`src/tasks/LocalAgentTask/LocalAgentTask.tsx:466-515`

它会做：

- 为 transcript 建输出 symlink
- 创建 abort controller
- 生成 `LocalAgentTaskState`
- 标记 `status: 'running'`
- `isBackgrounded: true`
- 注册 cleanup handler
- 注册到 `AppState.tasks`

也就是说，后台 agent 首先是一个任务对象，然后才是一个执行流。

## 9. foreground agent 也能被后台化

关键代码：`src/tasks/LocalAgentTask/LocalAgentTask.tsx:526-614`

`registerAgentForeground(...)` 会：

- 先创建一个前台 agent task
- 同时暴露 `backgroundSignal`
- 可配置 `autoBackgroundMs`

这意味着 agent 的前台/后台并不是启动时固定死的，前台 agent 也能在运行中转后台。

## 10. `runAgent()`：真正的子代理执行器

关键代码：`src/tools/AgentTool/runAgent.ts:430-860`

这是子代理真正跑起来的地方。

## 10.1 先构造 agent 专属权限与工具视图

关键代码：`src/tools/AgentTool/runAgent.ts:430-503`

这里会：

- 根据 agent permission mode 覆盖 `toolPermissionContext`
- 决定是否 `shouldAvoidPermissionPrompts`
- 如果有 `allowedTools`，只保留 SDK/CLI 层显式权限和 session 允许工具
- 解析 effort override
- 解析最终工具池

说明：

- 子代理不是简单共享父代理全部权限。
- 它有自己独立的权限视图。

## 10.2 再生成 agent system prompt

关键代码：`src/tools/AgentTool/runAgent.ts:508-518`

如果外层传了 override system prompt，就直接用；

否则：

- 根据 agent definition、工具池、model、working directories 重新生成 agent system prompt。

## 10.3 SubagentStart hooks 与 frontmatter hooks

关键代码：`src/tools/AgentTool/runAgent.ts:530-575`

运行前会：

- 执行 `SubagentStart` hooks，追加额外上下文
- 注册 agent frontmatter hooks

这说明子代理也是 hook 生命周期中的一级实体。

## 10.4 预加载技能与 agent-specific MCP

关键代码：

- `src/tools/AgentTool/runAgent.ts:577-645`
- `src/tools/AgentTool/runAgent.ts:648-665`

这里会：

- 预加载 agent frontmatter 指定的 skills
- 初始化 agent 专属 MCP servers
- 合并 agent MCP tools 与 resolved tools

这说明 agent 不是单纯“换个 prompt”，而是能带自己的技能与外部能力环境。

## 10.5 最终还是调用 `query()`

关键代码：`src/tools/AgentTool/runAgent.ts:747-806`

子代理最终也会：

- 调用 `query({ ... })`
- 消费消息流
- 记录 sidechain transcript
- 记录 lastRecordedUuid

这再次证明：

> 主线程与子代理共享同一个 query 内核，只是上下文不同。

## 10.6 cleanup 做得很彻底

关键代码：`src/tools/AgentTool/runAgent.ts:816-859`

结束后会清理：

- agent-specific MCP servers
- session hooks
- prompt cache tracking
- cloned readFileState
- 初始消息数组
- perfetto agent registry
- transcript subdir mapping
- todos entry
- background bash tasks
- monitor MCP tasks

这说明子代理生命周期治理是很严肃的，不是 fire-and-forget。

## 11. 远程会话管理：`RemoteSessionManager`

关键代码：`src/remote/RemoteSessionManager.ts:87-260`

这个类负责：

- WebSocket 订阅远程会话消息
- HTTP POST 发送用户消息
- 远程 permission request/response

## 11.1 它为什么重要

因为远程 agent 或远程 session 并不是另起一套前端协议，而是仍然复用 SDK message / control message 语义。

### 11.1.1 control request 的一个典型用途

远程侧如果需要工具权限，会发：

- `control_request`
- subtype `can_use_tool`

`RemoteSessionManager` 接到后会缓存 pending request，再通知上层 UI。

### 11.1.2 respondToPermissionRequest

本地 UI 处理后，再把：

- allow / deny
- updatedInput

回发给远程会话。

所以远程模式其实是把权限交互也“隧道化”了。

## 12. 多代理体系总图

```mermaid
flowchart TB
    A[主线程 query] --> B[AgentTool]
    B --> C{spawn mode}
    C -- teammate --> D[spawnTeammate]
    C -- local async/sync --> E[runAgent]
    C -- remote --> F[teleportToRemote]

    E --> G[registerAsyncAgent / foreground]
    E --> H[createSubagentContext]
    E --> I["query()"]
    I --> J[sidechain transcript]

    F --> K[registerRemoteAgentTask]
    K --> L[RemoteSessionManager]
    L --> M[WS SDK messages]
    L --> N[permission control flow]
```

## 13. 架构观察

## 13.1 Agent 是“工具化的工作单元”

它之所以强大，是因为它同时复用了：

- Tool 协议
- query 内核
- AppState 任务系统
- transcript 系统
- MCP 系统

## 13.2 背景任务是 agent 生命周期的可视化投影

后台任务并不是另一个执行系统，而是：

- 对 agent lifecycle 的状态化包装

## 13.3 远程会话是同协议延伸

远程会话仍然说的是：

- SDKMessage
- control_request / response

这让本地与远程之间可以共用大量上层逻辑。

## 14. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| AgentTool 定义 | `src/tools/AgentTool/AgentTool.tsx:196-250` | 工具协议层入口 |
| teammate / fork / remote / worktree 分支 | `src/tools/AgentTool/AgentTool.tsx:282-685` | 各类子代理启动路径 |
| async agent 注册 | `src/tools/AgentTool/AgentTool.tsx:686-740` | 后台 agent 任务注册 |
| 本地后台任务注册 | `src/tasks/LocalAgentTask/LocalAgentTask.tsx:466-515` | `LocalAgentTaskState` 生成 |
| 前台转后台 | `src/tasks/LocalAgentTask/LocalAgentTask.tsx:526-614` | foreground/background 切换 |
| runAgent 主体 | `src/tools/AgentTool/runAgent.ts:430-860` | 子代理上下文构造与 query 运行 |
| 远程会话管理 | `src/remote/RemoteSessionManager.ts:87-260` | WS/HTTP/control message 流 |

## 15. 本文结论

多代理体系的核心设计是：

- 用 `AgentTool` 把“启动子代理”纳入主线程工具协议。
- 用 `runAgent()` 复用同一个 query 内核。
- 用 `LocalAgentTask` / `RemoteSessionManager` 把 agent 生命周期投影到 UI 与远程连接层。

因此这套系统并不是“主线程 + 若干脚本 worker”，而是一个可统一调度、可追踪、可恢复的多代理运行时。
