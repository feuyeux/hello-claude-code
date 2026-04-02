# GEMINI.md

本文件为 Gemini CLI 在此工作区工作时提供指导。

## Git 提交署名

每次提交代码时，必须指定作者为 Gemini，并在 commit message 末尾加上 co-author trailer。

```bash
git commit --author="Gemini <gemini@google.com>" -m "你的提交说明"
```

```text
Co-authored-by: Gemini <gemini@google.com>
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

- `deep_dive/README.md` 是统一导航和阅读入口。
- `deep_dive_cc/`、`deep_dive_cx/`、`deep_dive_gi/` 仍可作为历史材料参考，但默认不再作为新的成稿目标。
- 如果任务没有明确点名旧目录，优先修改 `deep_dive/`。

## 文档写作规范

在 `deep_dive/` 下撰写或修改分析文档时，遵守以下规范：

- 语言：全部使用中文。
- 口吻：直接面向最终读者，不写成与编辑者互动的过程记录。
- 结构：一个主题只在一篇主文档中完整展开，其他位置只保留摘要与引用。
- 文件命名：两位序号 + kebab-case，例如 `07-context-management.md`、`18-api-provider-retry-errors.md`。
- 配图：流程图、时序图、关系图优先使用 Mermaid；只有 Mermaid 明显不适合时才用 draw.io XML。
- 导航：新增、拆分或重组主题时，必须同步更新 `deep_dive/README.md` 和受影响的交叉引用。
- 旧目录：若用户明确要求编辑 `deep_dive_cc/`、`deep_dive_cx/`、`deep_dive_gi/`，保留该目录既有命名风格，不顺手重命名。

## 项目概述

`claude-code/` 是 Anthropic 官方 Claude Code CLI 的反编译 / 逆向还原版本。本质上是一套终端中的 Agent 运行时，而非普通聊天界面。

- 运行时：Bun `>= 1.3.11`
- 语言：TypeScript + TSX
- UI：React + Ink 终端 TUI
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

## 关键路径速查

| 路径 | 说明 |
| --- | --- |
| `claude-code/src/entrypoints/cli.tsx` | 入口 polyfill 与全局变量注入 |
| `claude-code/src/main.tsx` | Commander.js CLI 定义与模式分流 |
| `claude-code/src/query.ts` | 请求主循环状态机 |
| `claude-code/src/QueryEngine.ts` | Headless / SDK 会话编排器 |
| `claude-code/src/screens/REPL.tsx` | 交互式终端控制中心 |
| `claude-code/src/services/api/claude.ts` | API client 与 provider 适配层 |
| `claude-code/src/tools.ts` | 工具池装配入口 |
| `claude-code/src/Tool.ts` | Tool 协议与 `buildTool()` 工厂 |
| `claude-code/src/services/mcp/` | MCP client、transport、tool/resource/prompt 接入 |
| `claude-code/src/bridge/` | 远程桥接与会话控制 |
| `claude-code/src/state/` | AppState、store、selector 与状态更新 |

## 工作注意事项

- 不要顺手修复大批量 tsc 错误。反编译产生的类型问题不影响 Bun 运行时。
- 所有 `feature("...")` 调用在当前构建里都等价于 `false`，feature flag 分支默认视为死代码。
- React Compiler 反编译样板如 `const $ = _c(N)` 是正常输出。
- `audio-capture-napi`、`image-processor-napi`、`modifiers-napi`、`url-handler-napi`、`@ant/*` 都是 stub。
- `src/*` 路径别名是合法导入路径。

## 首选参考

优先从 [deep_dive/README.md](./deep_dive/README.md) 开始。

如果只需要抓主线，优先看：

1. `deep_dive/01-architecture.md`
2. `deep_dive/06-query-and-request.md`
3. `deep_dive/07-context-management.md`
4. `deep_dive/14-prompt-system.md`
5. `deep_dive/15-memory-system.md`

如果任务明确针对旧目录，再回到 `deep_dive_cc/`、`deep_dive_cx/`、`deep_dive_gi/` 定点修改。
