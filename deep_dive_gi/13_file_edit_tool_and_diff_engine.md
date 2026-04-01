# 13. 文件编辑工具与 Diff 引擎深度分析

`FileEditTool` 是 `claude-code` 中逻辑最复杂、安全性要求最高的工具。它不只是简单的字符串替换，而是一套集成了**状态校验、模糊匹配、样式保持和原子写入**的精密系统。

## 13.1. 核心工作流：Read-Modify-Write (RMW)

`FileEditTool` 遵循严格的“先读后改”原则，整个生命周期分为 **Validate（校验）** 和 **Call（执行）** 两个阶段。

### 13.1.1. 状态校验 (Staleness Check)
为了防止 AI 基于过时（Stale）的文件内容进行修改（例如在 AI 读取文件后，用户手动保存了更改），系统实现了双重校验：
1.  **读取存根检查**: 工具会检查 `readFileState` 缓存。如果 AI 之前没有调用过 `read_file`（或者只读了部分内容），校验将失败。
2.  **时间戳与内容比对**: 
    - 比较磁盘文件的 `mtime`（修改时间）与读取时的 `timestamp`。
    - 如果 `mtime` 不一致，系统会进行二次确认：如果文件是全量读取的，则比对当前磁盘内容与缓存内容。如果内容完全一致（可能是云同步或杀毒软件触发了时间戳更新但未改动内容），则允许继续；否则报错，强制要求 AI 重新读取。

### 13.1.2. 原子性保证
在 `call` 方法中，系统在读取文件内容到写入磁盘之间，严格限制异步操作（Avoid async operations），以最小化竞态条件（Race Condition）的风险，确保操作的准原子性。

## 13.2. 启发式匹配：`findActualString` 算法

AI 输出的 `old_string` 往往会因为引号风格（直引号 vs 弯引号）与源代码微小不符。`findActualString` 解决了这一顽疾：

```typescript
export function findActualString(fileContent: string, searchString: string): string | null {
  // 1. 尝试精确匹配
  if (fileContent.includes(searchString)) return searchString;

  // 2. 启发式匹配：引号标准化
  const normalizedSearch = normalizeQuotes(searchString); // 将弯引号转为直引号
  const normalizedFile = normalizeQuotes(fileContent);

  const searchIndex = normalizedFile.indexOf(normalizedSearch);
  if (searchIndex !== -1) {
    // 根据标准化后的索引，从原文件中截取原始字符串
    return fileContent.substring(searchIndex, searchIndex + searchString.length);
  }
  return null;
}
```

此外，系统还会进行 **脱敏逆转 (Desanitization)**：处理 Claude 模型特有的占位符（如 `<fnr>` 还原为 `<function_results>`），确保匹配成功。

## 13.3. 样式保持：`preserveQuoteStyle`

如果 `findActualString` 匹配到了使用弯引号（Curly Quotes）的原始文本，系统会通过 `preserveQuoteStyle` 自动调整 `new_string` 的风格，使修改后的代码与原文件保持排版一致。

-   **开启/闭合识别**: 通过 `isOpeningContext` 启发式判断：如果引号前是空格、换行或左括号，则视为左引号（“），否则视为右引号（”）。
-   **缩写处理**: 智能识别英语缩写（如 `don't`），在缩写中的单引号会被正确处理为右单弯引号（’）而非左弯引号。

## 13.4. 补丁生成与安全性增强

### 13.4.1. 冲突预防
在单次任务执行多个 Edit 时，`getPatchForEdits` 会检查当前的 `old_string` 是否包含在上一个 Edit 刚刚生成的 `new_string` 中。如果是，则抛出错误，防止 AI 产生逻辑混乱的嵌套修改。

### 13.4.2. 空白符处理
-   **自动裁剪**: 默认会对 `new_string` 进行结尾空白符裁剪（Markdown 文件除外），保持代码整洁。
-   **换行符保持**: 检测原文件的换行风格（LF 或 CRLF），并在写入时严格遵循。

### 13.4.3. 变更通知 (LSP & UI)
修改完成后，`FileEditTool` 会通过以下渠道发出通知：
-   **LSP Manager**: 调用 `changeFile` 和 `saveFile`，触发 IDE 级别的代码分析（如重新计算 TypeScript 的诊断信息）。
-   **VSCode SDK**: 如果在 VSCode 插件环境下运行，会触发原生的 Diff 视图更新。
-   **File History**: 触发 `fileHistoryTrackEdit`，记录原始内容的快照，支持 `/undo` 命令。

## 13.5. 总结

`FileEditTool` 的精髓在于它对“意图”的理解而非简单的字符映射。通过 `findActualString` 容忍输入误差，通过 `preserveQuoteStyle` 尊重原文件风格，再通过严格的 `Staleness Check` 确保安全。这使得 `claude-code` 能够像经验丰富的工程师一样，精准、优雅且安全地重构代码。
