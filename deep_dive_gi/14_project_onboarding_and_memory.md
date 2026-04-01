# 14. 项目感知与记忆系统深度分析

`claude-code` 的核心优势之一在于其强大的“上下文连续性”。通过一套精密的项目感知（Onboarding）和多层级记忆（Memory）机制，它不仅能理解当前的指令，还能记住项目的全局规范、历史修改记录以及跨会话的交互上下文。

## 14.1. 项目感知与初始化流程

### 14.1.1. 状态监测 (`projectOnboardingState.ts`)
当用户在某个目录下启动 `claude` 时，系统会首先通过 `getSteps()` 函数评估项目的就绪程度：
- **工作区检查**: 检测目录是否为空。如果为空，建议用户克隆仓库或创建新应用。
- **指令文件检查**: 扫描是否存在 `CLAUDE.md`。这是项目规范的载体。
- **状态判定**: `isProjectOnboardingComplete()` 会根据上述检查结果返回项目是否已完成初始化。

### 14.1.2. 状态持久化
初始化状态存储在全局配置文件中（通常是 `~/.claude.json`）。
- **数据结构**: `ProjectConfig` 接口定义了 `hasCompletedProjectOnboarding` 和 `projectOnboardingSeenCount` 等字段。
- **存储路径**: 通过 `getProjectPathForConfig()` 计算项目的唯一标识（通常是 Git 根目录或绝对路径），并以此为键值在 `~/.claude.json` 中索引配置。

## 14.2. 多层级指令系统 (Memory Files)

`claude-code` 通过 `src/utils/claudemd.ts` 实现了一套类似 CSS 优先级的文件指令系统。

### 14.2.1. 指令层级与优先级
文件按以下顺序加载，后加载的规则具有更高优先级：
1.  **Managed (托管级)**: 全局强制规范，路径如 `/etc/claude-code/CLAUDE.md`。
2.  **User (用户全局级)**: 个人偏好，路径为 `~/.claude/CLAUDE.md`。
3.  **Project (项目级)**: 代码库自带规范，如 `CLAUDE.md` 或 `.claude/rules/*.md`。
4.  **Local (本地私有级)**: 针对当前项目但不提交到 Git 的个人规则 `CLAUDE.local.md`。
5.  **AutoMem (自动记忆)**: 系统根据历史会话自动沉淀的经验。

### 14.2.2. 高级特性
- **@include 指令**: 支持在 Markdown 中通过 `@path` 引入其他文件，系统会递归解析并拼接内容，最大深度为 5 层。
- **条件规则 (Conditional Rules)**: 支持在 `.claude/rules/*.md` 的 Frontmatter 中定义 `paths`。系统利用 `picomatch` 匹配当前操作的文件路径，实现“按需加载”规范。

## 14.3. 跨会话历史与转录记录 (Transcript)

为了保证对话的连贯性，`claude-code` 会将每一条消息持久化。

### 14.3.1. 存储结构 (`sessionStorage.ts`)
- **文件格式**: 采用 JSONL (JSON Lines) 格式，支持追加写，性能极佳。
- **存储位置**: `~/.claude/projects/{sanitizedPath}/{sessionId}.jsonl`。
- **消息链**: 每条消息条目都包含 `uuid` 和 `parentUuid`，形成一个完整的对话有向无环图 (DAG)，支持分支和恢复。

### 14.3.2. 自动压缩 (Compaction)
当会话过长导致 Token 消耗接近模型上限时，系统会触发 `Compaction`。它会总结之前的对话内容，设置 `SystemCompactBoundaryMessage`，并修剪历史记录以节省上下文空间。

## 14.4. 文件历史快照与检查点 (Checkpointing)

这是 `claude-code` 实现“撤销”和“重做”功能的核心。

### 14.4.1. 快照机制 (`fileHistory.ts`)
- **存储位置**: `~/.claude/file-history/{sessionId}/{hash}@v{version}`。
- **哈希算法**: 文件路径经过 SHA256 处理取前 16 位作为标识符。
- **追踪时机**: 在执行任何 `replace` 或 `write_file` 操作前，系统会调用 `fileHistoryTrackEdit` 保存文件的当前版本。

### 14.4.2. 回滚与对比
- **Rewind**: 用户可以通过 `/rewind` 命令让模型将文件系统恢复到特定的消息 ID 对应的状态。
- **Diff Stats**: 系统能实时计算当前状态与历史快照之间的差异（增删行数），用于 UI 展示。

## 14.5. 全局配置与安全并发

所有状态的持久化都依赖于 `src/utils/config.ts`：
- **原子写操作**: 使用 `.lock` 文件机制确保在多实例运行时配置不会损坏。
- **自动备份**: 每次保存配置前，系统都会在 `~/.claude/backups/` 下保留最近 5 个版本的备份。
- **损坏恢复**: 如果检测到 JSON 损坏，系统会自动尝试从最新的备份中恢复。

## 14.6. 总结

`claude-code` 的记忆系统是一个闭环：
1. **感知**: 启动时识别项目环境。
2. **约束**: 加载多级 `CLAUDE.md` 规范。
3. **记录**: 实时保存对话（JSONL）和文件快照（Backups）。
4. **演进**: 通过自动压缩和自动记忆不断优化上下文。

这种多维度的记忆模型使得 Claude 能够像一个长期驻场的高级工程师一样，不仅懂代码，更懂项目的业务背景和协作规范。
