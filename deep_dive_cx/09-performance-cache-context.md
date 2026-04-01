# 性能、缓存与上下文治理专题

本文汇总启动性能、prompt cache、上下文治理、资源释放与长会话稳定性相关的工程设计。

## 1. 问题范围

这套工程的大量复杂度并不直接来自业务功能，而是来自以下几类真实成本控制：

- 启动延迟
- 首轮响应延迟
- 长会话内存增长
- prompt cache 失效带来的 token 成本
- 上下文膨胀导致的请求失败
- streaming 与工具执行带来的资源泄露

因此，这篇专题的目标是把散落在各处的“工程性设计”串起来。

## 2. 启动性能：把工作拆成三个窗口

## 2.1 顶层 side effect 窗口

关键代码：`src/main.tsx:1-20`

这里提前做：

- `profileCheckpoint`
- `startMdmRawRead()`
- `startKeychainPrefetch()`

本质上是在争取：

- “模块求值期间并行做别的事”

## 2.2 setup 窗口

关键代码：`src/setup.ts:287-381`

这里做的是：

- 首轮 query 前必须准备的注册与预热
- 但尽量不阻塞 REPL 首屏的东西

例如：

- `getCommands(...)` 预热
- plugin hooks 加载
- attribution hooks 注册
- sink 初始化

## 2.3 首屏后 deferred prefetch 窗口

关键代码：`src/main.tsx:382-431`

这里专门把：

- `getUserContext`
- `getSystemContext`
- `countFilesRoundedRg`
- analytics gates
- model capabilities

推迟到首屏之后。

### 2.3.1 这说明项目的性能优化目标很明确

它区分了：

- 进程可运行
- REPL 首屏可见
- 首轮输入性能准备充分

而不是把所有初始化糊成一坨。

## 3. prompt cache 稳定性是一级设计目标

关键代码：

- `src/main.tsx:445-456`
- `src/services/api/claude.ts:1358-1728`
- `src/services/api/promptCacheBreakDetection.ts`

## 3.1 为什么一个 settings 临时文件路径都要做 content hash

`src/main.tsx:445-456` 的注释非常典型：

- 如果临时 settings 路径用随机 UUID，每个进程都会不同。
- 这个路径会进入工具描述。
- 工具描述参与 prompt cache key。
- 结果是缓存前缀频繁失效。

所以它刻意使用 content-hash-based path。

这类代码很能代表全工程的工程哲学：

> 任何会污染 prompt 前缀的“看似无关细节”都值得修正。

## 3.2 `claude.ts` 里大量 header / beta latch 也是为 cache 稳定

关键代码：`src/services/api/claude.ts:1405-1698`

这里有很多“sticky-on latch”：

- AFK mode header
- fast mode header
- cache editing header
- thinking clear latch

目的都是：

- 一旦这个 header 在本 session 某时刻开始发送，就尽量继续稳定发送
- 避免 session 中途来回切换导致 prompt cache key 波动

## 3.3 prompt cache break detection

`services/api/promptCacheBreakDetection.ts` 专门跟踪：

- system prompt 是否变了
- tool schema 是否变了
- cache read 是否突然掉太多
- cached microcompact 是否是“合法下降”而不是异常失效

这说明团队并不只“希望缓存命中”，而是把缓存失效当作可观测故障来监控。

## 4. 上下文治理不是单一压缩，而是梯度体系

关键代码：`src/query.ts:396-468`

系统对上下文的处理顺序是：

1. tool result budget
2. `snip`
3. `microcompact`
4. `context collapse`
5. `autocompact`
6. 之后还有 reactive compact 参与恢复

## 4.1 梯度图

```mermaid
flowchart LR
    A[原始 messages] --> B[tool result budget]
    B --> C[snip]
    C --> D[microcompact]
    D --> E[context collapse]
    E --> F[autocompact]
    F --> G[必要时 reactive compact / overflow recovery]
```

### 4.1.1 运行顺序不是“四层同时工作”

“四种不同粒度的压缩机制在同时工作”并不准确。更接近源码事实的表述如下：

- 这是 **按顺序尝试的梯度体系**，不是每一轮都四层全开。
- `snip` 和 `microcompact` 的确可能在同一轮都运行。
- `microcompact` 自己又分成互斥的两条活路径：time-based content clearing 和 cached microcompact。
- `context collapse` 会在 `autocompact` 前运行，但当 collapse runtime 真正启用时，`autoCompact.ts` 会 suppress proactive autocompact，让 collapse 自己接管 headroom 管理。
- 严格说，这四层前面还有一层 `tool result budget`，只是它更像“结果尺寸裁剪”，还不是完整的上下文折叠策略。

需要同时明确一个反编译边界：

- `src/services/compact/snipCompact.ts`
- `src/services/compact/snipProjection.ts`
- `src/services/contextCollapse/*`

这几块在当前仓库里是 stub。下面关于 `snip` / `context collapse` 的分析，部分结论来自 `query.ts`、`sessionStorage.ts`、`/context`、`QueryEngine.ts` 的调用点和注释，而不是完整实现体。

### 4.1.2 “三层压缩，让对话永不超限”怎么改写才更贴源码

这一表述抓住了一部分真实设计，但还不够严谨。更接近源码的表述如下：

- 如果只看最常见的重手段链路，可以口语化概括成 `microcompact -> autocompact -> legacy full compact summary`
- 但 `query.ts` 的真实顺序前面还有 `tool result budget` 和可选 `snip`
- 中间还有 `context collapse` 这条更强的结构化路径；当它启用时，proactive autocompact 会被 suppress
- `autocompact` 自己也不是单层动作，而是“先试 `SessionMemory compact`，失败后再退到 `compactConversation()`”

另外，“让对话永不超限”更适合当产品层描述，不适合当代码级结论。源码真正实现的是：

- 预防式压缩
- 失败熔断
- overflow 后的 reactive recovery
- compact 请求自身 prompt-too-long 时的重试与截断补救

这些机制在工程上尽量把会话做成“可持续”，但并不构成数学意义上的绝对不超限保证。

## 4.2 `snip` 的角色

它是轻量级、偏“先切一点历史”的策略。

优点：

- 成本低
- 对当前上下文侵入较小

如果把它再落到代码层，能确认的是：

- `query.ts` 里直接调用 `snipCompactIfNeeded(messagesForQuery)`，返回新的 `messages`、`tokensFreed` 和可选的 boundary message。
- `snipTokensFreed` 会一路传进 `autoCompactIfNeeded()` 和 blocking-limit 判断，专门抵消 `tokenCountWithEstimation()` 看不到的那部分释放量。
- `sessionStorage.ts` 的 `applySnipRemovals()` 注释写得非常明确：snip 不是像 `compact_boundary` 那样截一个 prefix，而是 **删除中间区段**，并在 resume 时重连 parentUuid。
- `utils/messages.ts` 默认会对 API 视图调用 `projectSnippedView()`；REPL scrollback 可以保留全量消息，但送给模型的默认视图要把被 snip 的消息滤掉。
- `QueryEngine.ts` 还说明了另一层差异：REPL 为了 UI 会保留全 history，headless/SDK 路径则会在 replay 后直接裁剪 mutable store，避免无 UI 长会话持续占内存。

代码可以确认 `HISTORY_SNIP` 属于“最细粒度、直接删消息、不做摘要”的机制；但当前仓库缺少 `snipCompact.ts` 正文，因此具体筛选规则仍不完整。

## 4.3 `microcompact` 的角色

它更偏向：

- 对特定 tool results 做细粒度压缩
- 某些场景使用 cached microcompact / cache editing

这比整段摘要更精细，也更利于 prompt cache 复用。

这里需要把两种完全不同的实现分开：

### 4.3.1 time-based microcompact：会直接改消息

`microCompact.ts` 的 `maybeTimeBasedMicrocompact()` 在 cache 冷掉时触发：

- 判定条件是“距离上一次 assistant 消息已经超过阈值”，默认语义就是 1h cache TTL 已过。
- 它会保留最近 `N` 个 compactable tool result，把更老的那些直接改成 `[Old tool result content cleared]`。
- 这是 **内容级压缩**，不是 cache 层编辑。

### 4.3.2 cached microcompact：不改本地消息，改 API cache 视图

cached path 则完全不同：

- 只在主线程、支持的模型、`CACHED_MICROCOMPACT` 打开时可用。
- `microCompact.ts` 只负责收集要删的 `tool_use_id`，把 `pendingCacheEdits` 暂存起来。
- `services/api/claude.ts` 的 `addCacheBreakpoints()` 才会真正把 `cache_edits` block 和 `cache_reference` 塞进请求体。
- API 返回后，`query.ts` 再根据 usage 里的 `cache_deleted_input_tokens` 计算这次实际删掉了多少 token，并补发 microcompact boundary。

因此，microcompact 不能统一描述为“它不改消息内容，只是告诉 API 这些 token 别用了”。代码上应区分为：

- cached microcompact：是
- time-based microcompact：不是

另外，`cache_deleted_input_tokens` 也不是机制本身，而是 **API 返回的统计结果**。

## 4.4 `context collapse` 的角色

它不是简单生成一条摘要消息，而是维护一种 collapse store / projection 视图。

优势在于：

- 对长会话更稳定
- 可在多轮中持续重用 collapse 结果

这部分从周边代码能看到几个关键事实：

- `query.ts` 注释明确说：summary messages 不在 REPL array 里，而是在 collapse store；每次 turn 入口重新 `projectView()`。
- `commands/context/context.tsx` 和 `context-noninteractive.ts` 都把 `projectView()` 当作“得到模型真实视图”的必要步骤；否则 `/context` 会严重高估 token。
- `sessionStorage.ts` 会把 context collapse 的 commit 和 snapshot 以 `marble-origami-commit` / snapshot entry 写进 transcript，并在 resume 时重建这套提交历史。
- overflow 恢复时，`query.ts` 还会先调用 `contextCollapse.recoverFromOverflow()` 去 drain staged collapses，再决定要不要走 reactive compact。

“像 git log 一样维护结构化归档并在每轮重放”这一类比有依据，代码上的准确描述是：

> 类似 commit log 的 collapse store + 每轮投影视图

当前仓库尚未还原出完整实体实现。

更重要的一点是：它和 autocompact 不是并列兜底。`autoCompact.ts` 明确写了，开启 context collapse 后，**proactive autocompact 会被压掉**，因为 collapse 被视为新的主 context-management system。

## 4.5 `autocompact` 的角色

它是更强的一步：

- 当 token 窗口真正逼近阈值时，生成 post-compact messages

这是重手段。

但如果把它说成“最后调一次模型把整个历史压成一段话”，会低估它的真实复杂度。

从 `autoCompact.ts` 和 `compact.ts` 看，autocompact 实际上有两层：

1. 先试 `trySessionMemoryCompaction()`
2. 失败后再走 `compactConversation()`

### 4.5.1 触发条件是“effective window - 13,000”，不是固定 87%

源码常量是：

- `AUTOCOMPACT_BUFFER_TOKENS = 13_000`
- `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3`

但触发阈值不是写死的 87%。真实公式在 `autoCompact.ts`：

1. `getEffectiveContextWindowSize(model)`  
   先从 `getContextWindowForModel(model)` 开始，再减去 `reservedTokensForSummary`
2. `getAutoCompactThreshold(model)`  
   再从这个 effective window 里减去 `13_000`

其中 `reservedTokensForSummary` 又来自：

- `min(getMaxOutputTokensForModel(model), 20_000)`

所以，“接近上下文窗口 87%”不是稳定事实；真正稳定的只有：

> **autocompact 在 effective context window 的基础上预留 13,000 token buffer**

这个 effective window 还会受模型 context size、1M mode、max output cap、环境变量 override 影响，因此百分比会漂移。

### 4.5.2 确实有一个 3 次失败的熔断器

这一点在 `autoCompactIfNeeded()` 里写得非常明确：

- `tracking.consecutiveFailures >= 3` 时，直接停止后续 proactive autocompact 尝试
- compact 成功一次后，失败计数清零
- 失败时会把 `nextFailures` 回传给 `query.ts`，由 query loop 继续线程内状态

这不是一个 UI 层提示，而是实际控制分支，目的是防止 irrecoverable prompt-too-long 场景里每一轮都白打一遍 compact 请求。

### 4.5.3 `NO_TOOLS_PREAMBLE` 属于 legacy compact summary 路径

“完全压缩——AI 总结 `NO_TOOLS_PREAMBLE`”这一描述需要限定作用域。

准确说法是：

- `NO_TOOLS_PREAMBLE` 定义在 `src/services/compact/prompt.ts`
- `getCompactPrompt()` / `getPartialCompactPrompt()` 会把它拼到 compact summarizer prompt 最前面
- `compactConversation()` 用这个 prompt 生成 `summaryRequest`
- `streamCompactSummary()` 再把 `summaryRequest` 发给模型
- forked-agent cache-sharing 路径还会通过 `createCompactCanUseTool()` 直接 deny 所有 tool use

因此，`NO_TOOLS_PREAMBLE` 确实是“模型总结式完全压缩”的关键一环，但它只覆盖 **legacy compactConversation**，不覆盖前面那条 `SessionMemory compact` 快路径。

第一层并不调用新的 compact summarizer，而是：

- 读取现有 session memory
- 结合 `lastSummarizedMessageId` 保留最近消息尾部
- 构造 compact boundary + session memory summary + 少量附件

第二层的传统 compact 也不是“单段摘要”：

- 它会调用专门的 compact prompt，让模型输出结构化 summary
- 然后再组装 `boundaryMarker`、`summaryMessages`、post-compact file attachments、plan attachment、MCP/tool delta attachments、session start hooks、post-compact hooks

因此，autocompact 更准确的代码级定义是：

> 最后的重型上下文重写机制，但产物是“新的 post-compact 上下文包”，不是单纯一段话。

## 4.6 reactive compact / overflow recovery

这类恢复策略会在真实 API overflow 或 prompt-too-long 后参与补救。

系统同时包含预防式压缩和失败后的恢复式压缩。

## 5. REPL 层对内存与 GC 非常敏感

关键代码：

- `src/screens/REPL.tsx:2608-2627`
- `src/screens/REPL.tsx:3537-3545`
- `src/screens/REPL.tsx:3608-3621`
- `src/screens/REPL.tsx:3657-3688`

## 5.1 替换 ephemeral progress 而不是持续 append

原因：

- 某些 progress 每秒一条
- 全部 append 会让 messages 与 transcript 爆炸

## 5.2 大量 stable callback / ref 是为了防闭包保留

注释里明确提到：

- 不稳定 callback 会让旧 REPL render scope 被下游组件引用住
- 长会话下会明显增加内存占用

## 5.3 rewind 时还要清 microcompact/context collapse 状态

因为如果只回滚消息而不重置这些缓存态：

- 新的会话视图会引用旧的 tool_use_ids 或 collapsed state
- 导致严重不一致

## 6. `claude.ts` 对 streaming 资源泄漏有专门防护

关键代码：

- `src/services/api/claude.ts:1515-1526`
- 以及后续 cleanup 注释

源码明确写到：

- Response 持有 native TLS/socket buffers
- 这些不在 V8 heap 里
- 必须显式 cancel/release

这说明作者并不是泛泛而谈“避免泄漏”，而是针对 Node/SDK 真实行为做了防护。

## 7. query checkpoints 是贯穿式观测点

关键代码：

- `src/query.ts`
- `src/services/api/claude.ts`
- `src/screens/REPL.tsx:2767-2810`

常见 checkpoint 包括：

- `query_fn_entry`
- `query_snip_start/end`
- `query_microcompact_start/end`
- `query_autocompact_start/end`
- `query_api_streaming_start/end`
- `query_tool_execution_start/end`
- `query_context_loading_start/end`

意义：

- 可以把一次 turn 拆成多个阶段分析瓶颈。

## 8. transcript 与持久化也被当成性能/稳定性问题处理

例如 `QueryEngine.ts` 里会：

- 对 assistant 消息 transcript write 采用 fire-and-forget
- 对 compact boundary 前的 preserved tail 做提前 flush
- 在结果返回前做最后 flush

这说明 transcript 不是“顺便记一下”，而是会直接影响：

- resume 正确性
- SDK 进程被上层杀掉时的数据完整性

## 9. 这套系统的性能设计关键词

可以总结为：

- 提前预取
- 延迟预取
- 缓存稳定
- 分层压缩
- 渐进恢复
- 稳定闭包
- 显式资源释放
- 埋点可观测

## 10. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| 顶层启动优化 | `src/main.tsx:1-20` | 启动最早期 side effects |
| deferred prefetch | `src/main.tsx:382-431` | 首屏后预取 |
| settings 路径稳定化 | `src/main.tsx:445-456` | 避免随机路径破坏 prompt cache |
| 上下文治理阶梯 | `src/query.ts:396-468` | snip / microcompact / collapse / autocompact |
| API request cache 相关组装 | `src/services/api/claude.ts:1358-1728` | system blocks、betas、cache editing |
| prompt cache break detection | `src/services/api/promptCacheBreakDetection.ts` | 缓存异常监控 |
| REPL 内存控制 | `src/screens/REPL.tsx:2608-2627`, `3537-3621` | progress 替换与稳定 callback |
| stream 资源释放 | `src/services/api/claude.ts:1515-1526` | native 资源 cleanup |

## 11. 总结

这套工程最值得学习的地方之一，不是某个功能，而是它如何把“长期运行的 Agent 会话”当成一类需要精细治理的系统：

- 启动要分阶段。
- 缓存要稳定。
- 上下文要分层压缩。
- 闭包、stream、transcript 都要防泄漏与防失真。

这些机制共同构成了面向长会话、真实成本和真实故障模式的生产级运行时。
