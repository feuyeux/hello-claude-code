# Transcript 持久化、会话恢复与 `resume` 语义

本篇拆解会话如何写入磁盘，以及 `--resume` / `--continue` 如何把磁盘状态重新恢复为 live runtime。

## 1. 这套系统存的不是“聊天记录”，而是 append-only 会话日志

关键文件：

- `src/utils/sessionStorage.ts`
- `src/utils/conversationRecovery.ts`
- `src/utils/sessionRestore.ts`

`sessionStorage.ts` 写入的并不只是 user/assistant 对话，还包括：

- transcript messages
- summary
- custom title / tag
- agent name / color / setting
- mode
- worktree state
- file history snapshots
- attribution snapshots
- content replacements
- context collapse commits / snapshot

所以它更像：

> 一个 append-only 的 session event log，而不是狭义 chat history。

## 2. transcript 路径与 sessionProjectDir 强耦合

关键代码：

- `src/utils/sessionStorage.ts:202-221` `getTranscriptPath()` / `getTranscriptPathForSession()`
- `src/utils/sessionStorage.ts:247-260` `getAgentTranscriptPath()`

这里一个非常重要的语义是：

- 路径不只取决于 `sessionId`
- 还取决于 `sessionProjectDir`

原因写得很清楚：

- `resume`、branch、worktree 等操作会切换 active session
- 如果 transcript path 仍按旧的 `originalCwd` 推导，就会发生“hook 看到的 transcript_path”和真实落盘位置不一致

会话文件定位本身就是恢复语义的一部分。

## 3. 文件是延迟 materialize 的，不是 session 一开始就创建

关键代码：

- `src/utils/sessionStorage.ts:956-986` `shouldSkipPersistence()` / `materializeSessionFile()`
- `src/utils/sessionStorage.ts:993-1078` `insertMessageChain()`
- `src/utils/sessionStorage.ts:1129-1144` `appendEntry()`

session file 的创建时机非常克制：

- 在首个真正的 user/assistant message 到来之前，只缓存 metadata / pending entries
- 首次出现 user/assistant message 时才 `materializeSessionFile()`

这样做的目的包括：

1. 避免启动即产生 metadata-only orphan session file。
2. 让 `--name`、mode、agentSetting 等信息先缓存，等真正有会话内容时再落盘。
3. 结合 `--no-session-persistence` / `cleanupPeriodDays=0` / test env 一起统一控制是否根本不写 transcript。

transcript 系统默认优先保证：

- resume 质量
- session 列表干净度
- 不制造伪会话

## 4. parentUuid 链才是“恢复对话”的核心结构

关键代码：

- `src/utils/sessionStorage.ts:132-150` `isTranscriptMessage()` / `isChainParticipant()`
- `src/utils/sessionStorage.ts:993-1078` `insertMessageChain()`
- `src/utils/sessionStorage.ts:2070-2146` `buildConversationChain()`

会话恢复不是按“文件顺序全部读出来”，而是按：

- 每条消息的 `uuid`
- 每条消息的 `parentUuid`

来重建主链。

此外还有几个非常关键的特判：

- `progress` 不参与 transcript chain
- `tool_result` 类型 user message 如果带 `sourceToolAssistantUUID`，会改写父节点
- compact boundary 会把 `parentUuid` 断开，并把旧父节点放到 `logicalParentUuid`

transcript 的核心数据结构不是数组，而是：

> 一张 append-only、可裁剪、可跨 boundary 重连的消息 DAG。

`compact boundary`、`snip`、`context collapse` 在运行时分别如何工作，完整说明见：

- [07-context-management.md](./07-context-management.md)

## 5. progress 被明确排除在持久化主链之外

关键代码：`src/utils/sessionStorage.ts:132-184`

源码里对 progress 的态度非常鲜明：

- progress 不是 transcript message
- progress 不参与 parentUuid chain
- 老 transcript 里历史遗留的 progress entry，还需要在 load 时 bridging

原因是：

- progress 是 UI 状态
- 如果让它进入 parent chain，会在 resume 时把真实对话链截断或分叉

因此这里会有：

- `isLegacyProgressEntry()`
- `progressBridge`

这些看起来很“兼容层”的逻辑。

## 6. `loadTranscriptFile()` 的复杂度来自“要在大文件上恢复正确链”

关键代码：

- `src/utils/sessionStorage.ts:3307-3417` `walkChainBeforeParse()`
- `src/utils/sessionStorage.ts:3473-3791` `loadTranscriptFile()`
- `src/utils/sessionStorage.ts:1840-1983` `applyPreservedSegmentRelinks()` / `applySnipRemovals()`

这段代码的关键点不是“读 JSONL”，而是：

1. 大 transcript 不能傻读全量，否则 RSS 爆炸。
2. compact boundary 前的大量旧数据要尽可能跳过。
3. 跳过旧段后，又必须恢复 boundary 前的关键 metadata。
4. 历史 progress、snip、preserved segment 还要被重新桥接。

所以 `loadTranscriptFile()` 实际做的是：

- 预扫描
- 大文件裁剪
- metadata 补回
- legacy bridge
- leaf 计算

它是一个“恢复算法”，不是简单 parser。

## 7. metadata 不是附属品，而是 resume 体验的一部分

关键代码：

- `src/utils/sessionStorage.ts:721-820` `reAppendSessionMetadata()`
- `src/utils/sessionStorage.ts:2759-2914` `restoreSessionMetadata()` / `cacheSessionTitle()` / `saveMode()` / `saveWorktreeState()`

最典型的一点是：

- custom title、tag、agent name/color、mode、worktree state 都会被缓存，并在合适时机重新 append 到 transcript 尾部

原因也写得很明确：

- `/resume` 的 lite metadata 读取依赖尾部窗口
- 如果 compaction 或后续写入把 metadata 挤出 tail window，resume picker 展示就会退化

因此 `reAppendSessionMetadata()` 的职责不是“重复写一下”，而是：

> 让关键 session metadata 始终处于 resume 系统能快速读到的位置。

## 8. sidechain / subagent transcript 是一级公民

关键代码：

- `src/utils/sessionStorage.ts:233-260` `getAgentTranscriptPath()`
- `src/utils/sessionStorage.ts:4191-4352` `getAgentTranscript()` / `loadSubagentTranscripts()`

子代理 transcript 并不是混在主 session 文件里，而是：

- 以 `session/subagents/.../agent-<id>.jsonl` 形式独立落盘
- 仍然使用同样的 load chain 逻辑
- 还能单独提取 content replacements

transcript 系统天然支持：

- 主链
- sidechain
- subagent chain

而不是后来临时拼接出来的功能。

## 9. `loadConversationForResume()` 才是 `resume` 的真正装配点

关键代码：`src/utils/conversationRecovery.ts:459-589`

它会统一处理多种来源：

- `undefined`：`--continue`，取最近 session
- sessionId：按会话恢复
- `LogOption`
- 任意 `.jsonl` 路径

然后依次做：

1. 必要时把 lite log 升级成 full log。
2. copy plan / copy file history。
3. `checkResumeConsistency()`。
4. 从 transcript 恢复技能状态。
5. 反序列化并检测中断状态。
6. 执行 `SessionStart(resume)` hooks。

所以 `resume` 不是“读盘然后 mount REPL”，而是：

> 重新把一份磁盘会话加工成当前进程可继续运行的 live session。

## 10. 反序列化阶段会主动修正老数据与异常中断

关键代码：

- `src/utils/conversationRecovery.ts:164-234` `deserializeMessagesWithInterruptDetection()`
- `src/utils/conversationRecovery.ts:272-344` `detectTurnInterruption()`
- `src/utils/conversationRecovery.ts:348-380` `isTerminalToolResult()`

这里会做几类重要修复：

- 迁移 legacy attachment type
- 过滤 unresolved tool uses
- 过滤 orphaned thinking-only assistants
- 过滤 whitespace-only assistant messages
- 把中断状态分成 `interrupted_prompt` / `interrupted_turn`
- 必要时自动注入一条 meta user continuation message

transcript 恢复不是“相信磁盘一定完美”，而是默认：

> 进程可能在 streaming、tool_use、brief mode 等中间状态被杀掉，因此恢复层必须主动消毒和补形状。

## 11. `sessionRestore.ts` 负责把恢复结果重新注入 bootstrap 与 AppState

关键代码：

- `src/utils/sessionRestore.ts:99-145` `restoreSessionStateFromLog()`
- `src/utils/sessionRestore.ts:200-249` `restoreAgentFromSession()`
- `src/utils/sessionRestore.ts:332-357` `restoreWorktreeForResume()`
- `src/utils/sessionRestore.ts:409-527` `processResumedConversation()`

这层会把磁盘恢复结果重新映射到：

- file history state
- attribution state
- context collapse state
- todo state
- main thread agent type / model override
- worktree cwd
- session metadata cache

并在非 fork resume 时调用：

- `adoptResumedSessionFile()`

让当前 session 直接继续写原 transcript 文件。

`resume` 的完整闭环至少跨了三层：

1. sessionStorage 读与链重建
2. conversationRecovery 反序列化与中断检测
3. sessionRestore 状态回灌

## 12. 一张总图

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A[insertMessageChain / appendEntry] --> B[append-only JSONL]
    B --> C[metadata entries + snapshots + sidechains]
    C --> D[loadTranscriptFile]
    D --> E[chain rebuild + leaf selection + metadata restore]
    E --> F[loadConversationForResume]
    F --> G[deserializeMessagesWithInterruptDetection]
    G --> H[processSessionStartHooks resume]
    H --> I[sessionRestore]
    I --> J[AppState / bootstrap / worktree / agent restored]
```

## 13. 关键源码锚点

| 主题 | 代码锚点 | 说明 |
| --- | --- | --- |
| transcript 路径规则 | `src/utils/sessionStorage.ts:202-260` | sessionProjectDir 与 agent transcript 路径 |
| 延迟 materialize | `src/utils/sessionStorage.ts:956-986`, `993-1078` | 首个真实对话消息才创建文件 |
| append / pending entry 逻辑 | `src/utils/sessionStorage.ts:1129-1274` | 当前 session 与其他 session 的写入分流 |
| metadata 重新追加 | `src/utils/sessionStorage.ts:721-820`, `2759-2914` | title/tag/mode/worktree 的持久化策略 |
| transcript 加载算法 | `src/utils/sessionStorage.ts:3307-3791` | precompact skip、bridge、leaf 计算 |
| 主链恢复 | `src/utils/sessionStorage.ts:2070-2146`, `3870-3924` | `buildConversationChain()` 与 last log |
| sidechain transcript | `src/utils/sessionStorage.ts:4191-4352` | subagent transcript 的单独恢复 |
| 反序列化与中断检测 | `src/utils/conversationRecovery.ts:164-380` | resolve legacy / interruption 语义 |
| resume 装配入口 | `src/utils/conversationRecovery.ts:459-589` | 多来源 resume 的统一入口 |
| 状态回灌 | `src/utils/sessionRestore.ts:99-145`, `200-249`, `332-357`, `409-527` | file history / worktree / agent / AppState 恢复 |

## 14. 总结

这套 transcript/resume 体系的核心不是“把历史消息保存下来”，而是：

1. 用 append-only JSONL 记录可恢复的完整会话状态。
2. 用 parentUuid 链而不是文件顺序恢复主对话。
3. 用大文件裁剪、legacy bridge、metadata 重追加保证 resume 质量。
4. 用 conversationRecovery + sessionRestore 把磁盘日志重新转换回 live runtime。

因此 `resume` 会跨 `sessionStorage.ts`、`conversationRecovery.ts`、`sessionRestore.ts` 三个大文件，而不是一个简单的“读取历史记录”函数。
