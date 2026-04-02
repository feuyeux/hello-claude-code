# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此工作区工作时提供指导。

## Git 提交署名

每次提交代码时，必须在 commit message 末尾加上以下 co-author trailer：

```text
Co-authored-by: Claude <claude@anthropic.com>
```

## 工作区结构

```text
hello-claude-code/
├── claude-code/     # 反编译还原的 Claude Code CLI 源码
├── deep_dive/       # 当前唯一的统一成稿目录
├── deep_dive_cc/    # 历史分析文档 / 来源材料
├── deep_dive_cx/    # 历史分析文档 / 来源材料
├── deep_dive_gi/    # 历史分析文档 / 来源材料
└── doc/             # 其他文档
```

## 统一文档体系

当前分析文档以 `deep_dive/` 为准。

- `deep_dive/README.md` 是统一导航。
- `deep_dive_cc/`、`deep_dive_cx/`、`deep_dive_gi/` 保留为历史输入和参考材料。
- 如果任务没有明确点名旧目录，默认修改 `deep_dive/`。

## 文档写作规范

在 `deep_dive/` 下撰写或修改分析文档时，遵守以下规范：

- 全部使用中文。
- 采用成稿口吻，直接面对最终读者，不写成与编辑者对话。
- 同一机制只在一篇主文档中完整展开，其他篇章只保留引用。
- 文件命名使用两位序号 + kebab-case，例如 `10-mcp-system.md`、`20-bridge-system.md`。
- 流程图、时序图、结构图优先使用 Mermaid；只有 Mermaid 不适合时才使用 draw.io XML。
- 文档拆分、合并或重命名时，必须同步更新 `deep_dive/README.md` 与相关交叉引用。
- 如果任务明确要求编辑旧目录，则保留旧目录现有命名风格，不主动改制。

## 项目概述

`claude-code/` 是 Anthropic 官方 Claude Code CLI 的反编译 / 逆向还原版本，目标是复现其主要运行机制。

- 运行时：Bun `>= 1.3.11`
- 语言：TypeScript + TSX（React / Ink 终端 UI）
- 模块系统：ESM
- Monorepo：Bun workspaces，内部包位于 `packages/`

## 常用命令

在 `claude-code/` 目录下执行：

```bash
bun install
bun run dev
bun run build
bun run lint
bun run lint:fix
bun run format
bun test
```

## 关键代码路径

| 路径 | 职责 |
| --- | --- |
| `claude-code/src/entrypoints/cli.tsx` | 真正入口，注入 `feature()` polyfill 与全局变量 |
| `claude-code/src/main.tsx` | CLI 参数解析、模式选择与启动 |
| `claude-code/src/query.ts` | 请求主循环状态机 |
| `claude-code/src/QueryEngine.ts` | 会话编排与 headless 入口 |
| `claude-code/src/screens/REPL.tsx` | 交互式终端控制中心 |
| `claude-code/src/services/api/claude.ts` | provider 路由与 API 请求构造 |
| `claude-code/src/tools.ts` | 工具池装配器 |
| `claude-code/src/services/mcp/` | MCP 协议实现 |
| `claude-code/src/bridge/` | 远程桥接与会话控制 |
| `claude-code/src/state/` | AppState、store 与状态订阅 |

## 工作注意事项

- 不要试图一次性修复反编译导致的大量 tsc 错误。
- 所有 feature flag 在当前构建里都等价于 `false`，相关分支默认视为死代码。
- React Compiler 反编译样板如 `const $ = _c(N)` 是正常现象。
- `audio-capture-napi`、`image-processor-napi`、`modifiers-napi`、`url-handler-napi`、`@ant/*` 都是 stub。
- `src/*` 是仓库中合法的路径别名。

## 参考入口

统一阅读入口：`deep_dive/README.md`

高频专题：

- `deep_dive/01-architecture.md`
- `deep_dive/07-context-management.md`
- `deep_dive/10-mcp-system.md`
- `deep_dive/14-prompt-system.md`
- `deep_dive/15-memory-system.md`
- `deep_dive/21-agents-tasks-remote.md`
