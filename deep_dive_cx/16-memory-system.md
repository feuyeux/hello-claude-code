# Claude Code 的记忆系统

本文分析 Claude Code 的 memory 子系统，重点覆盖记忆分层、写入路径、读取机制以及 `KAIROS` 对长期记忆策略的影响。

---

## 1. 结构概览：Claude Code 不是只有一个 memory

Claude Code 至少有下面几套彼此相关、但职责不同的持久化机制：

| 子系统 | 关键源码 | 存储形态 | 主要用途 |
| --- | --- | --- | --- |
| auto-memory | `src/memdir/memdir.ts`、`src/memdir/memoryTypes.ts` | `MEMORY.md` + topic files | 保存长期有价值、且不能从代码库直接推导出的上下文 |
| team memory | `src/memdir/teamMemPrompts.ts` | private/team 双目录 | 把“个人记忆”扩展成可协作的组织记忆 |
| KAIROS daily log | `src/memdir/memdir.ts`、`src/memdir/paths.ts` | `logs/YYYY/MM/YYYY-MM-DD.md` | 长生命周期 assistant 模式下的 append-only 日志记忆 |
| extractMemories | `src/services/extractMemories/prompts.ts` | 后台 memory 写入 worker | 在主对话没主动写记忆时，异步抽取最近消息里的可保存信息 |
| dream / consolidation | `src/services/autoDream/*` | 从 logs / transcripts 蒸馏回 topic memory | 定期把松散日志整理成 durable memory |
| SessionMemory | `src/services/SessionMemory/prompts.ts` | 当前会话 notes 文件 | 保持当前会话的结构化续航，不是长期知识库 |
| agent memory | `src/tools/AgentTool/agentMemory.ts` | 每类 agent 自己的 `MEMORY.md` | 给子代理保留跨会话、跨任务的专属经验 |
| `remember` skill | `src/skills/bundled/remember.ts` | 审阅报告，不直接落盘 | 让用户人工整理 memory / `CLAUDE.md` / `CLAUDE.local.md` |

真正关键的判断是：

- Claude Code 把 **长期记忆**、**当前会话续写**、**子代理经验**、**夜间整理** 拆成了不同层。
- `KAIROS` 会改变“长期记忆”的**写入形态**，不是只多一段 prompt 文案。

---

## 2. auto-memory 是主 system prompt 的一部分

核心文件：

- `src/memdir/memdir.ts`
- `src/memdir/paths.ts`
- `src/constants/prompts.ts`

`loadMemoryPrompt()` 的返回值会被塞回主系统提示。

这表明 auto-memory 不是“外置插件”，而是模型在主回合里就必须遵守的行为约束。Claude Code 不是先回答问题、再顺手调用一个 memory 服务；它是在主 prompt 中直接定义：

- 什么时候该读 memory
- 什么信息值得存
- 什么东西绝对不能存
- 保存时该写成什么格式

默认形态下，auto-memory 的入口是：

- memory 目录：`getAutoMemPath()`
- 索引文件：`getAutoMemEntrypoint()`，也就是 `MEMORY.md`

这一层的基本结构是：

1. `MEMORY.md` 只做索引。
2. 真正的内容写在独立 memory files 里。
3. 模型下一次启动时，会把索引内容再次加载进上下文。

这套设计比“往一个大文件里越写越多”更稳定，因为：

- index 可控，便于裁剪
- topic files 可按语义拆分
- 旧 memory 可单独更新或删除，不会把整个索引重写坏

### 2.1 查询时并不会把整个 memory 目录都塞进上下文

这里存在一个关键设计分叉。

关键文件：

- `src/utils/claudemd.ts`
- `src/context.ts`
- `src/utils/attachments.ts`
- `src/memdir/findRelevantMemories.ts`

`context.ts` 默认会通过 `getClaudeMds(filterInjectedMemoryFiles(await getMemoryFiles()))` 把 memory/instructions 拼进 `userContext`。

但 `claudemd.ts` 里 `filterInjectedMemoryFiles()` 的注释明确写了：

- 当 `tengu_moth_copse` 打开时
- `findRelevantMemories` prefetch 会通过 attachment 注入相关 memory files
- 此时 `MEMORY.md` index 不再直接注入 system prompt

在这条实验分支上，Claude Code 并不会始终把 auto-memory 的入口文件原样塞进主上下文，而是改成了：

1. 主上下文不直接吃整个 `MEMORY.md` / team memory index。
2. 查询时再按当前问题动态挑选“相关 memory files”。
3. 选中的文件以 `relevant_memories` attachment 的形式注入。

这本质上是在把 memory 从“静态常驻上下文”改造成“按需召回上下文”。

### 2.2 相关性筛选明确是“精确度优先于召回率”

这条设计在源码里不是推测，而是直接写在 prompt 里的。

关键文件：`src/memdir/findRelevantMemories.ts`

里面的 `SELECT_MEMORIES_SYSTEM_PROMPT` 直接要求 selector：

- 只返回那些 **clearly be useful**
- 最多选 5 个
- 如果不确定某个 memory 是否有用，就 **不要选**
- 如果没有任何 memory 明显有用，可以返回空列表

这其实就是非常明确的：

> precision 优先于 recall

Claude Code 宁可漏掉一个“可能有帮助”的 memory，也不愿把一个不相关的 memory 塞进来污染上下文。

### 2.3 这个相关性判断确实是另一个 Sonnet side query

同一个文件里，`selectRelevantMemories()` 的实现不是本地关键词匹配，而是：

- 先 `scanMemoryFiles()` 扫描 memory 目录
- 只读取每个文件前 30 行 frontmatter
- 抽出：
  - `filename`
  - `mtimeMs`
  - `description`
  - `type`
- 再用 `formatMemoryManifest()` 组装成 manifest
- 然后调用：

```ts
sideQuery({
  model: getDefaultSonnetModel(),
  system: SELECT_MEMORIES_SYSTEM_PROMPT,
  ...
  querySource: 'memdir_relevance',
})
```

这里几个事实都很关键：

1. 它调用的是 `sideQuery(...)`，不是主对话回合。
2. 模型是 `getDefaultSonnetModel()`，也就是默认 Sonnet 路线。
3. 输出格式是 JSON schema，只允许返回 `selected_memories: string[]`。
4. 它看的不是 memory 全文，而是 file header manifest。

换句话说，Claude Code 确实在用 **另一个 Sonnet 模型调用** 来做“当前 query 和哪些 memory file 相关”的判定。

### 2.4 它不是朴素召回，而是多重限流后的“窄注入”

从 `memoryScan.ts` 和 `attachments.ts` 还能看出，这条链是层层收紧的：

- `scanMemoryFiles()` 最多只看 200 个 `.md` memory files，而且排除 `MEMORY.md`
- 每个文件只读前 30 行 frontmatter
- selector 最多选 5 个
- `startRelevantMemoryPrefetch()` 只在：
  - auto-memory 打开
  - feature gate 打开
  - 最近用户输入不是单词 prompt
  - 本 session 已注入 memory 总字节数还没超过 `60KB`
  时才启动
- `readMemoriesForSurfacing()` 读取正文时还会继续截断：
  - 最多 200 行
  - 最多 4096 bytes/文件
- `filterDuplicateMemoryAttachments()` 还会去掉：
  - 之前 turn 已 surfacing 过的 memory
  - 本 turn 已通过 FileRead/Write/Edit 进入上下文的 memory

这说明它的设计目标不是“尽量多召回”，而是：

> 只把最值得塞进当前上下文的那几份 memory，以一个非常受控的大小注入。

### 2.5 它还是异步 prefetch，不阻塞主回合

`attachments.ts` 和 `query.ts` 还补了最后一个很重要的工程细节：

- `startRelevantMemoryPrefetch()` 会在 turn 里异步启动
- prefetch 和主模型 streaming / 工具执行并行
- `query.ts` 到 collect point 时，如果这个 prefetch 已经完成，才把 `relevant_memories` attachment 注入
- 如果还没完成，就直接跳过，留给下一次 loop 机会

这套“另一个 Sonnet 先帮你挑相关记忆”的机制不是阻塞式前置步骤，而是一个 **机会主义的异步召回器**。

这进一步解释了为什么它必须偏 precision：

- 它是 background assist，不是主回合核心链路
- 既然是 opportunistic prefetch，就更不能把低质量 memory 大量塞进上下文制造噪声
- 因此“if unsure, do not include”不是一句抽象 prompt engineering，而是和 runtime 位置相匹配的产品取舍

---

## 3. 这套系统最重要的不是“记住”，而是“限制记什么”

核心文件：`src/memdir/memoryTypes.ts`

Claude Code 把 memory 严格限制成四类：

- `user`
- `feedback`
- `project`
- `reference`

这四类背后的设计意图非常清楚：

- `user`：记用户画像、角色、知识背景、协作偏好
- `feedback`：记用户对工作方式的纠偏或确认
- `project`：记项目里的非代码事实，比如 deadline、incident、决策原因
- `reference`：记外部系统入口，比如 Grafana、Linear、Slack、dashboard

同时，它又非常明确地禁止模型把下面这些内容写进 memory：

- 代码结构、架构、项目目录
- file paths
- git history / blame / who changed what
- debugging recipe
- 已经写进 `CLAUDE.md` 的东西
- 当前对话里的临时任务状态

这说明 Claude Code 的 memory 定位不是“第二份项目文档”，而是：

> 保存那些对未来对话仍然有价值、但又不能从当前仓库状态直接推导出来的上下文。

这一层还有两个很强的防漂移约束：

1. **记忆可能过时，使用前要验证。**
2. **用户要求忽略 memory 时，要当作 `MEMORY.md` 为空，不能边忽略边引用。**

这两条约束直接在 prompt 里防止“历史提示污染当前判断”。

---

## 4. team memory 把记忆从“个人层”升级成“协作层”

核心文件：`src/memdir/teamMemPrompts.ts`

当 team memory 启用时，Claude Code 会把 memory 拆成两个目录：

- private directory
- shared team directory

`buildCombinedMemoryPrompt()` 明确告诉模型：

- 哪些 memory 应该永远 private
- 哪些 memory 默认 private，但在项目级约束成立时可以升为 team
- 哪些 memory 强烈偏向 team
- shared memory 里绝不能保存敏感信息

这里最值得注意的是：Claude Code 不是先让模型“自由发挥是否共享”，而是把 **scope 规则也编进 prompt taxonomy** 里。

因此 team memory 并不是简单地“多一个目录”，而是：

1. 让同一条记忆同时拥有 **type** 和 **scope** 两个维度。
2. 让“这是不是团队约束”成为模型在写入前必须做的判断。
3. 把组织知识和个人偏好分开，避免污染。

这套设计将组织知识与个人偏好分离：

- “我个人喜欢你回答简短” 不应进入 team memory。
- “这个仓库所有集成测试都必须打真实数据库” 这类规则则应该上升成 team memory。

---

## 5. KAIROS 机制：把记忆系统切成 daily log 模式

`KAIROS` 不是只在 UI 上多几个按钮，也不是只给主 prompt 多一段 addendum。它会改变 Claude Code 的长期记忆写入方式。

### 5.1 KAIROS 的激活条件

关键文件：

- `src/main.tsx`
- `src/bootstrap/state.ts`
- `src/assistant/index.ts`

从 `main.tsx` 能看到，assistant 模式启用并不只是看 `feature('KAIROS')`：

1. 需要 build-time `feature('KAIROS')`。
2. 需要 assistant mode 判定为真。
3. 需要工作目录已经通过 trust dialog。
4. 需要 `kairosGate.isKairosEnabled()` 通过，或者由 `--assistant` 强制。
5. 最后会调用 `setKairosActive(true)`。

`KAIROS` 是 **assistant-mode runtime latch**，不是普通布尔开关。

还要注意一个反编译仓库特性：

- 当前反编译树中的 [index.ts](/Users/han/coding/hello-claude-code/claude-code/src/assistant/index.ts) 是 stub。
- 这里的 `isAssistantMode()`、`markAssistantForced()`、`getAssistantSystemPromptAddendum()` 都返回空实现。

所以在这份 reverse-engineered 外部构建里，`KAIROS` 相关路径大多是“结构仍在，但运行时关着”的状态。即便如此，memory 相关 prompt 和路径设计仍然完整保留下来了，足够分析它的原始意图。

### 5.2 KAIROS 打开的那一刻，`loadMemoryPrompt()` 会走另一条分支

关键文件：`src/memdir/memdir.ts`

`loadMemoryPrompt()` 里最重要的一段逻辑是：

1. 先检查 auto-memory 是否启用。
2. 如果 `feature('KAIROS') && autoEnabled && getKairosActive()`，直接返回 `buildAssistantDailyLogPrompt(skipIndex)`。
3. 这个分支优先级高于 TEAMMEM。

源码注释写得非常明确：

- `KAIROS daily-log mode takes precedence over TEAMMEM`
- append-only log paradigm does not compose with team sync

这句话的含义非常重：

- KAIROS 不是在原有 memory 上“叠一层功能”。
- 它是把记忆写入范式从“维护可编辑的 memory index + topic files”切换成“按天 append 的日志流”。

### 5.3 KAIROS 的写入路径不是 `MEMORY.md`，而是按天命名的日志

关键文件：`src/memdir/paths.ts`

`getAutoMemDailyLogPath(date)` 返回的路径模式是：

```text
<autoMemPath>/logs/YYYY/MM/YYYY-MM-DD.md
```

`buildAssistantDailyLogPrompt()` 则要求模型：

- 把值得记住的信息 append 到“今天的 daily log”
- 每条写成带时间戳的短 bullet
- 第一次写时自动创建目录和文件
- 不要重写、不要整理、不要重排，这是 append-only log

这里最精细的一点是 prompt cache 适配：

- prompt 里不会直接内联“今天的绝对路径”
- 而是写成 `logs/YYYY/MM/YYYY-MM-DD.md` 这种 pattern
- 模型要从 `currentDate` 推导今天的真实日期
- 午夜跨天时，再切到新的一天的 log 文件

这明显是在为 **长生命周期会话 + system prompt cache** 做设计。

### 5.4 KAIROS 与普通 auto-memory 的核心差别

| 维度 | 普通 auto-memory | KAIROS daily log |
| --- | --- | --- |
| 主写入目标 | topic files + `MEMORY.md` index | 当天的 `logs/YYYY/MM/YYYY-MM-DD.md` |
| 写入风格 | 语义化、可更新、可去重 | append-only、按时间顺序累积 |
| 立即维护 index | 是 | 否 |
| 对话形态假设 | 普通会话，按任务推进 | assistant/perpetual session，持续存在 |
| 与 TEAMMEM 组合 | 可以有 combined prompt | 不组合，KAIROS 分支优先 |
| 后续整理方式 | 直接维护 topic files | 依赖后续 consolidation / `/dream` 蒸馏 |

### 5.5 为什么 Claude Code 要这样做

注释已经给出答案：

- assistant session 是长期存在的
- 长期会话里如果每次都重写 `MEMORY.md`，索引会抖动很大
- append-only daily log 更接近日志系统，适合持续写入
- nightly dream 再做一次冷静、集中、批处理式的蒸馏

所以 KAIROS 本质上把 memory 从“在线知识库编辑”改造成了“先写事件流，再做离线汇总”。

这更像 event sourcing，而不是传统 wiki。

---

## 6. dream / consolidation：把 daily log 再蒸馏回 durable memory

关键文件：

- `src/services/autoDream/consolidationPrompt.ts`
- `src/services/autoDream/autoDream.ts`
- `src/skills/bundled/index.ts`

`buildConsolidationPrompt()` 把 dream 流程拆成四阶段：

1. Orient：先看 memory dir、`MEMORY.md`、现有 topic files
2. Gather recent signal：优先看 daily logs，再看 drift，再 grep transcripts
3. Consolidate：把值得长期保存的信息合并进 memory files
4. Prune and index：更新 `MEMORY.md`，删 stale pointer，保持 index 简短

这说明 dream 的职责不是“再提取一遍记忆”，而是：

- 把 append-only 日志转成 durable topic memory
- 修复旧 memory 漂移
- 清理索引膨胀

### 6.1 非 KAIROS 和 KAIROS 的 consolidation 路径不同

`autoDream.ts` 里有一句非常关键的注释：

```ts
if (getKairosActive()) return false // KAIROS mode uses disk-skill dream
```

结论如下：

- 非 KAIROS 模式下，可以走后台 `autoDream`
- KAIROS 模式下，不走这条后台 consolidate 触发器，而是改用 disk-skill 版本的 `dream`

`src/skills/bundled/index.ts` 也能看到：

- 只有 `feature('KAIROS') || feature('KAIROS_DREAM')` 时才注册 `dream`

### 6.2 当前反编译树里，`dream` skill 的源码没有完整落盘

这个仓库里能看到 `registerDreamSkill()` 的注册入口，但 `src/skills/bundled/dream.ts` 没有反编译出来。

因此目前能确认的是：

- `dream` 机制肯定存在
- 它和 KAIROS / KAIROS_DREAM 有直接关系
- `consolidationPrompt.ts` 已经把 dream 的核心工作流讲得很清楚
- `autoDream.ts` 明确把 KAIROS 和非 KAIROS 的 consolidate 路径区分开了

命令层的完整实现细节在当前仓库里仍未完整还原，因此相关结论需要限定在现有可见代码范围内。

---

## 7. SessionMemory 不是长期记忆，而是“当前会话的续写笔记”

关键文件：`src/services/SessionMemory/prompts.ts`

`SessionMemory` 和 auto-memory 最大的区别是：

- auto-memory 是为了 **未来会话**
- SessionMemory 是为了 **当前会话在 compact / resume / continuation 之后还能接得上**

它内置了一整套固定模板，包含：

- `# Session Title`
- `# Current State`
- `# Task specification`
- `# Files and Functions`
- `# Workflow`
- `# Errors & Corrections`
- `# Codebase and System Documentation`
- `# Learnings`
- `# Key results`
- `# Worklog`

默认更新 prompt 还明确规定：

- 不要把这次 note-taking instruction 本身写进 notes
- 不要把 system prompt、`CLAUDE.md`、旧 session summaries 里的内容搬进来
- 只能用 `Edit` 工具改 notes file
- header 和 italic description 必须原样保留
- 要控制 section token 大小

因此 SessionMemory 更接近：

> 为“当前任务上下文接续”服务的结构化 notes 文件。

它不是长期 memory taxonomy 的一部分，也不该被当作用户/项目长期知识库。

---

## 8. extractMemories 是后台受限写入 worker

关键文件：`src/services/extractMemories/prompts.ts`

这个 prompt 非常像一个严格约束的后台子代理。

它的特点是：

1. 只看最近若干条消息。
2. 不准去读代码验证，也不准额外调查。
3. shell 只允许 read-only 命令。
4. memory 目录内才允许 `Edit` / `Write`。
5. 明确建议两阶段执行：
   - 第一轮并行 `Read`
   - 第二轮并行 `Write/Edit`

源码注释还说明了一个关键点：

- extract agent 是主对话的 perfect fork
- 主系统 prompt 本来就已经带完整 memory 规则
- 如果主 agent 本回合自己写过 memory，extract 流程会跳过

所以 extractMemories 不是另一套 memory policy，而是：

> 主 memory policy 的后台补写器。

它的角色是补漏，不是重定义规则。

---

## 9. agent memory：子代理也有自己的持久记忆

关键文件：`src/tools/AgentTool/agentMemory.ts`

Claude Code 不只给主会话做 memory，也给 agent 做了独立 memory scope：

- `user`
- `project`
- `local`

对应目录大致是：

- user：`~/.claude/agent-memory/<agentType>/`
- project：`.claude/agent-memory/<agentType>/`
- local：`.claude/agent-memory-local/<agentType>/`

`loadAgentMemoryPrompt()` 会复用通用 memory prompt builder，再附加 scope note，例如：

- user-scope 要更通用，跨项目适用
- project-scope 面向项目团队共享
- local-scope 面向本机/本仓库，不进版本控制

这说明 Claude Code 对 agent 的看法不是“一次性 worker”，而是：

- agent 也可以形成长期经验
- 这些经验也需要明确 scope
- agent 记忆和主对话记忆是平行层，而不是简单复用

---

## 10. `remember` skill 是人工整理层，不是自动写入层

关键文件：`src/skills/bundled/remember.ts`

`remember` skill 的价值，在于它让用户可以主动审查 memory landscape。

它会要求模型同时审视：

- auto-memory
- `CLAUDE.md`
- `CLAUDE.local.md`
- team memory

然后把候选动作分成四组：

1. `Promotions`
2. `Cleanup`
3. `Ambiguous`
4. `No action needed`

最重要的是，它明确要求：

- **只提案，不直接改**
- 模糊项要问用户，不要猜

这说明 Claude Code 团队很清楚：memory 不能完全自动化。

自动提取擅长“收集”，但不擅长“治理”；而 `remember` skill 就是补治理这一层。

---

## 11. 把这些层串起来，Claude Code 的记忆主线其实很清楚

可以把整套机制理解成下面这条流水线：

### 11.1 主回合前

- 主系统提示加载 auto-memory / team memory / KAIROS daily-log rules
- `CLAUDE.md` 仍然是另一条平行的 instruction layer

### 11.2 主回合中

- 模型根据主 prompt 决定是否读取 memory
- 也可能在当前回合直接写 memory

### 11.3 主回合后

- 如果主回合没写、但最近消息里有值得保存的信息，`extractMemories` 可以补写
- 当前任务的连续性则由 SessionMemory 维护

### 11.4 更长期的整理

- 普通模式下，后台 `autoDream` 可以定时 consolidate
- KAIROS 模式下，daily logs 走 `dream` 路线做蒸馏

### 11.5 人工治理

- 用户可以用 `remember` 把 auto-memory 中真正应该升格为 `CLAUDE.md` / `CLAUDE.local.md` / team memory 的内容整理出来

换句话说，Claude Code 的 memory 不是一个文件，而是一整套：

- 在线读写策略
- 后台抽取策略
- 夜间蒸馏策略
- 人工治理策略
- 多作用域持久化策略

---

## 12. KAIROS 在其他文档里不是完全没有，但之前没有独立讲清

`KAIROS` 在现有 `deep_dive_cx` 文档里已经出现过，但都不是专门的 memory 视角：

- [01-architecture.md](./01-architecture.md) 提到它是一个重要 feature family
- [10-queryengine-sdk.md](./10-queryengine-sdk.md) 提到 memory mechanics prompt
- [15-prompt-system.md](./15-prompt-system.md) 已经写到 `KAIROS` 会切到 daily log prompt

但在这之前，还没有一篇文档把下面几件事放到一起讲：

1. `KAIROS` 的 assistant-mode gate
2. `loadMemoryPrompt()` 如何切分支
3. daily log 路径模式
4. 为什么它和 TEAMMEM 不组合
5. dream / consolidation 如何把日志重新蒸馏成 durable memory

这篇文档就是把这条链路单独闭环。

---

## 13. 关键源码锚点

推荐按以下顺序核对相关源码：

1. `src/memdir/memdir.ts`
2. `src/memdir/memoryTypes.ts`
3. `src/memdir/teamMemPrompts.ts`
4. `src/memdir/paths.ts`
5. `src/main.tsx` 里 `kairosEnabled` / `setKairosActive(true)` 那段
6. `src/services/extractMemories/prompts.ts`
7. `src/services/SessionMemory/prompts.ts`
8. `src/services/autoDream/consolidationPrompt.ts`
9. `src/services/autoDream/autoDream.ts`
10. `src/tools/AgentTool/agentMemory.ts`
11. `src/skills/bundled/remember.ts`
12. `src/skills/bundled/index.ts`

---

## 14. 总结

Claude Code 的 memory system 将 **长期知识、当前会话续航、协作共享、子代理经验、后台蒸馏与人工治理** 拆分成多个相互配合的子系统；`KAIROS` 则进一步把长期记忆从在线编辑模式切换为 `daily log + dream consolidation` 的运行模式。
