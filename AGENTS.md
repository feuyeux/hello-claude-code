# AGENTS.md

This file provides guidance for agentic coding agents working in this repository.

## Project Overview

This repository contains a **reverse-engineered / decompiled** version of Anthropic's Claude Code CLI plus a large documentation set around the codebase.

- Runtime: Bun, requires `>= 1.3.11`
- Language: TypeScript + TSX
- UI: React + Ink terminal UI
- Module system: ESM (`"type": "module"`)
- Monorepo: Bun workspaces with internal packages in `packages/`

The codebase still has many decompilation artifacts and roughly `1341` TypeScript errors. These do **not** block the Bun runtime. Do not try to “clean up” all type errors as part of unrelated work.

## Workspace Layout

```text
hello-claude-code/
├── claude-code/     # Source tree of the reconstructed Claude Code CLI
├── deep_dive/       # Canonical integrated architecture / reverse-engineering docs
├── deep_dive_cc/    # Legacy/source analysis docs
├── deep_dive_cx/    # Legacy/source analysis docs
├── deep_dive_gi/    # Legacy/source analysis docs
└── doc/             # Other notes
```

## Documentation Guidance

Use `deep_dive/` as the default target for architecture and reverse-engineering documentation work unless the user explicitly asks for one of the legacy directories.

- `deep_dive/README.md` is the canonical index and reading map.
- `deep_dive_cc/`, `deep_dive_cx/`, and `deep_dive_gi/` are historical/source variants, not the default publication target.
- Write `deep_dive/` docs in Chinese, in a finished-reader voice. Do not write as if replying to the editor.
- Keep topic ownership unique. If two chapters cover the same mechanism, choose one primary chapter and cross-reference it from the others.
- In `deep_dive/`, use two-digit prefixes plus kebab-case names such as `07-context-management.md`.
- Use Mermaid for flowcharts, sequence diagrams, and simple system diagrams. Use draw.io XML only when Mermaid is not expressive enough.
- When adding, splitting, or moving a topic in `deep_dive/`, update `deep_dive/README.md` and any affected internal links in the same change.
- If you are explicitly asked to edit `deep_dive_cc/`, `deep_dive_cx/`, or `deep_dive_gi/`, preserve that directory's existing filename convention instead of renaming files opportunistically.

## Build / Lint / Test Commands

All code commands run in the `claude-code/` directory:

```bash
bun install
bun run dev
bun run build
bun run lint
bun run lint:fix
bun run format
bun test
bun run check:unused
```

### Running a Single Test

```bash
bun test src/path/to/testFile.test.ts
bun test --test-name-pattern "tool.*"
```

## Code Style Guidelines

### General Approach

This codebase uses Biome with a lenient configuration to accommodate decompiled code patterns. Follow existing patterns in each file instead of trying to normalize the entire repository.

### Formatting

- Formatter is disabled in `biome.json`
- Indentation: tabs
- Line width: `120`
- JavaScript / TypeScript quotes: double quotes

### TypeScript

- `strict` is off
- `skipLibCheck` is on
- Decompiled types like `unknown`, `never`, or `{}` are common and not automatically suspicious
- Path alias: `src/*` maps to `./src/*`

### React / Ink

- This is a terminal UI, not a browser app
- React Compiler output such as `const $ = _c(N)` is normal decompilation boilerplate

## Special Code Patterns

### Feature Flag System

All `feature("FLAG_NAME")` calls return `false` in this build. Any code only reachable behind feature flags is effectively dead code. Do not try to enable or “repair” feature-flag branches unless the user explicitly asks for that.

### Stub Packages

These packages are stubs and should not be “implemented” as part of routine work:

- `audio-capture-napi`
- `image-processor-napi`
- `modifiers-napi`
- `url-handler-napi`
- `@ant/*`

### Bundle API

`import { feature } from "bun:bundle"` works at build time. In dev mode, the polyfill in `src/entrypoints/cli.tsx` provides `feature()`.

## What Not To Fix

1. Decompiled TypeScript errors that do not affect runtime.
2. Dead feature-flag branches.
3. React Compiler memoization scaffolding.
4. Stub package behavior.

## File Organization

```text
claude-code/
├── src/
│   ├── entrypoints/   # CLI entry points
│   ├── commands/      # Slash commands
│   ├── components/    # React / Ink components
│   ├── screens/       # REPL and overlays
│   ├── services/      # API, MCP, compact, oauth, plugins
│   ├── state/         # AppState and store
│   ├── tools/         # Tool implementations
│   ├── ink/           # Custom Ink framework
│   ├── utils/         # Utilities
│   └── types/         # Type definitions
├── packages/
│   └── @ant/          # Stub packages
└── dist/              # Build output
```

## Git Commit Convention

When committing code, add this trailer:

```text
Co-authored-by: Claude <claude@anthropic.com>
```

## Architecture Summary

```text
CLI Entry -> commands/ -> QueryEngine -> query.ts -> tools.ts -> services/api/
                                                       ↓
                                             tools/ (BashTool, etc.)
```

- `src/main.tsx`: CLI definition and launch routing
- `src/query.ts`: main streaming query loop
- `src/QueryEngine.ts`: headless/session orchestrator
- `src/screens/REPL.tsx`: interactive terminal control center
- `src/services/api/claude.ts`: provider-specific API client
- `src/tools.ts`: tool pool assembly by permission context

For the integrated code-reading map, start with `deep_dive/README.md`.
