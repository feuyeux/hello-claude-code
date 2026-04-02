# Codex 工作指南

本文件为 OpenAI Codex 在此工作区工作时提供指导。

## Git 提交署名

每次提交代码时，必须在 commit message 末尾加上以下 co-author trailer：

```text
Co-authored-by: Codex <codex@openai.com>
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

## 文档工作规则

如果任务涉及源码分析、架构解读、文档重组或专题补写，默认以 `deep_dive/` 为目标目录。

- `deep_dive/README.md` 是统一导航和阅读入口。
- `deep_dive_cc/`、`deep_dive_cx/`、`deep_dive_gi/` 是历史材料，不再是默认成稿位置。
- `deep_dive/` 一律使用中文成稿口吻，直接面向最终读者。
- 不保留“先校准”“这里提醒一下”“下面回答你的问题”这类编辑痕迹。
- 同一个主题只能有一篇主文档完整展开；其他篇章只做摘要与引用。
- 文件命名统一为两位序号 + kebab-case，例如 `06-query-and-request.md`。
- 新增、拆分、合并专题时，必须同步更新 `deep_dive/README.md` 与相关交叉引用。
- 如果用户明确要求修改旧目录，则保留旧目录既有命名规范，不主动整体迁移。

## 项目概述

`claude-code/` 是 Anthropic 官方 Claude Code CLI 的反编译 / 逆向还原版本。本质上是一套终端中的 Agent 运行时：UI、命令、工具、权限、上下文治理、远程会话、多代理都围绕同一个 query 主循环组织起来。

- 运行时：Bun `>= 1.3.11`
- 语言：TypeScript + TSX
- UI：React + Ink
- 模块系统：ESM + Bun workspaces

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

| 路径 | 说明 |
| --- | --- |
| `claude-code/src/entrypoints/cli.tsx` | 入口 polyfill、全局变量注入 |
| `claude-code/src/main.tsx` | Commander.js CLI 定义与模式分流 |
| `claude-code/src/query.ts` | 请求主循环状态机 |
| `claude-code/src/QueryEngine.ts` | Headless / SDK 会话编排器 |
| `claude-code/src/screens/REPL.tsx` | 交互式终端控制中心 |
| `claude-code/src/tools.ts` | 工具池装配入口 |
| `claude-code/src/Tool.ts` | Tool 协议与工厂 |
| `claude-code/src/services/api/claude.ts` | provider 路由、请求构造、重试与错误翻译 |
| `claude-code/src/services/mcp/` | MCP 协议栈 |
| `claude-code/src/bridge/` | 远程桥接与会话同步 |
| `claude-code/src/state/` | AppState、store、selector 与订阅 |

## 工作注意事项

- 不要顺手修复大批量 tsc 错误；它们主要来自反编译。
- 所有 feature flag 在当前构建里都等价于 `false`。
- React Compiler 反编译样板如 `const $ = _c(N)` 是正常输出。
- `audio-capture-napi`、`image-processor-napi`、`modifiers-napi`、`url-handler-napi`、`@ant/*` 都是 stub。
- `src/*` 路径别名是合法导入方式。

## 推荐入口

统一阅读入口：`deep_dive/README.md`

高频专题：

1. `deep_dive/01-architecture.md`
2. `deep_dive/06-query-and-request.md`
3. `deep_dive/07-context-management.md`
4. `deep_dive/08-tools-and-permissions.md`
5. `deep_dive/10-mcp-system.md`
6. `deep_dive/14-prompt-system.md`
7. `deep_dive/15-memory-system.md`
8. `deep_dive/21-agents-tasks-remote.md`
