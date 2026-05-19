# Claude Code 深度分析（CC 视角）

本目录包含对 Claude Code CLI 工具的全面深度分析，共 17 篇文档，系统剖析其架构、流程和核心机制。

## 文档导航

### 基础架构层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [01_architecture_overview.md](./01_architecture_overview.md) | 整体架构设计、分层结构、关键设计判断 | 初次进入仓库时 |
| [02_startup_flow.md](./02_startup_flow.md) | 应用启动的三个窗口、Trust 门控、初始化步骤 | 想搞懂启动链路时 |

### 请求处理层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [03_request_flow.md](./03_request_flow.md) | query() 28 阶段主循环、错误恢复、5 个并行通道 | 想读 query.ts 时 |
| [04_tool_system.md](./04_tool_system.md) | 工具注册、StreamingToolExecutor、批处理策略、权限 | 想搞懂工具调用时 |

### 系统支撑层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [05_bridge_system.md](./05_bridge_system.md) | Bridge 机制、HybridTransport、JWT 刷新、FlushGate | 想研究远程控制时 |
| [06_transport_system.md](./06_transport_system.md) | WebSocket/SSE/Hybrid 传输、退避策略、CCR 客户端 | 想研究网络层时 |
| [07_state_management.md](./07_state_management.md) | AppState、DeepImmutable、Selector 缓存、持久化选择性 | 想研究状态管理时 |

### 高级特性层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [08_mcp_system.md](./08_mcp_system.md) | MCP 协议、6 种传输、XAA 认证、工具转换 | 想研究外部集成时 |
| [09_compact_system.md](./09_compact_system.md) | 多层压缩策略、Microcompact 双路径、缓存检测 | 想研究上下文压缩时 |
| [10_hooks_system.md](./10_hooks_system.md) | 27 种事件、4 种 Hook 类型、退出码语义、Trust 门控 | 想研究扩展机制时 |

### 配置与持久化层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [11_settings_policy_env.md](./11_settings_policy_env.md) | 5 源配置合并、Policy first-source-wins、Trust 边界 | 想搞懂配置系统时 |
| [12_session_storage_resume.md](./12_session_storage_resume.md) | Transcript JSONL、parentUuid 链、会话恢复 7 步 | 想研究会话持久化时 |

### API 与 Provider 层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [13_api_provider_retry.md](./13_api_provider_retry.md) | 4 种 Provider 路由、重试状态机、Fast Mode 降级 | 想深挖 API 层时 |

### Prompt 与记忆层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [14_prompt_system.md](./14_prompt_system.md) | 4 阶段编译、缓存边界、工具/Agent/Slash 命令 Prompt | 想系统理解 prompt 时 |
| [15_memory_system.md](./15_memory_system.md) | 8 层子系统、Durable Memory、KAIROS、SessionMemory | 想研究记忆机制时 |
| [16_context_management.md](./16_context_management.md) | 梯度压缩管线、query.ts 5 阶段、Reactive Compact | 想研究上下文治理时 |

### 代理与任务层

| 文档 | 核心问题 | 最适合什么时候读 |
| :------| :---------| :--------------|
| [17_agents_tasks_remote.md](./17_agents_tasks_remote.md) | AgentTool、Coordinator 模式、4 层隔离、远程会话 | 想研究多代理时 |

## 阅读建议

### 快速上手（30 分钟）

按顺序阅读：`01` → `02` → `03`

### 深入理解（2-3 小时）

结合用例场景：

- **开发工具集成**：`04` → `05` → `08`
- **性能优化**：`09` → `16` → `06`
- **功能扩展**：`10` → `08` → `17`
- **配置与安全**：`11` → `10` → `13`

### 完整掌握（4-6 小时）

推荐顺序：`01` → `02` → `11` → `03` → `16` → `04` → `10` → `08` → `17` → `12` → `14` → `15` → `13` → `09` → `05` → `06` → `07`

### 按目标选读

- **想跑通"一条消息的旅程"**：`02` → `03` → `04` → `16` → `14`
- **想理解"为什么这个项目这么大"**：`01` → `11` → `14` → `15` → `10` → `17`
- **想研究 SDK/headless 场景**：`03` → `16` → `12` → `13`
- **想研究"隐藏复杂度"**：`11` → `16` → `14` → `15` → `12` → `13`
- **想专门研究长期记忆**：`14` → `15` → `12` → `16`

## 核心术语表

| 术语 | 含义 |
| :------| :------|
| `query()` | 对话执行状态机，28 阶段主循环，多轮模型请求与工具调用 |
| `ToolUseContext` | 工具执行时携带的 50+ 字段运行时上下文 |
| `Trust` | 启动时的安全边界；通过前后可用能力不同 |
| `compact / collapse` | 上下文治理与压缩的梯度管线 |
| `MCP` | 外部工具/资源协议接入层，支持 6 种传输 |
| `QueryEngine` | 非交互路径下的 headless 会话控制器 |
| `policySettings` | 企业托管配置层，使用 first-source-wins 而非深合并 |
| `transcript` | append-only JSONL 会话日志，parentUuid 链式结构 |
| `provider` | first-party / Bedrock / Foundry / Vertex 等 API 后端 |
| `StreamingToolExecutor` | 工具与 API 流式并行执行的调度器 |
| `Sticky Latch` | Beta headers 一旦发送就整个会话保持的机制 |

## 技术栈

- **运行时**：Bun >= 1.3.11
- **语言**：TypeScript + TSX（React/Ink 终端 UI）
- **模块系统**：ESM（Monorepo with Bun workspaces）
- **核心框架**：React/Ink（终端 UI）、Commander.js（CLI）、Anthropic SDK
- **代码规模**：~1200+ 源文件，44 个顶层目录

## 相关资源

- **源代码**：`../claude-code/` - 反编译还原的 Claude Code CLI 完整源码
- **Codex 视角**：`../deep_dive_cx/` - 系统级源码阅读导航（17 篇）
- **Gemini 视角**：`../deep_dive_gi/` - 工程架构分析

---

**最后更新**：2026-04-02
