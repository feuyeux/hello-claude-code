# 17. 文件历史与回滚机制（File History & Rewind）深度分析

在 AI 辅助编程工具中，文件修改的安全性是核心诉求。`claude-code` 实现了一套极其稳健的本地文件历史管理系统，允许用户随时将代码库回退到对话序列中的任意一个历史节点。这不仅提供了“撤销”功能，更是 AI 实验和试错的安全边界。

## 17.1. 核心架构与数据结构

文件历史系统的核心逻辑位于 `claude-code/src/utils/fileHistory.ts`。它主要依赖三个关键的数据结构：

### 17.1.1. `FileHistoryBackup` (备份元数据)
描述单个文件在特定版本时的状态。
```typescript
export type FileHistoryBackup = {
  backupFileName: string | null // 备份文件的实际存储名称（如 hash@v1），null 表示文件不存在
  version: number               // 单调递增的版本号
  backupTime: Date              // 备份时间
}
```

### 17.1.2. `FileHistorySnapshot` (快照)
代表一次完整对话轮次（Message）对应的全局文件状态。
```typescript
export type FileHistorySnapshot = {
  messageId: UUID                               // 关联的对话 Message ID
  trackedFileBackups: Record<string, FileHistoryBackup> // 文件路径 -> 备份版本的映射
  timestamp: Date
}
```

### 17.1.3. `FileHistoryState` (全局状态)
维护在应用的全局状态（AppState）中。
```typescript
export type FileHistoryState = {
  snapshots: FileHistorySnapshot[] // 历史快照数组（受 MAX_SNAPSHOTS = 100 限制）
  trackedFiles: Set<string>        // 当前被追踪的文件路径集合（相对路径）
  snapshotSequence: number         // 递增序列号，用于 UI 触发刷新
}
```

## 17.2. 运行流程：写前拦截与快照提交

文件历史系统的工作分为“追踪”和“提交”两个阶段。

### 17.2.1. 写前拦截：`fileHistoryTrackEdit`
这是最关键的防御性逻辑。在 `FileEditTool` 或 `NotebookEditTool` 真正修改文件之前，必须先调用此函数。

1.  **确定追踪路径**: 将绝对路径转换为相对路径（以缩减存储体积）。
2.  **创建初始备份 (v1)**: 如果该文件是第一次被修改，系统会立即读取其当前磁盘内容，并创建 `v1` 版本的备份。
3.  **防止破坏**: `v1` 备份始终代表 AI 开始修改该文件之前的“原始状态”。
4.  **原子更新状态**: 将该备份记录插入当前最新的快照中。

### 17.2.2. 提交快照：`fileHistoryMakeSnapshot`
在用户提交输入或 AI 完成一轮任务后，系统会调用此函数来“固化”当前的文件状态。

1.  **扫描变动**: 遍历 `trackedFiles`。
2.  **增量备份**: 
    *   利用 `mtime` (修改时间) 和 `size` (大小) 作为快速检查。
    *   如果初步检查发现变动，则进行昂贵的“内容哈希”比较。
    *   如果确认内容已变动，则生成新版本备份（例如 `v2`, `v3`）。
3.  **引用继承**: 如果文件没变，新快照会直接引用旧快照中的 `FileHistoryBackup` 对象（浅拷贝），节省内存。
4.  **持久化记录**: 通过 `recordFileHistorySnapshot` 将元数据存入 `sessionStorage`，确保重启 Session 后仍能回滚。

## 17.3. 存储机制 (The Storage System)

备份文件并不存储在内存中，而是存储在用户的配置目录下：
`~/.claude/file-history/{sessionId}/{sha256(filePath).slice(0, 16)}@v{version}`

### 17.3.1. 性能优化
*   **Lazy mkdir**: 只有在真正需要写备份时才会创建目录。
*   **copyFile**: 使用原生的 `fs.promises.copyFile` 实现备份和恢复，避免将大文件读入 Node.js 的 V8 堆内存，从而防止 OOM（内存溢出）。
*   **Hard Links**: 在恢复 Session 或 Fork 子 Agent 时，使用 `fs.promises.link`（硬链接）而不是物理拷贝来同步备份文件，极大地提高了速度并节省了磁盘空间。

## 17.4. 回滚算法 (The Rewind Engine)

当用户在 UI 中选择一个历史 Message 并触发回退时，`fileHistoryRewind` 会执行以下逻辑：

1.  **定位快照**: 查找 `messageId` 对应的 `FileHistorySnapshot`。
2.  **应用状态 (`applySnapshot`)**:
    *   **情况 A：目标快照中有备份**: 调用 `restoreBackup`，用备份文件覆盖当前文件。
    *   **情况 B：备份记录为 `null`**: 说明在该历史节点，该文件尚不存在。系统会执行 `unlink` 删除当前文件。
    *   **情况 C：文件中途加入追踪**: 如果目标快照中没有该文件的记录，说明它是后来才被修改的，系统会寻找该文件最早的 `v1` 备份（即它被 AI 第一次触碰前的状态）并进行恢复。
3.  **VSCode 同步**: 调用 `notifyVscodeFileUpdated`，确保 VSCode 插件（如果已连接）能立即刷新 diff 视图。

## 17.5. 安全与局限性

*   **隔离性**: 快照只追踪被 AI 明确修改（通过 Tool）的文件。用户在外部编辑器中手动修改但未被 AI 读取/写入的文件，可能无法被完整捕获。
*   **容量限制**: 默认保留 100 个快照。超过限制后，最旧的快照会被丢弃。
*   **非交互性**: 回滚是一个纯异步的副作用操作。在 REPL 中，它会触发状态更新并重置对话流。

## 17.6. 总结

`claude-code` 的文件历史系统是一个微型的版本控制系统。它通过 `v1` 拦截机制确保了“绝对可撤销性”，并通过基于文件的物理拷贝确保了系统的健壮性。这种设计使得 `claude-code` 在处理复杂重构任务时，即便 AI 逻辑跑偏，用户也能通过 `/undo` 或 `/rewind` 瞬间恢复生产力。
