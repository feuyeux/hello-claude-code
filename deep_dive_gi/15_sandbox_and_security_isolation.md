# 15. 沙盒与安全隔离机制深度分析

在 AI 辅助编程领域，安全是第一要务。`claude-code` 通过一套多层级的防御体系，确保在执行 AI 生成的代码或命令时，宿主机的安全性得到保障。本文将从代码实现层面深入分析其沙盒（Sandbox）与安全隔离机制。

## 15.1. 多层级防御架构

`claude-code` 的安全模型可以分为四个主要层级：

1.  **静态安全扫描 (Security Vetting)**：在命令执行前，通过 AST 和正则匹配识别危险模式。
2.  **动态权限管控 (Permission Flow)**：根据配置的权限模式（Mode）和规则（Rules）决定是否拦截或询问。
3.  **操作系统级沙盒 (OS-level Sandbox)**：利用 `bubblewrap` (Linux) 或 macOS 的 Log Monitor 机制实现文件系统和网络隔离。
4.  **后置清理与审计 (Post-execution Scrubbing)**：清理可能导致宿主机提权的痕迹（如恶意 Git 配置）。

## 15.2. 静态安全扫描：`bashSecurity.ts`

在 `src/tools/BashTool/bashSecurity.ts` 中，系统实现了极其严苛的命令审计。

### 15.2.1. 危险模式拦截

系统定义了一系列 `COMMAND_SUBSTITUTION_PATTERNS`，防止 AI 通过命令替换（Command Substitution）绕过审计：

```typescript
const COMMAND_SUBSTITUTION_PATTERNS = [
  { pattern: /<\(/, message: 'process substitution <()' },
  { pattern: /\$\(/, message: '$() command substitution' },
  { pattern: /`/, message: 'backtick execution' },
  // 甚至针对 Zsh 的特殊语法进行了拦截
  { pattern: /(?:^|[\s;&|])=[a-zA-Z_]/, message: 'Zsh equals expansion (=cmd)' },
];
```

### 15.2.2. AST 与 Tree-sitter 分析

为了应对复杂的混淆手段，系统不仅使用正则，还尝试使用 `tree-sitter` 进行语法树分析。`parseForSecurity` 函数会将原始命令解析为结构化的 `ParsedCommand`，从而能够精准识别复合命令（如 `cmd1 && cmd2`）中的每一个子项。

## 15.3. 沙盒适配器：`SandboxManager`

`src/utils/sandbox/sandbox-adapter.ts` 是连接 CLI 与底层的 `@anthropic-ai/sandbox-runtime` 的核心。

### 15.3.1. 动态配置生成

`convertToSandboxRuntimeConfig` 函数会将用户的 `settings.json` 转换为沙盒运行时所需的配置：

-   **写保护**：强制禁止写入 `.claude/settings.json`、`.claude/settings.local.json` 和 `.claude/skills`。
-   **路径解析**：支持 `//path`（绝对路径）和 `/path`（相对于设置文件的路径）的特殊转换。
-   **网络隔离**：基于 `WebFetchTool` 的规则动态生成允许访问的域名白名单。

### 15.3.2. Git 裸仓库逃逸防御 (Bare Git Repo Escape)

这是一个非常硬核的安全细节（修复了 `#29316`）。Git 在某些情况下会将包含 `HEAD`, `objects`, `refs` 的目录视为裸仓库。攻击者可以在沙盒内创建这些文件并植入恶意的 `.git/config`（如利用 `fsmonitor` 钩子），当沙盒退出后，宿主机的 Git 进程扫描到该目录时可能会触发恶意代码。

`claude-code` 的防御策略：
1.  **只读挂载**：如果这些文件已存在，则以只读模式（ro-bind）挂载到沙盒中。
2.  **强制擦除**：如果在沙盒运行期间这些文件被创建，`cleanupAfterCommand` 会调用 `scrubBareGitRepoFiles()` 强行删除它们：

```typescript
function scrubBareGitRepoFiles(): void {
  for (const p of bareGitRepoScrubPaths) {
    try {
      rmSync(p, { recursive: true }); // 在宿主机层面强行删除
    } catch { /* ... */ }
  }
}
```

## 15.4. 权限流转与拦截：`bashPermissions.ts`

`src/tools/BashTool/bashPermissions.ts` 处理复杂的权限判定逻辑。

### 15.4.1. 复合命令拆解

对于 `npm install && rm -rf /` 这样的复合命令，系统不会简单地将其视为一个整体，而是将其拆解为多个子命令分别校验。

```typescript
export const MAX_SUBCOMMANDS_FOR_SECURITY_CHECK = 50; // 防止 ReDoS 或性能陷阱
```

如果子命令过多，系统会自动降级为 `ask` 模式，要求用户手动确认，以防范潜在的逃逸手段。

### 15.4.2. 自动权限提升 (Auto-Allow if Sandboxed)

如果启用了 `sandbox.autoAllowBashIfSandboxed`，且命令在沙盒内运行，系统会适当放宽对只读命令（如 `ls`, `cat`, `grep`）的拦截，以提升用户体验，同时利用沙盒底层的 OS 隔离作为最终防线。

## 15.5. 超时与资源限制

为了防止 AI 执行死循环或高负载任务，`BashTool.tsx` 定义了严格的超时：

-   **默认超时**：由 `getDefaultTimeoutMs()` 控制，通常为几分钟。
-   **Assistant 阻塞预算**：`ASSISTANT_BLOCKING_BUDGET_MS = 15_000` (15秒)。在助手模式下，如果任务运行超过此时间，会自动转入后台执行，并通知用户。

## 15.6. 总结

`claude-code` 的安全机制并非单一的工具，而是一套**深度防御 (Defense in Depth)** 体系。它通过：
1.  **前端审计** 拦截低级攻击。
2.  **权限系统** 赋予用户最终控制权。
3.  **内核级沙盒** 提供强有力的隔离边界。
4.  **特定漏洞防御**（如 Git 逃逸）体现了其在安全性上的工程深度。

这种“怀疑一切（Zero Trust）”的设计理念，使得它在处理不可信的 AI 生成内容时，依然能保持宿主机的绝对安全。
