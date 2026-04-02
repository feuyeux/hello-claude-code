# `deep_dive_cx` 阅读导航

这组文档旨在为 Claude Code CLI 源码建立一张可连续追踪的整体地图。

仅从目录树切入，通常会同时遇到以下问题：

- 入口太大，不知道先看哪里。
- REPL、`query()`、工具系统、插件系统彼此交叉，很难一次理清。
- 文档虽然按专题拆开了，但跨篇关系不够显式。

本导航提供：

1. 整体阅读顺序。
2. 每篇文档回答的核心问题。
3. 不同阅读目标下的最短路径。

## 1. 推荐阅读顺序

推荐阅读顺序如下：

1. [01-architecture.md](./01-architecture.md)：先建立分层和主线。
2. [02-startup-flow.md](./02-startup-flow.md)：再理解 CLI 如何启动成一个可运行会话。
3. [11-settings-policy-and-env.md](./11-settings-policy-and-env.md)：补齐 settings、托管策略和 env 注入。
4. [03-repl-and-state.md](./03-repl-and-state.md)：看交互模式下的控制中心。
5. [04-input-command-queue.md](./04-input-command-queue.md)：看输入如何变成一次 turn。
6. [05-query-and-request.md](./05-query-and-request.md)：看请求主循环、流式响应和工具回流。
7. [17-context-management.md](./17-context-management.md)：专门看上下文治理、压缩阶梯和 overflow 恢复。
8. [06-tools-and-permissions.md](./06-tools-and-permissions.md)：看工具系统和权限判定。
9. [12-hooks-lifecycle-and-runtime.md](./12-hooks-lifecycle-and-runtime.md)：补齐 hooks 运行时模型。
10. [07-extension-skills-plugins-mcp.md](./07-extension-skills-plugins-mcp.md)：看扩展如何接入命令和工具总线。
11. [08-agents-tasks-remote.md](./08-agents-tasks-remote.md)：看子代理、后台任务和远程会话。
12. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)：补齐 transcript、resume 与恢复链路。
13. [15-prompt-system.md](./15-prompt-system.md)：把 system prompt、工具 prompt、技能 prompt、子代理 prompt 和二级模型 prompt 串成一张图。
14. [16-memory-system.md](./16-memory-system.md)：把 auto-memory、team memory、KAIROS daily log、SessionMemory、dream consolidation 串成一条持久化主线。
15. [09-performance-cache-context.md](./09-performance-cache-context.md)：看性能、缓存、观测与长会话稳定性。
16. [10-queryengine-sdk.md](./10-queryengine-sdk.md)：再看非交互/SDK 路径如何复用内核。
17. [14-api-provider-retry-errors.md](./14-api-provider-retry-errors.md)：最后补 API provider、retry 与错误治理。

## 2. 各篇一句话索引

| 文档 | 核心问题 | 最适合什么时候读 |
| --- | --- | --- |
| [01-architecture.md](./01-architecture.md) | 这套工程按什么分层，主线怎么走 | 初次进入仓库时 |
| [02-startup-flow.md](./02-startup-flow.md) | 进程如何从入口走到 setup、trust 和 REPL | 想先搞懂启动链路时 |
| [03-repl-and-state.md](./03-repl-and-state.md) | 交互模式的控制中心在哪里，状态怎么流动 | 想读 `REPL.tsx` 前 |
| [04-input-command-queue.md](./04-input-command-queue.md) | 用户输入如何分类、排队、转消息 | 想跟 prompt 提交流程时 |
| [05-query-and-request.md](./05-query-and-request.md) | `query()` 为什么是多轮状态机，不只是 API 包装 | 想读 `query.ts` 时 |
| [17-context-management.md](./17-context-management.md) | `snip`、`microcompact`、`context collapse`、`autocompact` 如何组成上下文治理链路 | 想单独研究上下文压缩与 overflow 恢复时 |
| [06-tools-and-permissions.md](./06-tools-and-permissions.md) | 工具如何装配、校验、执行、回流 | 想搞懂 Agent 工具调用时 |
| [07-extension-skills-plugins-mcp.md](./07-extension-skills-plugins-mcp.md) | 技能、插件、MCP 如何并入主系统 | 想研究扩展机制时 |
| [08-agents-tasks-remote.md](./08-agents-tasks-remote.md) | 子代理和后台/远程任务如何运行 | 想研究多代理与任务系统时 |
| [09-performance-cache-context.md](./09-performance-cache-context.md) | 复杂工程性代码到底在优化什么 | 想理解性能与稳定性取舍时 |
| [10-queryengine-sdk.md](./10-queryengine-sdk.md) | 非交互路径怎样复用 query 内核 | 想看 SDK/headless 模式时 |
| [11-settings-policy-and-env.md](./11-settings-policy-and-env.md) | settings、MDM、policy 与 env 为什么会影响整条启动链 | 想搞懂配置优先级和 trust 前后差异时 |
| [12-hooks-lifecycle-and-runtime.md](./12-hooks-lifecycle-and-runtime.md) | hooks 到底如何被组装、执行和约束 | 想把 hook 当运行时系统来理解时 |
| [13-session-storage-and-resume.md](./13-session-storage-and-resume.md) | transcript 如何持久化，resume 如何真正恢复 live session | 想研究会话恢复与 JSONL 结构时 |
| [14-api-provider-retry-errors.md](./14-api-provider-retry-errors.md) | provider 选择、重试与错误治理如何工作 | 想深挖 `services/api` 时 |
| [15-prompt-system.md](./15-prompt-system.md) | Claude Code 到底有哪些提示词，它们如何被装配、缓存和分发 | 想系统理解 prompt runtime 时 |
| [16-memory-system.md](./16-memory-system.md) | 记忆系统有哪些层，公共流传的“7 层记忆”哪些能被代码证实，KAIROS daily log 为什么是另一条持久化路线 | 想专门研究长期上下文与 memory 治理时 |

## 3. 按目标选读

### 3.1 想快速跑通“交互式一条消息”

推荐路径如下：

1. [02-startup-flow.md](./02-startup-flow.md)
2. [11-settings-policy-and-env.md](./11-settings-policy-and-env.md)
3. [03-repl-and-state.md](./03-repl-and-state.md)
4. [04-input-command-queue.md](./04-input-command-queue.md)
5. [05-query-and-request.md](./05-query-and-request.md)
6. [17-context-management.md](./17-context-management.md)
7. [15-prompt-system.md](./15-prompt-system.md)
8. [16-memory-system.md](./16-memory-system.md)
9. [06-tools-and-permissions.md](./06-tools-and-permissions.md)
10. [12-hooks-lifecycle-and-runtime.md](./12-hooks-lifecycle-and-runtime.md)

### 3.2 想理解“为什么这个项目这么大”

推荐路径如下：

1. [01-architecture.md](./01-architecture.md)
2. [11-settings-policy-and-env.md](./11-settings-policy-and-env.md)
3. [17-context-management.md](./17-context-management.md)
4. [15-prompt-system.md](./15-prompt-system.md)
5. [16-memory-system.md](./16-memory-system.md)
6. [12-hooks-lifecycle-and-runtime.md](./12-hooks-lifecycle-and-runtime.md)
7. [09-performance-cache-context.md](./09-performance-cache-context.md)
8. [07-extension-skills-plugins-mcp.md](./07-extension-skills-plugins-mcp.md)
9. [08-agents-tasks-remote.md](./08-agents-tasks-remote.md)

### 3.3 想研究 SDK / headless / 自动化场景

推荐路径如下：

1. [01-architecture.md](./01-architecture.md)
2. [05-query-and-request.md](./05-query-and-request.md)
3. [17-context-management.md](./17-context-management.md)
4. [15-prompt-system.md](./15-prompt-system.md)
5. [16-memory-system.md](./16-memory-system.md)
6. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)
7. [10-queryengine-sdk.md](./10-queryengine-sdk.md)
8. [14-api-provider-retry-errors.md](./14-api-provider-retry-errors.md)
9. [08-agents-tasks-remote.md](./08-agents-tasks-remote.md)

### 3.4 想研究配置、hooks 与 resume 这些“隐藏复杂度”

推荐路径如下：

1. [11-settings-policy-and-env.md](./11-settings-policy-and-env.md)
2. [17-context-management.md](./17-context-management.md)
3. [15-prompt-system.md](./15-prompt-system.md)
4. [16-memory-system.md](./16-memory-system.md)
5. [12-hooks-lifecycle-and-runtime.md](./12-hooks-lifecycle-and-runtime.md)
6. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)
7. [14-api-provider-retry-errors.md](./14-api-provider-retry-errors.md)

### 3.5 想专门研究“长期记忆、会话续航、KAIROS”

推荐路径如下：

1. [15-prompt-system.md](./15-prompt-system.md)
2. [16-memory-system.md](./16-memory-system.md)
3. [13-session-storage-and-resume.md](./13-session-storage-and-resume.md)
4. [10-queryengine-sdk.md](./10-queryengine-sdk.md)
5. [02-startup-flow.md](./02-startup-flow.md)

## 4. 核心术语表

| 术语 | 在这组文档里的含义 |
| --- | --- |
| `REPL` | 交互式终端 UI 的主控制器，不只是视图层 |
| `query()` | 对话执行状态机，会经历多轮模型请求与工具调用 |
| `ToolUseContext` | 工具执行时携带的运行时上下文 |
| trust | 启动时的安全边界；通过前后可用能力不同 |
| compact / collapse | 上下文治理与压缩的一组机制 |
| MCP | 外部工具/资源协议接入层 |
| `QueryEngine` | 非交互路径下的 headless 会话控制器 |
| policySettings | 企业托管配置层，不等于普通本地 settings |
| session hook | 只存在于当前会话内存中的 hook，常由技能/代理动态注册 |
| transcript | append-only JSONL 会话日志，而不只是聊天文本 |
| provider | first-party / Bedrock / Foundry / Vertex 等真实 API 后端 |

## 5. 阅读建议

- 不必一次性通读整个仓库，可先沿文档主线建立整体地图。
- 读每篇时优先看“定义”“流程图”“关键源码锚点”三块。
- 真正卡住时，再回到对应的大文件做定点阅读，而不是整文件顺着翻。
