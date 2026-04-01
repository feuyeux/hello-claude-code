# 04. 工具系统深度分析

工具系统（Tool System）是 `claude-code` 的核心能力所在，它将模型（Claude）的逻辑推理能力转化为对文件系统、外壳（Shell）以及外部服务的具体操作。

## 4.1. 工具接口协议 (`src/Tool.ts`)

所有的工具都必须实现 `Tool` 接口，这是一种声明式的设计模式，将执行逻辑、输入验证、权限控制和 UI 渲染高度解耦。

### 4.1.1. 核心属性与方法

-   **`name`**: 工具的唯一标识，模型通过此名称调用工具。
-   **`inputSchema`**: 使用 `zod` 定义的参数模式。这不仅用于运行时验证，还会被转换为 JSON Schema 提供给模型，确保模型生成的参数符合预期。
-   **`call()`**: 工具的执行主体。接收参数、上下文（`ToolUseContext`）以及进度回调（`onProgress`）。
-   **`checkPermissions()`**: 工具特定的权限检查逻辑。在 `call` 之前被调用。
-   **`validateInput()`**: 在权限检查之前的参数语义验证，例如检查文件是否存在。
-   **`isReadOnly / isDestructive / isConcurrencySafe`**: 描述工具属性的元数据。
    -   `isReadOnly`: 如果为 `true`，系统可能在只读模式下跳过权限询问。
    -   `isDestructive`: 破坏性操作（如删除）通常需要更严格的确认。
    -   `isConcurrencySafe`: 决定该工具是否可以并行执行。

### 4.1.2. UI 渲染逻辑 (React/Ink)

`claude-code` 的一个独特设计是将 CLI 的渲染逻辑也包含在工具定义中：
-   `renderToolUseMessage`: 渲染工具调用的初始状态。
-   `renderToolUseProgressMessage`: 渲染执行过程中的流式反馈（如 Bash 输出）。
-   `renderToolResultMessage`: 渲染执行结果（如 Diff 预览或成功提示）。

## 4.2. 工具注册与组装 (`src/tools.ts`)

系统并不是简单地加载所有工具，而是根据环境和配置动态组装工具池（Tool Pool）。

-   **`getAllBaseTools()`**: 定义了内置工具的详尽列表，包括 `BashTool`、`FileEditTool`、`AgentTool` 等。
-   **`assembleToolPool()`**: 这是获取可用工具的“真相源”。它会将内置工具与通过 MCP (Model Context Protocol) 发现的外部工具进行合并，并根据权限规则（`denyRules`）进行过滤。
-   **功能开关 (Feature Flags)**: 许多高级工具（如 `WorkflowTool`、`MonitorTool`）受环境变量（如 `CLAUDE_CODE_PROACTIVE`）控制。

## 4.3. 核心工具深度解析

### 4.3.1. BashTool (Shell 执行)
`BashTool` 远比简单的 `exec` 复杂，它包含了一套精密的执行模式：
-   **语义分析**: 通过 `isSearchOrReadBashCommand` 分析命令意图。如果是搜索（`grep`）或读取（`cat`），UI 会自动折叠结果以保持界面整洁。
-   **自动后台化 (Auto-backgrounding)**: 对于耗时较长的命令（如 `npm install`），`BashTool` 会自动将其转入后台执行，并向模型返回任务 ID，让对话保持响应。
-   **沙箱机制 (Sandboxing)**: 支持在隔离环境中运行命令，防止对主机系统造成意外损害。
-   **模拟 Sed 编辑**: 专门处理 `sed -i` 命令，在应用前提供预览，并确保写入结果与预览完全一致。

### 4.3.2. FileEditTool (精密文件编辑)
为了确保在大规模代码库上编辑的安全性和准确性，`FileEditTool` 实现了以下特性：
-   **智能匹配 (`findActualString`)**: 自动处理引号、缩进和换行符的细微差异，确保 `old_string` 能准确匹配到源代码。
-   **陈旧性检查 (Staleness Check)**: 在写入前检查文件自上次读取以来是否被外部修改（如 Linter 或手动编辑）。如果文件已更改，则拒绝写入并要求模型重新读取。
-   **原子操作**: 采用“读取-修改-写入”的原子序列，并集成 LSP (Language Server Protocol) 通知，实时触发语法检查。
-   **编辑回滚**: 与 `fileHistory` 系统集成，支持对任何文件编辑进行撤销。

### 4.3.3. AgentTool (任务委托)
`AgentTool` 实现了代理的层级化：
-   **子代理创建**: 启动一个新的 `QueryEngine` 实例。
-   **上下文隔离**: 子代理拥有独立的任务目标和消息历史，但可以共享父代理的部分工具。
-   **并行执行**: 允许主代理在等待子代理完成复杂任务（如编写测试或重构）的同时处理其他逻辑。

## 4.4. 扩展机制：MCP 系统 (`src/services/mcp/`)

MCP 是 `claude-code` 能够无限扩展的关键。它允许通过网络或本地进程接入外部工具集。

-   **多传输层支持**: 支持 `stdio`（本地进程）、`sse`（服务器发送事件）、`http` 以及 `ws`（WebSocket）。
-   **动态转换**: 系统会自动将 MCP 服务器提供的工具描述转换为内部的 `Tool` 实例，包括参数 Schema 的映射和权限声明。
-   **会话管理**: 具备自动重连机制，能够处理 MCP 服务器的崩溃或连接超时。
-   **内置 MCP 服务器**: 为了性能，一些核心功能（如 Chrome 自动化和 Computer Use）以进程内（In-process）MCP 服务器的形式实现。

## 4.5. 执行模式与流式处理

1.  **参数校验**: AI 生成参数 -> `zod` 验证 -> `validateInput` 语义检查。
2.  **权限控制**: 根据 `checkPermissions` 的结果决定是否直接运行、询问用户或拒绝。
3.  **流式反馈**: `BashTool` 等工具通过 `AsyncGenerator` 实现。执行过程中的每一行输出都会通过 `onProgress` 实时推送到终端 UI。
4.  **结果持久化**: 如果工具输出过大（超过 `maxResultSizeChars`），系统会将结果保存到磁盘上的 `tool-results` 目录，并向模型返回一个文件路径预览，从而节省 Token 消耗并防止上下文溢出。

## 4.6. 总结

`claude-code` 的工具系统不仅仅是一个 API 集合，它是一套高度工业化的操作框架。通过精密的状态管理、严格的权限 gating 以及深度优化的终端交互逻辑，它确保了 AI 既能拥有强大的行动力，又能在可控、安全的边界内运行。
