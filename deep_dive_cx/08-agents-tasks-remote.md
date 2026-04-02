# 多代理、后台任务与远程会话

本篇梳理子代理、后台任务与远程会话如何通过 `AgentTool` 接入统一运行时。

## 1. Agent 在这套系统里的真实地位

在源码中，子代理不是一个平行子系统，而是工具系统的一部分。

系统关系如下：

- 主模型通过 `AgentTool` 启动子代理。
- 子代理再运行自己的 `query()`。
- 后台任务、远程任务、worktree 隔离、权限模式都是围绕这一工具调用展开。

主线如下：

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

后台 agent 首先是一个任务对象，然后才是一个执行流。

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

结论如下：

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

子代理也是 hook 生命周期中的一级实体。

## 10.4 预加载技能与 agent-specific MCP

关键代码：

- `src/tools/AgentTool/runAgent.ts:577-645`
- `src/tools/AgentTool/runAgent.ts:648-665`

这里会：

- 预加载 agent frontmatter 指定的 skills
- 初始化 agent 专属 MCP servers
- 合并 agent MCP tools 与 resolved tools

agent 不是单纯“换个 prompt”，而是能带自己的技能与外部能力环境。

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

## 12. `0402.md` 里那批隐藏能力在多代理链路里的真实落点

### 12.1 Coordinator 是独立编排人格，不是普通 worker 开关

关键代码：

- `src/coordinator/coordinatorMode.ts`
- `src/constants/tools.ts`

`isCoordinatorMode()` 的条件很直接：

- build-time 要有 `feature('COORDINATOR_MODE')`
- runtime 要有 `CLAUDE_CODE_COORDINATOR_MODE`

进入 coordinator mode 之后，主线程可见工具会被强约束到：

- `AgentTool`
- `TaskStopTool`
- `SendMessageTool`
- `SyntheticOutputTool`

也就是 `COORDINATOR_MODE_ALLOWED_TOOLS` 这一小组。

同时，`coordinatorMode.ts` 里的 `INTERNAL_WORKER_TOOLS` 又会从 worker 可见工具上下文里剔除：

- `TeamCreate`
- `TeamDelete`
- `SendMessage`
- `SyntheticOutput`

因此 `0402.md` 里“worker 拿不到 TeamCreate 和 SendMessage，防止套娃”这个说法，在 coordinator 语义下基本成立。源码的真实表达不是一句注释，而是：

- coordinator 自己有一套单独 system prompt
- worker 工具表是被 coordinator 运行时二次裁剪过的

### 12.2 “tmux / in-process / remote” 这个说法方向对，但要拆成两层看

关键代码：

- `src/tools/shared/spawnMultiAgent.ts`
- `src/utils/swarm/backends/registry.ts`
- `src/utils/swarm/backends/types.ts`
- `src/tools/AgentTool/AgentTool.tsx`

代码里真正的 teammate backend 类型是：

- `tmux`
- `iterm2`
- `in-process`

`spawnMultiAgent.ts` 和 backend registry 说明：

- 如果会话解析成 `in-process`，worker 直接在当前进程里跑。
- 如果需要 pane backend，则优先走当前终端环境可用的 `tmux` 或 `iTerm2`。
- `auto` 模式会在 pane backend 不可用时回退到 `in-process`。

而 `remote` 不是 teammate pane backend 的第四种枚举，而是 `AgentTool` 的 isolation 模式：

- `src/tools/AgentTool/AgentTool.tsx` 中 `effectiveIsolation === 'remote'`
- 随后走 `teleportToRemote(...)` + `registerRemoteAgentTask(...)`

所以更准确的说法是：

> teammate 执行后端是 `tmux / iTerm2 / in-process`，而 `remote` 是 AgentTool 级别的远程隔离路径。

### 12.3 Teleport 不是边缘命令，而是所有远程能力的公共底座

关键代码：

- `src/utils/teleport.tsx`
- `src/main.tsx`
- `src/tools/AgentTool/AgentTool.tsx`

`teleportToRemote(...)` 这条链同时被多处复用：

- `main.tsx` 的 `--remote` / `--teleport`
- `AgentTool` 的 `remote` isolation
- `/ultraplan`
- `/ultrareview`

它做的事也不只是“恢复一个网页 session”，而是：

- 选择 GitHub clone 还是 bundle 模式
- 创建远程 CCR session
- 注入环境变量与初始消息
- 返回 session URL / session id 给本地任务系统

从架构上看，Teleport 更像：

> Claude Code 所有云端执行能力共享的远程会话原语。

### 12.4 `/ultraplan` 确实是一个云端 30 分钟规划工作流

关键代码：

- `src/commands/ultraplan.tsx`
- `src/tasks/RemoteAgentTask/RemoteAgentTask.tsx`

`ultraplan.tsx` 里有非常直白的常量：

- `ULTRAPLAN_TIMEOUT_MS = 30 * 60 * 1000`

它的主流程是：

1. 通过 `teleportToRemote(...)` 创建远程 session。
2. 把 planning prompt 发到远端。
3. 用 `pollForApprovedExitPlanMode(...)` 轮询远端 plan approval。
4. 根据用户在浏览器里的选择，决定：
   - 继续在远端执行
   - 还是把计划带回本地

`RemoteAgentTaskState` 里还专门为它保留了：

- `isUltraplan`
- `ultraplanPhase`

`/ultraplan` 不是普通 slash command 外包一层 prompt，而是独立的远程任务类型。

### 12.5 `/ultrareview` 是 remote bughunter 路径，和 `/review` 不是一回事

关键代码：

- `src/commands/review.ts`
- `src/commands/review/ultrareviewEnabled.ts`
- `src/commands/review/reviewRemote.ts`

`review.ts` 已经把两者拆得很清楚：

- `/review` 保持本地 review prompt
- `/ultrareview` 是唯一的 remote bughunter 入口

`ultrareviewEnabled.ts` 说明它还受 `tengu_review_bughunter_config` 控制，未开 gate 时命令根本不会出现在命令表里。

`reviewRemote.ts` 进一步证明了 `0402.md` 里的“云端 bug fleet”不是夸张修辞：

- 默认 `BUGHUNTER_FLEET_SIZE = 5`
- 上限 `20`
- 默认最长运行 `10` 分钟
- 上限 `25` 分钟
- 结果通过 `registerRemoteAgentTask({ remoteTaskType: 'ultrareview' })` 回流本地会话

因此 `/ultrareview` 的真实代码形态不是“增强版 review prompt”，而是：

> 远程 session + bughunter 环境变量 + 轮询回流任务通知 的组合工作流。

## 13. 多代理体系总图

```mermaid
---
config:
  theme: neutral
---
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

## 14. 架构观察

## 14.1 Agent 是“工具化的工作单元”

它之所以强大，是因为它同时复用了：

- Tool 协议
- query 内核
- AppState 任务系统
- transcript 系统
- MCP 系统

## 14.2 背景任务是 agent 生命周期的可视化投影

后台任务并不是另一个执行系统，而是：

- 对 agent lifecycle 的状态化包装

## 14.3 远程会话是同协议延伸

远程会话仍然说的是：

- SDKMessage
- control_request / response

这让本地与远程之间可以共用大量上层逻辑。

## 15. `Cross-Agent Communication` 的源码归类

在一些概览图中，`Cross-Agent Communication` 会被放在所谓“第七层记忆”的末端。按源码口径，它更准确的归类不是 memory，而是：

> **协作 / 通信平面**

### 15.1 实际上有三条不同通道

1. **coordinator -> worker 的任务通知通道**  
   `LocalAgentTask.tsx` 会把完成/失败结果包装成 `<task-notification>`，再以 `task-notification` queued command 形式回灌；`query.ts` 只会把属于当前 agent 的通知 drain 给对应 worker。

2. **显式 agent / teammate 消息通道**  
   `SendMessageTool` 通过 `agentNameRegistry`、mailbox、`queuePendingMessage()` 把消息路由到指定 teammate 或本地 agent；接收侧再通过 `drainPendingMessages()` / attachment 注入取到消息。

3. **跨 session 的 peer 通道**  
   `SendMessageTool/prompt.ts` 还支持 `uds:` 和 `bridge:` 地址，消息会包成 `<cross-session-message from="...">`，这已经超出了单个 multi-agent team 的范围。

### 15.2 “共享 cache 前缀”不等于“共享状态”

外部图里还有一句很重要的话：“状态隔离，但共享 cache 前缀”。这在源码里基本成立，但要拆开理解：

- fork path 会继承父线程的 system prompt 和 exact tools，目标是 `cache-identical prefix`
- 但每个 agent 仍然有自己的：
  - message array
  - transcript/sidechain
  - permission context
  - task lifecycle

真正的共享必须走显式通道，例如：

- `SendMessage`
- `<task-notification>`
- coordinator scratchpad（开启时）
- team context / remote bridge

因此，`Cross-Agent Communication` 更适合被理解为多代理 runtime 的总线，而不是 recall / memory layer。将其并入 memory stack，会把协作机制与持久化机制混成一类。

## 16. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| AgentTool 定义 | `src/tools/AgentTool/AgentTool.tsx:196-250` | 工具协议层入口 |
| teammate / fork / remote / worktree 分支 | `src/tools/AgentTool/AgentTool.tsx:282-685` | 各类子代理启动路径 |
| async agent 注册 | `src/tools/AgentTool/AgentTool.tsx:686-740` | 后台 agent 任务注册 |
| 本地后台任务注册 | `src/tasks/LocalAgentTask/LocalAgentTask.tsx:466-515` | `LocalAgentTaskState` 生成 |
| 前台转后台 | `src/tasks/LocalAgentTask/LocalAgentTask.tsx:526-614` | foreground/background 切换 |
| runAgent 主体 | `src/tools/AgentTool/runAgent.ts:430-860` | 子代理上下文构造与 query 运行 |
| 远程会话管理 | `src/remote/RemoteSessionManager.ts:87-260` | WS/HTTP/control message 流 |
| coordinator mode | `src/coordinator/coordinatorMode.ts` | coordinator prompt 与 worker 工具围栏 |
| teammate backend 选择 | `src/utils/swarm/backends/registry.ts:335-430` | `auto / tmux / in-process` 的真实解析点 |
| remote teleport 原语 | `src/utils/teleport.tsx:737-1189` | 远程 session 创建、bundle / git source 选择 |
| `/ultraplan` | `src/commands/ultraplan.tsx:1-240` | 30 分钟远程 planning 与 phase 轮询 |
| `/ultrareview` | `src/commands/review.ts`, `src/commands/review/reviewRemote.ts` | 本地 review 与远程 bughunter 的分叉 |

## 17. 总结

多代理体系的核心设计是：

- 用 `AgentTool` 把“启动子代理”纳入主线程工具协议。
- 用 `runAgent()` 复用同一个 query 内核。
- 用 `LocalAgentTask` / `RemoteSessionManager` 把 agent 生命周期投影到 UI 与远程连接层。

因此这套系统并不是“主线程 + 若干脚本 worker”，而是一个可统一调度、可追踪、可恢复的多代理运行时。
