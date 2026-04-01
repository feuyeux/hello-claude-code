# Claude Code 的提示词系统

本文分析 Claude Code 中各类提示词资产的类型、注入时机和运行时装配方式。

## 1. 定义

Claude Code 的“提示词系统”不是单个 `systemPrompt` 文件，而是一个由多层文本资产共同组成的运行时装配体系：

1. 主系统提示。
2. 用户上下文与系统上下文。
3. 工具描述与工具 schema 文本。
4. slash command / skill / plugin 展开的任务模板。
5. 子代理的专用 system prompt。
6. 各种二级模型调用的专用 prompt，例如 compact、memory、summary、title generation。

Claude Code 不是“先写一大段 system prompt，再随便调用工具”，而是把 prompt 当成整个运行时协议的一部分。

---

## 2. 先划清边界：什么算“提示词”

如果按“是否真正进入模型上下文”来划分，这个仓库里的文本大致分三类：

### 2.1 一定会进入模型

- `src/constants/prompts.ts` 里的主系统提示。
- `src/context.ts` 里注入的 `CLAUDE.md`、日期、git status。
- `src/tools/*/prompt.ts` 里的工具描述。
- `src/commands/*.ts` 中 `type: 'prompt'` 命令返回的文本模板。
- `src/skills/loadSkillsDir.ts`、`src/utils/plugins/loadPluginCommands.ts` 把 Markdown 技能/插件编译成的 prompt。
- `src/tools/AgentTool/built-in/*.ts` 里的子代理 system prompt。
- `src/services/compact/prompt.ts`、`src/services/SessionMemory/prompts.ts` 等二级任务 prompt。

### 2.2 可能进入模型

- hook 配置里的 prompt。
- MCP server 返回的 `instructions`。
- CLI 启动参数里的 `--system-prompt` / `--append-system-prompt`。
- 运行时 feature 打开的附加提示，例如 proactive、brief、chrome、advisor。

### 2.3 不应混进“提示词分析”的内容

- 单纯的 UI 文案、菜单文字、日志文本。
- 只展示给用户但不会送进模型的状态文案。
- 大量反编译残留的 stub 文件。

这篇文档聚焦 2.1 和 2.2。

---

## 3. 全局地图

| 层级 | 典型源码 | 进入模型的方式 | 作用 |
| --- | --- | --- | --- |
| 主系统提示 | `src/constants/prompts.ts` | `getSystemPrompt()` | 定义 Claude Code 的角色、行为边界、风格、工具策略 |
| 用户上下文 | `src/context.ts` | `prependUserContext(...)` | 注入 `CLAUDE.md`、日期等“看起来像 user meta message”的上下文 |
| 系统上下文 | `src/context.ts` | `appendSystemContext(...)` | 追加 git status、cache breaker 等系统信息 |
| API 前缀块 | `src/services/api/claude.ts` | 请求前再 prepend | attribution、CLI prefix、advisor、chrome 附加说明 |
| 工具提示 | `src/tools/*/prompt.ts` | tool schema description | 把工具的语义、限制、最佳实践暴露给模型 |
| 命令模板 | `src/commands/*.ts` | slash command 展开成用户消息 | 把高层工作流包装成可重用任务模板 |
| 技能/插件 prompt | `src/skills/*`、`src/utils/plugins/*` | Markdown 编译成 `Command` | 让本地/插件能力变成 prompt 资产 |
| 子代理 system prompt | `src/tools/AgentTool/built-in/*.ts` | AgentTool 派生线程 | 给不同 agent 赋予专门人格和约束 |
| 二级模型 prompt | `src/services/*`、`src/utils/*` | `queryHaiku/queryModelWithoutStreaming` | 完成摘要、命名、分类、记忆提取等专用任务 |

---

## 4. 主链路：一次请求如何把提示词真正装进模型

## 4.1 基础 system prompt 从 `getSystemPrompt()` 开始

核心文件：`src/constants/prompts.ts`

`getSystemPrompt(...)` 负责构造 Claude Code 的基础 system prompt 数组。它不是一段字符串，而是一个分块数组，后面还会继续加工。

它的静态主干大致是：

1. `getSimpleIntroSection()`
2. `getSimpleSystemSection()`
3. `getSimpleDoingTasksSection()`
4. `getActionsSection()`
5. `getUsingYourToolsSection()`
6. `getSimpleToneAndStyleSection()`
7. `getOutputEfficiencySection()`

然后再接动态块：

- session-specific guidance
- auto memory
- env info
- language
- output style
- MCP instructions
- scratchpad
- tool-result clearing
- summarize-tool-results
- token budget / brief / proactive 等 feature 相关块

## 4.2 `QueryEngine` 和 `query()` 并不会直接把它原样发出去

相关文件：

- `src/QueryEngine.ts`
- `src/query.ts`
- `src/utils/queryContext.ts`

运行时还有几层装配：

1. `fetchSystemPromptParts(...)` 先拿到：
   - `defaultSystemPrompt`
   - `userContext`
   - `systemContext`
2. `customSystemPrompt` 会直接替换默认 system prompt。
3. `appendSystemPrompt` 会在末尾继续追加。
4. 某些模式还会再加 memory mechanics prompt、coordinator context、agent prompt。
5. `appendSystemContext(systemPrompt, systemContext)` 会把 systemContext 作为 system prompt 尾部拼进去。
6. `prependUserContext(messages, userContext)` 会把 userContext 作为一条 meta user message 放到消息前面。

这说明 Claude Code 的真正“上下文前缀”不是单一 system prompt，而是：

`system prompt blocks + user meta context message + 正常消息历史`

## 4.3 到了 API 层，还会再 prepend 一次

核心文件：`src/services/api/claude.ts`

在真正发请求前，`claude.ts` 会在系统提示前再塞几块：

- attribution header
- CLI system prompt prefix
- advisor 指令
- chrome tool search 指令

`constants/prompts.ts` 并不是最后一层。

---

## 5. 主系统提示的内部结构

## 5.1 这段 prompt 不是“教模型做事”，而是“定义产品人格”

`src/constants/prompts.ts` 里的主系统提示最核心的几件事是：

1. 定义身份：你是 Claude Code，不是普通聊天机器人。
2. 定义任务域：主要做软件工程任务。
3. 定义工具观：优先专用工具，不要乱用 Bash。
4. 定义风险观：高风险动作默认先确认。
5. 定义沟通观：中途汇报要短、要有信息量。
6. 定义真实性：不要虚报测试结果，不要把未验证工作说成完成。

这比“写点礼貌话术”要重得多，它直接规定了 Claude Code 的产品行为。

## 5.2 静态 section 的设计意图

### `# System`

重点是：

- 工具外文本会直接展示给用户。
- 权限模式是真实存在的执行边界。
- `<system-reminder>` 是系统层信号，不等于普通用户文本。
- 需要警惕 prompt injection。
- hooks 反馈应视为用户输入的一部分。

这部分定义的是“运行时协议”。

### `# Doing tasks`

这块非常像 Anthropic 内部对 coding agent 的经验总结，尤其强调：

- 不要过度设计。
- 不要凭空改没读过的代码。
- 不要随便创建新文件。
- 失败时先诊断，不要盲试。
- 修 bug 时不要顺手大重构。
- 要忠实汇报测试/验证结果。

它本质上是在压制“LLM 工程常见坏习惯”。

### `# Executing actions with care`

这块把动作按“可逆性”和“爆炸半径”来建模：

- 本地、可逆操作通常可直接做。
- 难以回滚、影响共享状态、对外可见的动作要先确认。

Claude Code 比一般 IDE 助手更像“代理系统”，原因在于它具备真实执行能力，因此 prompt 必须明确风控逻辑。

### `# Using your tools`

这里不是简单列工具，而是强行建立工具优先级：

- 读文件优先 `Read`
- 编辑优先 `Edit`
- 新建优先 `Write`
- 搜文件优先 `Glob`
- 搜内容优先 `Grep`
- Bash 只做 shell 真正需要的事

这块是整个工具体系能够“可审查”的关键。

### `# Tone and style` 与 `# Output efficiency`

这两块定义用户可感知的产品风格：

- 输出短而直接。
- 引用代码要带 `file:line`。
- 不要在 tool call 前面写冒号。
- 外部用户版更强调简洁，内部 `ant` 版更强调“人能读懂的连续 prose”。

## 5.3 动态 section 的设计意图

主动态段包括：

- `session_guidance`
- `memory`
- `ant_model_override`
- `env_info_simple`
- `language`
- `output_style`
- `mcp_instructions`
- `scratchpad`
- `frc`
- `summarize_tool_results`

这些块的共同特点是：

1. 运行时依赖更多上下文。
2. 可能因 session 状态而变化。
3. 不能随便放进静态前缀，否则 prompt cache 会炸。

---

## 6. 这套系统为什么如此在意 prompt cache

## 6.1 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 是全篇最关键的 prompt 工程技巧之一

核心文件：

- `src/constants/prompts.ts`
- `src/constants/systemPromptSections.ts`
- `src/utils/api.ts`
- `src/services/api/claude.ts`

Claude Code 明确把 system prompt 分成：

- 静态、可跨用户缓存的前缀
- 动态、按会话变化的尾部

`SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 就是这条边界线。

`splitSysPromptPrefix(...)` 会把：

- attribution header
- CLI prefix
- 边界前静态块
- 边界后动态块

拆成不同 cache scope。

这说明 Claude Code 不是“写 prompt”，而是在做“可缓存的 prompt 编译”。

## 6.2 很多 prompt 设计都服务于 cache 稳定性

典型例子：

- `AgentTool` 的 agent list 可以从 tool description 里移到 attachment，避免 agent 动态变化导致 tool-schema cache miss。
- MCP instructions 可以改成 delta attachment，避免晚连接的 MCP server 每次都打爆 prompt cache。
- `ToolSearch` 的 deferred tool announcement 也有同类 delta 化处理。

可以说，Claude Code 的 prompt 设计至少一半是在为“大规模缓存稳定性”服务。

---

## 7. 用户上下文和系统上下文其实是两条侧通道

## 7.1 `getUserContext()`：把 `CLAUDE.md` 当成 meta user message 注入

核心文件：`src/context.ts`

`getUserContext()` 默认会生成：

- `claudeMd`
- `currentDate`

然后通过 `prependUserContext(...)` 包成：

```text
<system-reminder>
As you answer the user's questions, you can use the following context:
# claudeMd
...
# currentDate
...
</system-reminder>
```

这是一种很聪明的做法：

- `CLAUDE.md` 不需要硬塞进主 system prompt。
- 它作为 meta user message 更接近“项目上下文”，而不是产品人格。

## 7.2 `getSystemContext()`：把 git status 等系统状态追加到 system prompt 尾部

默认会带：

- `gitStatus`
- 可选 `cacheBreaker`

这块和 `CLAUDE.md` 的区别是：

- `CLAUDE.md` 是项目规则。
- `git status` 是会话启动时刻的系统状态快照。

## 7.3 自定义 system prompt 会跳过一部分默认注入

`fetchSystemPromptParts(...)` 明确规定：

- 如果设置了 `customSystemPrompt`，默认 `getSystemPrompt()` 和 `getSystemContext()` 都会被跳过。

这意味着 `--system-prompt` 是真正的“覆盖”，不是“在默认 system prompt 前再插一段”。

---

## 8. 工具提示词系统：Claude Code 其实把工具当成“微 prompt”

## 8.1 这些 `prompt.ts` 不是注释，而是模型可见协议

工具 prompt 的本质是：

- 给模型解释这个工具是什么。
- 告诉模型什么时候用。
- 告诉模型什么时候不要用。
- 把一些软规则嵌进工具描述中。

所以工具 schema + description 在 Claude Code 里等价于一层细粒度行为控制。

## 8.2 文件工具：最强的约束在这里

代表文件：

- `src/tools/FileReadTool/prompt.ts`
- `src/tools/FileWriteTool/prompt.ts`
- `src/tools/FileEditTool/prompt.ts`

设计意图很明确：

### `Read`

- 强调绝对路径。
- 强调偏移/分页读取。
- 强调图片、PDF、ipynb 也是 Read 的职责。
- 特别强调“看截图也要用 Read”。

### `Write`

- 如果是已有文件，必须先 `Read`。
- 明确说“优先 Edit，Write 只用于新建或整文件重写”。
- 禁止主动创建 `*.md` / README，除非用户明确要求。

### `Edit`

- 也是必须先 `Read`。
- 强调不要把行号前缀带进 `old_string/new_string`。
- 强调 `old_string` 要尽可能小但足够唯一。
- 鼓励 `replace_all` 做批量替换。

这三者共同把“改文件”从自由文本行为变成了一个带前置条件的协议。

## 8.3 搜索与外部信息工具

代表文件：

- `src/tools/GlobTool/prompt.ts`
- `src/tools/GrepTool/prompt.ts`
- `src/tools/LSPTool/prompt.ts`
- `src/tools/WebSearchTool/prompt.ts`
- `src/tools/WebFetchTool/prompt.ts`

关键设计：

- `Grep` 明确禁止通过 Bash 去跑 `grep/rg`。
- `Glob/Grep` 都把 open-ended exploration 引流给 `Agent`。
- `WebSearch` 强制在最终回答里附 `Sources:`。
- `WebSearch` 还显式提醒“搜索最新资料时要用当前年份”。
- `WebFetch` 内部又分两层 prompt：
  - 主工具说明
  - 二级小模型内容提取 prompt

这里能看出 Claude Code 对“检索”和“执行”分工很清楚。

## 8.4 执行与协作工具

代表文件：

- `src/tools/BashTool/prompt.ts`
- `src/tools/PowerShellTool/prompt.ts`
- `src/tools/AgentTool/prompt.ts`
- `src/tools/TodoWriteTool/prompt.ts`
- `src/tools/Task*.ts`
- `src/tools/SendMessageTool/prompt.ts`
- `src/tools/AskUserQuestionTool/prompt.ts`
- `src/tools/SleepTool/prompt.ts`
- `src/tools/BriefTool/prompt.ts`

这些工具 prompt 的共同点是：它们不只是描述工具，还在定义“工作方法”。

### `Bash`

这几乎是一篇 mini policy：

- git 提交/PR 的安全流程
- sandbox 约束
- 背景任务使用方式
- 禁止 destructive git
- 使用 heredoc 写 commit/PR body

### `Agent`

这是 Claude Code 最像“多代理框架”的地方：

- 说明何时应该 fork，何时应该 fresh subagent。
- 强调 fork 继承上下文、不要窥探 fork 输出。
- 明确要求写 prompt 时不能偷懒，“不要把理解外包给 agent”。

### `TodoWrite` / `Task*`

这些 prompt 直接规定了任务管理哲学：

- 什么场景必须建任务
- 什么时候不应该建任务
- `in_progress` 的约束
- 任务必须即时更新，不许批量补账

### `AskUserQuestion`

它不是“随便问用户”，而是受 plan mode 协议约束：

- 不能用它代替 plan approval。
- 不能问“计划看起来怎么样”这种 UI 上用户看不到的问题。

### `Brief`

这是典型的产品态 prompt：

- 真正给用户看的消息要走 `SendUserMessage`。
- 普通文本很多时候只是 detail view，不保证用户会看。

这个工具 prompt 定义的是“可见性语义”，不只是功能。

## 8.5 扩展与配置类工具

代表文件：

- `src/tools/SkillTool/prompt.ts`
- `src/tools/ConfigTool/prompt.ts`
- `src/tools/ListMcpResourcesTool/prompt.ts`
- `src/tools/ReadMcpResourceTool/prompt.ts`

这里的共同设计是“把运行时能力显式化”：

- `SkillTool` 说明 slash command 本质上是 skill。
- `ConfigTool` 会把可配置项动态展开进 prompt。
- MCP resource 工具让“外部资源”也拥有模型可理解的接口说明。

## 8.6 这批 prompt 文件里有不少镜像和 stub

我在 `src/` 下统计到：

- `75` 个 `prompt/prompts.ts/txt` 文件
- 按内容去重后约 `61` 份

其中相当一部分是：

- `utils/src/...`
- `services/compact/src/...`
- `tools/AgentTool/built-in/src/...`
- `constants/src/...`

这些目录里的很多文件是反编译后的镜像或 type stub，不应该和主实现重复计入。

真正应该优先看的 canonical prompt 资产，集中在：

- `src/constants/prompts.ts`
- `src/tools/*/prompt.ts`
- `src/services/*/prompts.ts`
- `src/tools/AgentTool/built-in/*.ts`
- `src/commands/*.ts`

---

## 9. slash command 提示词：把高层工作流编译成 prompt 模板

## 9.1 `type: 'prompt'` 命令本质上就是 prompt asset

核心文件：

- `src/commands.ts`
- `src/commands/*.ts`
- `src/skills/loadSkillsDir.ts`
- `src/utils/plugins/loadPluginCommands.ts`

built-in prompt command 里比较典型的有：

- `/init`
- `/commit`
- `/commit-push-pr`
- `/review`
- `/statusline`
- `/init-verifiers`
- `/security-review`
- `/insights`

## 9.2 它们不是“快捷按钮”，而是整套任务脚本

### `/init`

`src/commands/init.ts` 里的 `NEW_INIT_PROMPT` 是一个超长工作流 prompt，明确拆成：

1. 先问用户要建什么
2. 启动 subagent 调研代码库
3. 补齐问答
4. 写 `CLAUDE.md`
5. 写 `CLAUDE.local.md`
6. 建 skill
7. 建 hook
8. 给优化建议

它实际上已经是“初始化专家 agent”的工作说明书。

### `/commit` 与 `/commit-push-pr`

它们的特点是：

- 通过 `executeShellCommandsInPrompt(...)` 先把 `git status/diff/log` 注入 prompt。
- 再给模型一套严格的 git safety protocol。
- 强制 heredoc 格式。

这些命令不是让模型自由发挥，而是把它包进一个很窄的执行框里。

### `/security-review`

这是最极端的工作流模板之一：

- 给出完整 diff
- 明确“只看新增安全问题”
- 给出大量 hard exclusion
- 甚至要求先子任务找漏洞，再子任务过滤假阳性

它本质上是一个专用 security-review agent，只是实现成 slash command prompt。

## 9.3 技能和插件进一步把这套机制泛化了

`loadSkillsDir.ts` 和 `loadPluginCommands.ts` 会把 Markdown 文件编译成 `Command`。

因此：

- 一个 `SKILL.md` 不只是文档，它本质上会变成 prompt。
- plugin skill 和本地 skill 最终都进入同一条 prompt command 总线。

这就是为什么 Claude Code 的扩展体系如此强：因为它扩展的不是 UI，而是 prompt 编译链。

## 9.4 shell 插值让命令 prompt 变成“半动态脚本”

`executeShellCommandsInPrompt(...)` 支持：

- ``!`command` ``
- `````! ... `````

即在 prompt 渲染阶段就执行 shell，把输出嵌进 prompt。

这个机制非常强：

- `/commit`、`/commit-push-pr` 可以把当前 git 状态直接注入。
- skill / plugin prompt 也可以做同样的事。

同时也很危险，所以：

- 会先做权限检查。
- MCP skill 被视为不可信，不允许执行这类 inline shell。

---

## 10. 子代理 system prompt：Claude Code 的“人格分裂层”

## 10.1 默认 agent prompt 很薄

`src/constants/prompts.ts` 里的 `DEFAULT_AGENT_PROMPT` 非常短：

- 完成任务
- 不要半拉子工程
- 最后给简明汇报

说明通用 agent 的“人格”大多还是来自共享环境和工具说明。

## 10.2 真正重要的是 built-in 专用 agent

### `Explore`

文件：`src/tools/AgentTool/built-in/exploreAgent.ts`

特点：

- 强只读。
- 鼓励高效并行搜索。
- 面向“快返回”的代码库探索。

### `Plan`

文件：`src/tools/AgentTool/built-in/planAgent.ts`

特点：

- 更强的 read-only 限制。
- 明确要求输出 implementation plan。
- 明确最终要列 critical files。

### `verification`

文件：`src/tools/AgentTool/built-in/verificationAgent.ts`

这是整个仓库里最狠的一段 prompt 之一：

- 明确把自己定义成“try to break it”，不是“确认它工作了”。
- 列出 verification avoidance 和 “first 80% seduction” 两个失败模式。
- 强制要求每个 check 都有 command/output/result 结构。
- 明确 PASS/FAIL/PARTIAL 的判定。

这个 prompt 非常像“对抗式验收代理”的系统规约。

### `claude-code-guide`

文件：`src/tools/AgentTool/built-in/claudeCodeGuideAgent.ts`

特点：

- 面向 Claude Code / Agent SDK / Claude API 文档答疑。
- 明确优先 fetch 官方 docs map，再 fetch 具体页面。
- 还能把用户当前技能、agent、MCP、settings 注入自己的 system prompt。

它本质上是一个“知识型检索代理”。

### `statusline-setup`

文件：`src/tools/AgentTool/built-in/statuslineSetup.ts`

特点：

- 把 shell PS1 到 Claude Code status line 的迁移规则写得很细。
- 这类 prompt 不是通用推理，而是非常垂直的产品流程脚本。

## 10.3 Agent 生成器本身也有自己的 meta prompt

文件：`src/components/agents/generateAgent.ts`

`AGENT_CREATION_SYSTEM_PROMPT` 的角色不是“执行任务”，而是“设计 agent”：

- 萃取核心 intent
- 设计 expert persona
- 写完整 system prompt
- 生成 `identifier/whenToUse/systemPrompt` JSON

这说明 Claude Code 连“创建新代理”本身都被做成了专门 prompt 工作流。

---

## 11. Memory 系统是主系统提示里最重的一块附加 prompt

这一章只保留 prompt 视角下的总览。若要专门看记忆层级、`KAIROS` daily log、`dream` consolidation、SessionMemory 与 agent memory 的关系，请继续看 [16-memory-system.md](./16-memory-system.md)。

## 11.1 auto-memory 不是附属功能，而是主 prompt 的一个 section

核心文件：

- `src/memdir/memdir.ts`
- `src/memdir/memoryTypes.ts`
- `src/memdir/teamMemPrompts.ts`

`loadMemoryPrompt()` 会把 memory 规则直接塞进主系统提示里。

这意味着 memory 不是“后台插件”，而是 Claude Code 的第一等行为约束。

## 11.2 它最重要的设计不是“记住”，而是“限制记什么”

`memoryTypes.ts` 明确规定四类 memory：

- `user`
- `feedback`
- `project`
- `reference`

同时又明确规定不能记：

- 代码结构
- file paths
- architecture
- git history
- debugging recipe
- 已经写进 `CLAUDE.md` 的内容
- 当前对话中的临时任务细节

这说明 Claude Code 的 memory 设计目标不是做“第二份项目文档”，而是存不可从仓库直接推导出的上下文。

## 11.3 它还专门处理了“记忆漂移”

典型规则：

- memory 可能过时，使用前要验证。
- memory 里提到函数/文件/flag 时，推荐前要先确认它现在还存在。
- 用户要求忽略 memory 时，要当作 `MEMORY.md` 为空，不能边忽略边引用。

这几条非常重要，因为它们是在防“历史提示词污染当前判断”。

## 11.4 team memory 把 prompt 从“个人记忆”升级成“组织记忆”

`teamMemPrompts.ts` 会引入：

- private memory
- team memory
- 不同 memory type 的 scope 规则
- shared memory 中不能存敏感信息

Claude Code 已经把 prompt 层设计扩展到了多人协作。

## 11.5 KAIROS 模式会切换成 daily log prompt

`memdir.ts` 里还有一套 daily-log 风格 prompt：

- 不是立即维护 `MEMORY.md`
- 而是往按日期命名的日志里 append
- 夜间 consolidation 再蒸馏成 index + topic files

这是一种完全不同的记忆写入策略。

## 11.6 Session Memory 是另一套“对当前会话做持久摘要”的 prompt

文件：`src/services/SessionMemory/prompts.ts`

它的关键特点：

- 针对当前 session notes 文件做结构化更新。
- 强制保持 section/header/italic description 不变。
- 明确排除 system prompt、CLAUDE.md、旧 session summary。
- 要求只用 `Edit`，而且可并行发多个 edit。

这更像“结构化笔记维护代理”。

## 11.7 extractMemories 是后台 memory 提取子代理的 prompt

文件：`src/services/extractMemories/prompts.ts`

特点：

- 只允许看最近若干消息。
- 明确说不要去 grep 代码、不要进一步验证。
- 给出两阶段策略：先并行读，再并行写。
- auto-only 和 auto+team 两套 prompt 分开。

这很像一个“受限写入 worker”。

## 11.8 `remember` skill 是 memory 体系上的人工审阅层

文件：`src/skills/bundled/remember.ts`

它不是直接修改 memory，而是：

- 对 auto-memory、`CLAUDE.md`、`CLAUDE.local.md` 做交叉审查
- 输出 promotion / cleanup / ambiguous / no-action-needed 报告

这代表 Claude Code 不只是自动写记忆，还给了用户一个“回收和整理旧提示”的入口。

---

## 12. compact、summary、title 这些二级 prompt 说明了什么

## 12.1 compact prompt 其实是“上下文编译器”

文件：`src/services/compact/prompt.ts`

几个关键特点：

- 最前面先加 `NO_TOOLS_PREAMBLE`，防止 compact 阶段浪费 turn 去调工具。
- 强制输出 `<analysis>` + `<summary>`。
- 结构化要求极强：
  - Primary Request and Intent
  - Key Technical Concepts
  - Files and Code Sections
  - Errors and fixes
  - Pending Tasks
  - Current Work
  - Optional Next Step

这说明 compact 不是“随便总结一下”，而是在做“可继续执行的上下文重编译”。

## 12.2 `awaySummary` 是为回到会话的用户写的

文件：`src/services/awaySummary.ts`

它的要求非常克制：

- 只写 1-3 句。
- 先说高层任务。
- 再说下一步。
- 不要写状态报告和 commit recap。

这是一种典型的产品型 prompt：极短，但用户场景非常明确。

## 12.3 `toolUseSummary` 是给移动端/时间线用的

文件：`src/services/toolUseSummary/toolUseSummaryGenerator.ts`

它要求：

- 只生成单行 label。
- 像 git commit subject。
- 动词用过去式。
- 30 字符左右会被截断。

所以它不是“总结”，而是“生成 UI 行标签”。

## 12.4 命名类 prompt 很小，但很产品化

相关文件：

- `src/utils/sessionTitle.ts`
- `src/commands/rename/generateSessionName.ts`
- `src/components/Feedback.tsx`

分别用于：

- session title
- kebab-case session name
- GitHub issue title

这类 prompt 有几个共同点：

- 都用小模型。
- 都强格式约束，常配 JSON schema。
- 目标不是开放生成，而是“短、稳、可直接展示/存储”。

---

## 13. 还有几类容易漏掉的隐藏 prompt

## 13.1 Web 工具内部的二级 prompt

### `WebSearchTool`

文件：`src/tools/WebSearchTool/WebSearchTool.ts`

它自己会起一次模型请求，并用一个极短 system prompt：

- “你是执行 web search tool use 的助手”

本质上是在用模型触发 server-side search tool。

### `WebFetch`

文件：`src/tools/WebFetchTool/utils.ts`

这里的 `makeSecondaryModelPrompt(...)` 会把网页 markdown 和用户提取要求拼给一个小模型。

它还内嵌了版权/引用限制：

- 非预批准域名严格限制 quote 长度
- 不要评价自己回答的合法性
- 不要输出歌词

## 13.2 Prompt Suggestion

文件：`src/services/PromptSuggestion/promptSuggestion.ts`

`SUGGESTION_PROMPT` 的定位很清楚：

- 预测“用户下一句会自然输入什么”
- 不是给建议，而是猜下一步用户意图
- 2-12 个词
- 不要 Claude 口吻
- 不明显就沉默

这块很能体现 Claude Code 已经在用 prompt 做“交互预测”。

## 13.3 自然语言日期解析

文件：`src/utils/mcp/dateTimeParser.ts`

这里不是手写 parser，而是把当前日期、时区、星期等上下文交给 Haiku，让模型返回 ISO 8601。

说明这套系统很乐意把“小而模糊的解析任务”交给次级 prompt。

## 13.4 shell prefix 分类器

文件：`src/utils/shell/prefix.ts`

这里用 Haiku 根据 policy spec 给 shell command 判 prefix。

这类 prompt 的价值不是文案，而是“把难写的启发式交给模型”。

## 13.5 hook prompt / hook agent

相关文件：

- `src/utils/hooks/execPromptHook.ts`
- `src/utils/hooks/execAgentHook.ts`
- `src/utils/hooks/apiQueryHookHelper.ts`

这里说明：

- hook 本身就可以是 prompt。
- 还能起 agent 级验证。
- 还支持强制 JSON schema 输出。

换句话说，Claude Code 连运行时自动化检查器也是 prompt-driven 的。

## 13.6 浏览器扩展与 companion 这种“产品边角 prompt”

相关文件：

- `src/utils/claudeInChrome/prompt.ts`
- `src/buddy/prompt.ts`

这两类 prompt 很容易被忽略，但都很有代表性。

### Claude in Chrome

`BASE_CHROME_PROMPT` 和相关 hint 会告诉模型：

- 先看当前 tab context，不要直接新开一堆页
- 避免触发 JS alert / confirm / prompt 这类会卡死扩展的对话框
- 遇到失败不要无限重试，2-3 次后该停就停
- 需要时录 GIF、读 console、处理 tab 生命周期

浏览器扩展不是“多一组 MCP 工具”，而是配了一整层专门的 browser-operation prompt。

### Buddy / Companion

`companionIntroText(...)` 会在特定模式下告诉主模型：

- 输入框旁边有一个 companion 气泡角色
- 用户直接叫 companion 名字时，主模型要少说甚至别插嘴
- 不要替 companion 代答

这类 prompt 规模很小，但它们清楚说明：Claude Code 连 UI 小组件之间的角色分工，也会用 prompt 显式建模。

---

## 14. 从这些 prompt 里能总结出哪些设计原则

## 14.1 分层，而不是堆叠

Claude Code 并没有把所有规则塞进一个超级 system prompt，而是分成：

- 主人格
- 环境信息
- 工具语义
- 工作流模板
- 专用 agent
- 二级任务 prompt

这样每层都更容易替换、缓存和调优。

## 14.2 把“软规则”下沉到离动作最近的地方

例如：

- “编辑前必须先读”不放在总 prompt，而放在 `Edit/Write` 工具 prompt。
- “web search 必须带 Sources”不放在全局，而放在 `WebSearch` 工具 prompt。
- “brief 模式下用户真正能看到什么”不放在全局，而放在 `Brief` 工具 prompt。

这比全局大而化之地提醒更可靠。

## 14.3 用 prompt 处理协议，而不是只处理语言

最典型的就是：

- `<system-reminder>`
- `<analysis>/<summary>`
- `VERDICT: PASS/FAIL/PARTIAL`
- `<updated_file>`
- JSON schema

Claude Code 反复把 prompt 设计成“弱结构化协议”。

## 14.4 大量 prompt 的真实目标是抑制 LLM 坏习惯

例如：

- 不要盲试
- 不要乱建文件
- 不要过度总结
- 不要虚报验证结果
- 不要把未理解的问题外包给 subagent
- 不要把 memory 当真理

这类指令的本质不是增加能力，而是减少偏航。

## 14.5 prompt 设计始终受 cache 成本约束

这一点在 Claude Code 里特别明显：

- static/dynamic boundary
- system prompt section cache
- tool description 静态化
- agent list / MCP instructions delta 化

换句话说，这套 prompt 设计从第一天起就是按“要规模化运行”来写的。

---

## 15. 这套提示词系统反映了怎样的 Claude Code 产品哲学

可以归纳成五句话：

1. **Claude Code 不是聊天产品，而是代理运行时。**
2. **prompt 不是文案，而是执行协议。**
3. **工具描述和工作流模板与 system prompt 同等重要。**
4. **memory、compact、summary、agent 都是 prompt 子系统，而不是附属功能。**
5. **几乎所有 prompt 设计都同时在回答两个问题：怎么让模型更稳，怎么让缓存更省。**

所以如果要真正理解 Claude Code，不能只看 `getSystemPrompt()`，必须把整条 prompt 编译链一起看。

---

## 16. 源码锚点索引

### 16.1 主系统提示与装配链

- `src/constants/prompts.ts`
- `src/constants/systemPromptSections.ts`
- `src/constants/system.ts`
- `src/context.ts`
- `src/utils/queryContext.ts`
- `src/query.ts`
- `src/QueryEngine.ts`
- `src/services/api/claude.ts`
- `src/utils/api.ts`

### 16.2 canonical 工具 prompt

- `src/tools/FileReadTool/prompt.ts`
- `src/tools/FileWriteTool/prompt.ts`
- `src/tools/FileEditTool/prompt.ts`
- `src/tools/BashTool/prompt.ts`
- `src/tools/GlobTool/prompt.ts`
- `src/tools/GrepTool/prompt.ts`
- `src/tools/LSPTool/prompt.ts`
- `src/tools/WebSearchTool/prompt.ts`
- `src/tools/WebFetchTool/prompt.ts`
- `src/tools/AgentTool/prompt.ts`
- `src/tools/TodoWriteTool/prompt.ts`
- `src/tools/TaskCreateTool/prompt.ts`
- `src/tools/TaskGetTool/prompt.ts`
- `src/tools/TaskListTool/prompt.ts`
- `src/tools/TaskUpdateTool/prompt.ts`
- `src/tools/TaskStopTool/prompt.ts`
- `src/tools/AskUserQuestionTool/prompt.ts`
- `src/tools/SleepTool/prompt.ts`
- `src/tools/BriefTool/prompt.ts`
- `src/tools/SkillTool/prompt.ts`
- `src/tools/ConfigTool/prompt.ts`
- `src/tools/SendMessageTool/prompt.ts`
- `src/tools/ListMcpResourcesTool/prompt.ts`
- `src/tools/ReadMcpResourceTool/prompt.ts`

### 16.3 命令模板

- `src/commands/init.ts`
- `src/commands/commit.ts`
- `src/commands/commit-push-pr.ts`
- `src/commands/review.ts`
- `src/commands/statusline.tsx`
- `src/commands/init-verifiers.ts`
- `src/commands/security-review.ts`

### 16.4 子代理与专用生成任务

- `src/tools/AgentTool/built-in/exploreAgent.ts`
- `src/tools/AgentTool/built-in/planAgent.ts`
- `src/tools/AgentTool/built-in/generalPurposeAgent.ts`
- `src/tools/AgentTool/built-in/verificationAgent.ts`
- `src/tools/AgentTool/built-in/claudeCodeGuideAgent.ts`
- `src/tools/AgentTool/built-in/statuslineSetup.ts`
- `src/components/agents/generateAgent.ts`

### 16.5 记忆、压缩、摘要与其他二级 prompt

- `src/memdir/memdir.ts`
- `src/memdir/memoryTypes.ts`
- `src/memdir/teamMemPrompts.ts`
- `src/tools/AgentTool/agentMemory.ts`
- `src/services/SessionMemory/prompts.ts`
- `src/services/extractMemories/prompts.ts`
- `src/services/MagicDocs/prompts.ts`
- `src/services/compact/prompt.ts`
- `src/services/autoDream/consolidationPrompt.ts`
- `src/services/toolUseSummary/toolUseSummaryGenerator.ts`
- `src/services/awaySummary.ts`
- `src/services/PromptSuggestion/promptSuggestion.ts`
- `src/utils/sessionTitle.ts`
- `src/commands/rename/generateSessionName.ts`
- `src/utils/mcp/dateTimeParser.ts`
- `src/utils/shell/prefix.ts`
- `src/utils/hooks/execPromptHook.ts`
- `src/utils/hooks/execAgentHook.ts`

## 17. 总结

Claude Code 的提示词系统将产品人格、工具协议、工作流模板、协作机制、记忆系统与缓存策略统一装配成一个可组合的 prompt runtime。
