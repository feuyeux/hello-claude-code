# 11. Slash Commands 调度系统深度分析

在 `claude-code` 中，Slash Commands（以 `/` 开头的斜杠命令）不仅是快捷操作，更是一套高度抽象、解耦且支持并发运行的指令调度系统。它能够处理从简单的 UI 切换（如 `/theme`）到复杂的后台子代理由 (Sub-agent) 执行的任务（如 `/commit`）。

## 11.1. 核心架构：三层调度模型

Slash Commands 的处理流程遵循“注册 -> 拦截与入队 -> 异步调度执行”的三层模型：

1.  **注册层 (`src/commands.ts`)**: 定义命令的元数据、类型（`local`, `local-jsx`, `prompt`）及加载逻辑。
2.  **调度层 (`src/utils/handlePromptSubmit.ts` & `src/hooks/useQueueProcessor.ts`)**: 处理用户输入。如果当前有正在进行的 Query，则将命令放入 `messageQueueManager`；如果空闲，则触发执行。
3.  **执行层 (`src/utils/processUserInput/processSlashCommand.tsx`)**: 真正解析命令参数，并根据命令类型分发到不同的执行逻辑中。

## 11.2. 命令类型与执行策略

系统根据命令的行为特征将其分为三类，每类都有独特的生命周期：

### 11.2.1. Local JSX Commands (`type: 'local-jsx'`)
这类命令允许渲染复杂的 React/Ink 交互界面，通常用于设置或需要用户确认的操作。
- **代表命令**: `/config`, `/doctor`, `/settings`, `/onboarding`。
- **执行逻辑**:
    - 调用 `setToolJSX` 将 UI 注入到 REPL 视图中。
    - 使用 `onDone` 回调机制。当 UI 交互完成时，调用 `onDone` 返回执行结果，并决定是否需要触发后续的 AI 查询。
    - **立即执行 (Immediate)**: 部分 JSX 命令标记为 `immediate: true`。即使当前正在运行查询（Query），它们也会被立即执行（弹出模态框），而不是进入队列等待。

### 11.2.2. Local Commands (`type: 'local'`)
执行本地逻辑并直接返回文本结果或改变应用状态，不涉及复杂的 UI。
- **代表命令**: `/clear`, `/compact`, `/exit`, `/cost`。
- **状态突变**:
    - **`/clear`**: 重置 `messages` 数组，清空对话历史。
    - **`/compact`**: 触发 `compactionResult`。它会压缩对话上下文，并用生成的摘要替换旧的消息序列，从而重置对话的“窗口边界”。

### 11.2.3. Prompt Commands / Skills (`type: 'prompt'`)
这类命令本质上是动态生成的系统提示词（System Prompt），用于扩展 AI 的能力。
- **代表命令**: `/bug`, `/review`, `/commit`, `/explain`。
- **执行流**: 
    - 解析结果通常是一组被标记为 `isMeta: true` 的消息。
    - 它们会被推入对话历史，并设置 `shouldQuery: true`。
    - 接着触发 `onQuery` 进入 `src/query.ts` 的核心循环。

## 11.3. 分叉执行机制：Forked Agents

`claude-code` 引入了 **Context Forking** 机制，允许某些耗时的 Skill 命令在后台的子代理（Sub-agent）中运行。

- **触发条件**: 命令定义中包含 `context: 'fork'`（例如 `/commit`）。
- **执行过程**:
    1.  **子环境隔离**: 创建一个新的 `agentId` 和隔离的 `ToolUseContext`。
    2.  **后台运行**: 使用 `runAgent` 函数启动一个独立的 Agent 循环。
    3.  **非阻塞**: 主线程立即返回，用户可以继续在 REPL 中输入其他指令。
    4.  **结果回填**: 子代理执行完毕后，会将结果封装成一个特殊的 `<scheduled-task-result>` 标签，重新入队到主消息队列中，待主 Agent 在下一轮对话中感知。

## 11.4. 调度安全与拦截

### 11.4.1. Query Guard
为了防止状态竞争，系统使用 `QueryGuard` 来锁定执行状态。
- 当 `query.ts` 循环运行时，`QueryGuard.isActive` 为 `true`。
- 普通 Slash Commands 会被 `handlePromptSubmit` 拦截并转入 `enqueue`。
- 只有标记为 `immediate` 的 `local-jsx` 命令可以绕过此锁定。

### 11.4.2. 队列处理器 (`useQueueProcessor`)
这是一个 React Hook，它监听 `QueryGuard` 和 `messageQueue`。一旦查询结束且队列中有待处理的 Slash Command，它会自动取出并调用 `executeQueuedInput`，从而实现命令的链式执行或延迟执行。

## 11.5. 命令执行对 Query 循环的影响

Slash Commands 是对话状态的核心干预者：

| 命令行为 | 对 `query.ts` 的影响 | 实现细节 |
| :--- | :--- | :--- |
| **中断 (Interruption)** | 如果用户在工具执行时输入 `/exit` 或其他命令，系统会触发 `abortController.abort()`。 | `handlePromptSubmit` 中检测 `hasInterruptibleToolInProgress`。 |
| **历史篡改 (History Mutation)** | `/clear` 或 `/compact` 直接通过 `setMessages` 修改 React State。 | `processSlashCommand` 返回 `compactionResult` 时调用 `buildPostCompactMessages`。 |
| **链式输入 (Chaining)** | 允许命令执行完后自动在输入框填入下一个命令或直接提交。 | 通过返回 `nextInput` 和 `submitNextInput` 参数实现。 |

## 11.6. 总结

`claude-code` 的 Slash Commands 系统不仅是 CLI 的点缀，它还是整个工具生态的入口。通过 `prompt` 类型支持的 Skills 插件系统，以及 `context: 'fork'` 带来的子代理能力，它将原本线性的对话模式转变为了一个支持多任务、多代理协作的动态系统。
