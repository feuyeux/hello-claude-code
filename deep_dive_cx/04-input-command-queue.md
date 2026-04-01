# 用户输入、Slash 命令与队列分发

本文分析用户提交输入后，系统如何完成输入分类、队列调度和 slash command 分流。

## 1. 这一层解决什么问题

对于用户来说，看到的是“输入一行文本然后 Claude 开始回答”。但在源码里，输入层至少要解决下面几类问题：

1. 这次输入是普通 prompt、bash 还是 slash command。
2. 当前 query 正在运行时，新输入是直接执行、排队、还是尝试中断。
3. 如果输入中带图片、附件、粘贴内容，要怎么转成消息。
4. 如果是 `/command`，这个命令是本地执行还是继续进入模型。
5. 如果命令声明了 `allowedTools / model / effort`，这些限制如何影响当前 turn。

这套职责主要落在：

- `src/utils/handlePromptSubmit.ts`
- `src/utils/processUserInput/processUserInput.ts`
- `src/utils/processUserInput/processSlashCommand.tsx`
- `src/utils/messageQueueManager.ts`
- `src/utils/QueryGuard.ts`
- `src/utils/queueProcessor.ts`

## 2. 整体流程图

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A[REPL.onSubmit] --> B[handlePromptSubmit]
    B --> C{当前是否已有活跃 query?}
    C -- 是 --> D[入队 / 尝试打断 / 排队提示]
    C -- 否 --> E[executeUserInput]
    E --> F[processUserInput]
    F --> G{mode}
    G -- prompt --> H[processTextPrompt]
    G -- bash --> I[processBashCommand]
    G -- slash --> J[processSlashCommand]
    J --> K{shouldQuery}
    H --> L[返回 messages]
    I --> L
    J --> L
    L --> M{有新消息且 shouldQuery}
    M -- 是 --> N["onQuery(...)"]
    M -- 否 --> O[只更新本地 UI / 消息]
```

## 3. `handlePromptSubmit`：输入总入口

关键文件：`src/utils/handlePromptSubmit.ts`

这是真正的“输入门面函数”。REPL 在 `onSubmit` 与 `executeQueuedInput` 两个路径里都会调用它。

### 3.1 它接收的上下文非常大

从 REPL 调用点可以看出，它会收到：

- `queryGuard`
- `isExternalLoading`
- `mode`
- `commands`
- `messages`
- `mainLoopModel`
- `pastedContents`
- `setAbortController`
- `onQuery`
- `setAppState`
- `canUseTool`
- `setMessages`
- `hasInterruptibleToolInProgress`

这表明它不是一个“字符串解析器”，而是：

> 输入调度器

### 3.2 它处理的第一个问题：当前系统忙不忙

如果当前已有 query 在运行，那么新输入不一定能立刻执行。此时它会根据输入类型和当前工具状态做几种策略：

- 排进统一命令队列。
- 如果正在运行的工具可中断，尝试打断当前 turn。
- 把 prompt/bash/slash 统一包装成 `QueuedCommand`。

## 4. 队列系统：为什么要在输入层就建模

关键文件：

- `src/utils/messageQueueManager.ts`
- `src/utils/queueProcessor.ts`
- `src/hooks/useQueueProcessor.ts`

### 4.1 队列里放的不是“文本”，而是命令对象

它至少要区分：

- `prompt`
- `bash`
- `task-notification`
- slash command 对应的 prompt 结果

并且有优先级概念：

- `now`
- `next`
- `later`

### 4.2 `processQueueIfReady` 的职责

`queueProcessor.ts` 会在：

- queue 非空
- queryGuard 不活跃
- 当前没有本地 JSX UI 阻塞

时启动下一批命令。

源码说明了它的批处理策略：

- slash/bash 一般逐个执行。
- 普通 prompt 可以按 mode 批量拼一批提交。

这意味着队列不只是“先进先出”，而是带有模式级别的调度优化。

## 5. `QueryGuard`：防并发 query 的同步闸门

关键文件：`src/utils/QueryGuard.ts`

它的状态机很轻，但作用极大：

- `idle`
- `dispatching`
- `running`

它提供的方法一般有：

- `reserve()`
- `cancelReservation()`
- `tryStart()`
- `end()`
- `forceEnd()`

### 5.1 为什么需要这个对象

因为输入处理里存在很多异步间隙：

- 解析 slash command
- 处理图片/附件
- hook 执行
- queue 出队

如果没有一个同步 guard，很容易出现：

- 两个 prompt 争抢同一轮 query 启动权。
- UI 以为还没开始，另一个异步路径已经启动了 query。

## 6. `executeUserInput`：真正进入处理前的那一步

`handlePromptSubmit` 在决定“现在可以处理这次输入”之后，会进入 `executeUserInput()` 路径。

它典型会做这些事：

1. 创建新的 `AbortController`。
2. 向 `QueryGuard` 申请 reservation。
3. 遍历 queued commands，逐个或分批交给 `processUserInput(...)`。
4. 记录 file history snapshot。
5. 如果得到新的 messages 且 `shouldQuery=true`，调用 `onQuery(...)`。
6. 否则只做本地状态收尾。

### 6.1 这里已经体现出一条重要事实

“一次提交”不一定只对应一个输入。

因为队列里可能已经有多条同类命令被合并执行。

## 7. `processUserInput`：输入语义转换层

关键文件：`src/utils/processUserInput/processUserInput.ts`

它是从“原始输入”进入“消息级语义”的核心层。

## 7.1 先做通用包装，再委托基础处理

`processUserInput(...)` 的结构大致是：

1. 对 prompt 模式设置临时 processing 文案。
2. 调用 `processUserInputBase(...)`。
3. 如果结果 `shouldQuery=true`，再执行 `UserPromptSubmit` hooks。
4. hooks 可以：
   - 追加消息
   - 阻止继续
   - 注入额外上下文

这说明 hooks 并不是 query 之后才介入，而是在“用户输入已被接受、尚未送模型”这个阶段就能工作。

## 8. `processUserInputBase`：真正的模式分发器

它主要做几件事：

### 8.1 内容归一化

- 把纯文本与 content blocks 归一化。
- 处理 pasted images。
- 调整图片块尺寸与存储。

### 8.2 特殊输入短路

例如：

- bridge 安全覆盖
- `ULTRAPLAN` 关键字改写到 `/ultraplan`

### 8.3 附件注入

- 通过 `getAttachmentMessages(...)` 把图片、文件、粘贴内容变成附加消息。

### 8.4 模式分发

- bash 模式走 `processBashCommand`
- slash 输入走 `processSlashCommand`
- 其余走 `processTextPrompt`

所以这层才是真正的：

> 文本输入 -> 会话消息

## 9. `processSlashCommand`：slash 命令并不是简单字符串匹配

关键代码：`src/utils/processUserInput/processSlashCommand.tsx:309-520`

这是理解命令系统的关键。

## 9.1 先 parse，再判断是不是“真命令”

处理流程大致是：

1. `parseSlashCommand(inputString)`
2. 拿到：
   - `commandName`
   - `args`
   - `isMcp`
3. 先判断这个 command 是否存在于 `context.options.commands`

### 9.1.1 如果不存在怎么办

这里不会立刻简单报错，而是先判断：

- 它看起来是否像命令名
- 它会不会其实是文件路径

如果不像真实命令，就把它退化成普通 prompt 继续处理。

这是一种非常实用的 UX 设计：避免把像 `/var/log` 这样的输入误伤成无效命令。

## 9.2 slash command 的返回值远不只是 messages

通过 `getMessagesForSlashCommand(...)`，一个命令可以返回：

- `messages`
- `shouldQuery`
- `allowedTools`
- `model`
- `effort`
- `resultText`
- `nextInput`
- `submitNextInput`

这组返回值非常重要，因为它意味着 slash command 可以改变：

- 当前 turn 是否进入模型
- 当前 turn 能用哪些工具
- 当前 turn 使用哪个模型
- 当前 turn 的 effort 等级

slash command 是前置控制层，而不是单纯的文本宏。

## 10. slash command 的三种典型结果

## 10.1 本地命令，直接结束

如果 `newMessages.length === 0`，说明这类命令在本地 UI 或本地逻辑中已经完成，不需要进 query。

例如某些设置命令、切换命令、只更新本地状态的命令。

## 10.2 命令产出消息，但不 query

比如：

- 生成一条本地输出
- 返回错误消息
- 只展示帮助文本

## 10.3 命令转换成 prompt，再进入 query

这就是很多技能命令的本质：

- `/commit`
- `/review`
- 插件技能
- 自定义 prompt skill

它们会把技能 Markdown、参数替换、allowed tools 等结果转成消息，再继续进入模型。

## 11. 技能型 slash 命令为什么这么强

因为命令系统没有把“技能”实现成另一套协议，而是直接让它走 slash command 入口。

这样技能就天然拥有：

- 参数替换
- allowed tools 控制
- model/effort 覆写
- 本地 shell 注入
- 插件/技能来源追踪

因此 slash command 是整个扩展体系进入主链路的统一入口。

## 12. 普通 prompt 路径并不简单

普通 prompt 也会经历：

- content blocks 组装
- attachment 注入
- image metadata 用户消息插入
- hooks 前置处理

所以即便用户只是输入一句自然语言，最终进入 query 的也不只是“一条字符串消息”。

## 13. 输入忙碌时的策略：排队而不是乱插

这套系统大量使用队列和 guard 的根本原因是：

- query 不是单请求，而是多轮工具循环。
- 中途还可能有可中断工具。
- 还可能有后台任务通知、incoming prompt、mailbox bridge 消息进来。

如果没有统一排队策略，会出现：

- 主线程 query 被多路输入打穿。
- 工具结果与新 prompt 交错，造成消息链断裂。

## 14. 输入层与 REPL 的边界

可以这么理解：

- `REPL.tsx` 负责把当前会话环境传给输入系统。
- `handlePromptSubmit` 负责调度。
- `processUserInput*` 负责语义转换。
- queue/guard 负责并发控制。
- `onQuery` 才是真正把结果送入 query 主循环。

## 15. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| REPL 提交入口 | `src/screens/REPL.tsx:3488-3519` | 交互模式进入 `handlePromptSubmit` |
| 队列执行入口 | `src/screens/REPL.tsx:3861-3889` | 队列中命令如何重用同一输入管线 |
| slash 解析与分流 | `src/utils/processUserInput/processSlashCommand.tsx:309-520` | slash 命令是否存在、是否 query、allowedTools/model/effort |
| QueryGuard | `src/utils/QueryGuard.ts` | 防止 query 重入 |
| queue manager | `src/utils/messageQueueManager.ts` | 统一命令队列模型 |

## 16. 总结

输入层的本质不是“把字符串发给模型”，而是：

1. 判断输入语义。
2. 在高并发会话中安全调度。
3. 把 slash/bash/prompt 统一转成消息对象。
4. 为当前 turn 注入工具权限、模型、effort 等局部策略。
5. 在准备完毕后才把这次输入送入 query 主循环。

`query.ts` 接收到的不是原始输入字符串，而是一组结构化的 `messages + ToolUseContext + turn 级策略`。
