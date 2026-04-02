# `deep_dive` 阅读导航

这组文档为 Claude Code CLI 建立一张可以连续追踪的整体地图。

它不是按“谁写的”或“从哪个目录搬来”组织，而是按运行时真实结构拆分主题：启动、状态、输入、请求、上下文治理、工具、扩展、MCP、配置、持久化、提示词、记忆、网络传输、桥接与多代理。

如果只从目录树或单个大文件切入，通常会同时遇到以下问题：

- 入口太大，不知道先看哪里。
- `REPL`、`query()`、工具系统、配置系统、prompt runtime 和 memory 彼此交叉，很难一次理清。
- 远程桥接、MCP、hooks、session resume 这些能力横跨多层，不适合只按目录读。

本导航提供：

1. 一条完整阅读顺序。
2. 每篇文档回答的核心问题。
3. 不同阅读目标下的最短路径。

## 1. 推荐阅读顺序

推荐阅读顺序如下：

1. [01-architecture.md](./01-architecture.md)：先建立全局分层与主执行链。
2. [02-startup-flow.md](./02-startup-flow.md)：理解进程如何启动成一个可运行会话。
3. [12-settings-policy-and-env.md](./12-settings-policy-and-env.md)：补齐 settings、policy、trust 与 env 注入边界。
4. [03-repl-and-state.md](./03-repl-and-state.md)：理解交互模式下的主控制中心。
5. [04-state-management.md](./04-state-management.md)：单独看 store、selector 与状态更新模式。
6. [05-input-command-queue.md](./05-input-command-queue.md)：看输入如何变成一次 turn。
7. [06-query-and-request.md](./06-query-and-request.md)：看 `query()` 主循环、流式响应和工具回流。
8. [07-context-management.md](./07-context-management.md)：专门看上下文治理、压缩阶梯与 overflow 恢复。
9. [08-tools-and-permissions.md](./08-tools-and-permissions.md)：看工具系统、权限判定与执行编排。
10. [11-hooks-lifecycle-and-runtime.md](./11-hooks-lifecycle-and-runtime.md)：补齐 hook 的运行时模型。
11. [09-extension-skills-plugins-mcp.md](./09-extension-skills-plugins-mcp.md)：看技能、插件和扩展总线如何接入主系统。
12. [10-mcp-system.md](./10-mcp-system.md)：再深入看 MCP client、transport、tool/resource/prompt 协议层。
13. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)：补齐 transcript、resume 与恢复链路。
14. [14-prompt-system.md](./14-prompt-system.md)：把 system prompt、工具 prompt、技能 prompt、子代理 prompt 和二级模型 prompt 串成一张图。
15. [15-memory-system.md](./15-memory-system.md)：把 durable memory、team memory、KAIROS、SessionMemory 与 consolidation 串成一条持久化主线。
16. [16-performance-cache-context.md](./16-performance-cache-context.md)：看性能、缓存、观测与长会话稳定性。
17. [17-queryengine-sdk.md](./17-queryengine-sdk.md)：再看非交互 / SDK 路径如何复用内核。
18. [18-api-provider-retry-errors.md](./18-api-provider-retry-errors.md)：补齐 provider 路由、重试与错误治理。
19. [19-transport-system.md](./19-transport-system.md)：看 WebSocket、SSE、HybridTransport 与批量上传器。
20. [20-bridge-system.md](./20-bridge-system.md)：看远程桥接、JWT 刷新、会话同步与远程控制链路。
21. [21-agents-tasks-remote.md](./21-agents-tasks-remote.md)：最后看多代理、后台任务与远程会话协作。

## 2. 各篇一句话索引

| 文档 | 核心问题 | 最适合什么时候读 |
| --- | --- | --- |
| [01-architecture.md](./01-architecture.md) | 这套工程按什么分层，主线怎么走 | 初次进入仓库时 |
| [02-startup-flow.md](./02-startup-flow.md) | 进程如何从入口走到 setup、trust 和 REPL | 想先搞懂启动链路时 |
| [03-repl-and-state.md](./03-repl-and-state.md) | 交互模式的控制中心在哪里，状态怎么流动 | 想读 `REPL.tsx` 前 |
| [04-state-management.md](./04-state-management.md) | `AppState`、store、selector 和状态更新模式如何共同工作 | 想单独研究状态系统时 |
| [05-input-command-queue.md](./05-input-command-queue.md) | 用户输入如何分类、排队、转消息 | 想跟 prompt 提交流程时 |
| [06-query-and-request.md](./06-query-and-request.md) | `query()` 为什么是多轮状态机，而不只是 API 包装 | 想读 `query.ts` 时 |
| [07-context-management.md](./07-context-management.md) | `snip`、`microcompact`、`context collapse`、`autocompact` 如何组成上下文治理链路 | 想单独研究上下文压缩与 overflow 恢复时 |
| [08-tools-and-permissions.md](./08-tools-and-permissions.md) | 工具如何装配、校验、执行、回流 | 想搞懂 Agent 工具调用时 |
| [09-extension-skills-plugins-mcp.md](./09-extension-skills-plugins-mcp.md) | 技能、插件、命令扩展与 MCP 接入如何共享统一总线 | 想研究扩展机制时 |
| [10-mcp-system.md](./10-mcp-system.md) | MCP client、transport、resource、prompt 与权限模型如何落地 | 想深入研究外部协议接入时 |
| [11-hooks-lifecycle-and-runtime.md](./11-hooks-lifecycle-and-runtime.md) | hooks 到底如何被组装、执行、约束与隔离 | 想把 hook 当运行时系统来理解时 |
| [12-settings-policy-and-env.md](./12-settings-policy-and-env.md) | settings、policy、MDM 与 env 为什么会影响整条启动链 | 想搞懂配置优先级和 trust 前后差异时 |
| [13-session-storage-and-resume.md](./13-session-storage-and-resume.md) | transcript 如何持久化，resume 如何真正恢复 live session | 想研究会话恢复与 JSONL 结构时 |
| [14-prompt-system.md](./14-prompt-system.md) | Claude Code 到底有哪些提示词，它们如何被装配、缓存和分发 | 想系统理解 prompt runtime 时 |
| [15-memory-system.md](./15-memory-system.md) | 记忆系统有哪些层，哪些长期写入路径能被代码证实 | 想研究长期上下文与 memory 治理时 |
| [16-performance-cache-context.md](./16-performance-cache-context.md) | 复杂工程性代码到底在优化什么，prompt cache 与长会话稳定性如何被维护 | 想理解性能与稳定性取舍时 |
| [17-queryengine-sdk.md](./17-queryengine-sdk.md) | 非交互路径怎样复用 query 内核 | 想看 SDK / headless 模式时 |
| [18-api-provider-retry-errors.md](./18-api-provider-retry-errors.md) | provider 选择、请求构造、重试与错误治理如何工作 | 想深挖 `services/api` 时 |
| [19-transport-system.md](./19-transport-system.md) | WebSocket、SSE、HybridTransport 与事件上传器如何构成通信层 | 想研究网络层时 |
| [20-bridge-system.md](./20-bridge-system.md) | 远程桥接、JWT 刷新、历史同步与桥接状态如何工作 | 想研究远程控制与桥接链路时 |
| [21-agents-tasks-remote.md](./21-agents-tasks-remote.md) | 子代理、后台任务和远程会话如何协作 | 想研究多代理与任务系统时 |

## 3. 按目标选读

### 3.1 想快速跑通“交互式一条消息”

推荐路径如下：

1. [02-startup-flow.md](./02-startup-flow.md)
2. [12-settings-policy-and-env.md](./12-settings-policy-and-env.md)
3. [03-repl-and-state.md](./03-repl-and-state.md)
4. [04-state-management.md](./04-state-management.md)
5. [05-input-command-queue.md](./05-input-command-queue.md)
6. [06-query-and-request.md](./06-query-and-request.md)
7. [07-context-management.md](./07-context-management.md)
8. [08-tools-and-permissions.md](./08-tools-and-permissions.md)
9. [14-prompt-system.md](./14-prompt-system.md)
10. [11-hooks-lifecycle-and-runtime.md](./11-hooks-lifecycle-and-runtime.md)

### 3.2 想理解“为什么这个项目这么大”

推荐路径如下：

1. [01-architecture.md](./01-architecture.md)
2. [12-settings-policy-and-env.md](./12-settings-policy-and-env.md)
3. [04-state-management.md](./04-state-management.md)
4. [07-context-management.md](./07-context-management.md)
5. [14-prompt-system.md](./14-prompt-system.md)
6. [15-memory-system.md](./15-memory-system.md)
7. [16-performance-cache-context.md](./16-performance-cache-context.md)
8. [10-mcp-system.md](./10-mcp-system.md)
9. [20-bridge-system.md](./20-bridge-system.md)
10. [21-agents-tasks-remote.md](./21-agents-tasks-remote.md)

### 3.3 想研究扩展、外部协议与自动化场景

推荐路径如下：

1. [08-tools-and-permissions.md](./08-tools-and-permissions.md)
2. [09-extension-skills-plugins-mcp.md](./09-extension-skills-plugins-mcp.md)
3. [10-mcp-system.md](./10-mcp-system.md)
4. [17-queryengine-sdk.md](./17-queryengine-sdk.md)
5. [18-api-provider-retry-errors.md](./18-api-provider-retry-errors.md)
6. [19-transport-system.md](./19-transport-system.md)
7. [20-bridge-system.md](./20-bridge-system.md)
8. [21-agents-tasks-remote.md](./21-agents-tasks-remote.md)

### 3.4 想研究配置、hooks 与 resume 这些“隐藏复杂度”

推荐路径如下：

1. [12-settings-policy-and-env.md](./12-settings-policy-and-env.md)
2. [11-hooks-lifecycle-and-runtime.md](./11-hooks-lifecycle-and-runtime.md)
3. [07-context-management.md](./07-context-management.md)
4. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)
5. [14-prompt-system.md](./14-prompt-system.md)
6. [18-api-provider-retry-errors.md](./18-api-provider-retry-errors.md)

### 3.5 想专门研究“长会话续航、上下文治理与长期记忆”

推荐路径如下：

1. [07-context-management.md](./07-context-management.md)
2. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)
3. [14-prompt-system.md](./14-prompt-system.md)
4. [15-memory-system.md](./15-memory-system.md)
5. [16-performance-cache-context.md](./16-performance-cache-context.md)
6. [17-queryengine-sdk.md](./17-queryengine-sdk.md)

## 4. 核心术语表

| 术语 | 在这组文档里的含义 |
| --- | --- |
| `REPL` | 交互式终端 UI 的主控制器，不只是视图层 |
| `AppState` | 全局运行时状态模型，覆盖 UI、任务、MCP、桥接、权限与主题等状态 |
| `query()` | 对话执行状态机，会经历多轮模型请求与工具调用 |
| `ToolUseContext` | 工具执行时携带的运行时上下文 |
| trust | 启动时的安全边界；通过前后可用能力不同 |
| compact / collapse | 上下文治理与压缩的一组机制 |
| MCP | 外部工具、资源与提示协议接入层 |
| `QueryEngine` | 非交互路径下的 headless 会话控制器 |
| policySettings | 企业托管配置层，不等于普通本地 settings |
| session hook | 只存在于当前会话内存中的 hook，常由技能或代理动态注册 |
| transcript | append-only JSONL 会话日志，而不只是聊天文本 |
| provider | first-party / Bedrock / Foundry / Vertex 等真实 API 后端 |
| bridge | 让本地 CLI 与远程会话、移动端或 Web 客户端协作的桥接层 |
| transport | WebSocket、SSE、HybridTransport 等底层通信抽象 |

## 5. 阅读建议

- 不必一次性通读整个仓库，可先沿文档主线建立整体地图。
- 读每篇时优先看“定义”“流程图”“关键源码锚点”三块。
- 真正卡住时，再回到对应的大文件做定点阅读，而不是整文件顺着翻。
- 如果某个主题既有“高层系统文档”又有“协议/运行时深挖文档”，先读前者，再读后者。
