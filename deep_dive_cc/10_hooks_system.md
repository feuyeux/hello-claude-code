# Claude Code 源码分析：Hooks 系统

## 1. Hooks 系统概述

Hooks 系统允许用户在关键生命周期点注入自定义逻辑，实现扩展和定制。

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    subgraph Pre["Pre-Tools Hooks"]
        A1["PreToolUse"]
        A2["PreCommand"]
        A3["Precompact"]
        A4["PreMessage"]
    end

    subgraph Exec["Tool Execution"]
        B1["工具执行"]
    end

    subgraph Post["Post-Tools Hooks"]
        C1["PostToolUse"]
        C2["PostCommand"]
        C3["Postcompact"]
        C4["PostMessage"]
    end

    subgraph Sampling["Sampling Hooks"]
        D1["PreSampling"]
        D2["PostSampling"]
    end

    subgraph Stop["Stop Hooks"]
        E1["Stop"]
    end

    Pre --> Exec --> Post --> Sampling --> Stop
```

## 2. Hook 类型定义

**位置**: `src/types/hooks.ts`

### 2.1 核心 Hook 类型

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph HookConfig["HookConfig"]
        A1["name"]
        A2["timing"]
        A3["blocking"]
    end

    subgraph HookMatch["HookMatch"]
        B1["tool?"]
        B2["command?"]
        B3["file_path?"]
    end

    subgraph HookInput["HookInput"]
        C1["messages"]
        C2["tool?"]
        C3["cwd"]
        C4["env"]
    end

    subgraph HookResult["HookResult"]
        D1["allow"]
        D2["deny"]
        D3["modify"]
        D4["block"]
    end
```

### 2.2 Hook 阶段

```typescript
export type HookPhase =
  | 'pre_tool_use'
  | 'post_tool_use'
  | 'pre_command'
  | 'post_command'
  | 'pre_compact'
  | 'post_compact'
  | 'pre_sampling'
  | 'post_sampling'
  | 'pre_message'
  | 'post_message'
  | 'stop'
```

## 3. Hook 注册

**位置**: `src/utils/hooks/hookRegistry.ts`

### 3.1 Hook 配置格式

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["hooks.json"] --> B["HooksConfig"]

    B --> C["HookDefinition[]"]

    C --> D["when: HookMatch"]
    C --> E["then: HookAction"]

    D --> D1["tool?"]
    D --> D2["command?"]
    D --> D3["phase?"]

    E --> E1["deny?"]
    E --> E2["allow?"]
    E --> E3["modify?"]
    E --> E4["block?"]
```

### 3.2 Hook 注册表

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Load as loadHooks()
    participant Registry as HookRegistry
    participant Config as hooks.json

    Load->>Config: 读取配置
    Config-->>Load: hooks[]

    loop 每个 config
        Load->>Registry: register(config)
        Registry->>Registry: createHook()
        Registry->>Registry: 创建 matcher
        Registry->>Registry: 创建 handler
        Registry->>Registry: 添加到 Map
    end
```

## 4. PreToolUse Hook

### 4.1 执行流程

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["executePreToolUseHooks()"] --> B["获取匹配的 hooks"]

    B --> C{"按顺序执行"}

    C --> D["executeHook()"]

    D --> E{"结果?"}

    E -->|allow| F["继续下一个"]
    E -->|deny/block| G["返回结果"]

    F --> C
    G --> H["返回 deny/block"]
    C -->|完成| I["返回 allow"]
```

### 4.2 工具输入修改

```typescript
// Hook 配置示例
{
  "name": "force-git-readonly",
  "when": {
    "tool": ["Bash(git *)"]
  },
  "then": {
    "modify": {
      "input": {
        "command": "${input.command} --no-edit"
      }
    }
  }
}
```

## 5. PostToolUse Hook

### 5.1 执行流程

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Hooks as PostToolUse Hooks
    participant Tool as Tool Result

    Hooks->>Hooks: 获取匹配的 hooks
    loop 每个 hook
        Hooks->>Hooks: executeHook()
        alt behavior === 'modify'
            Hooks->>Hooks: 处理 append
            Hooks->>Hooks: 添加到 additionalMessages
        end
    end
    Hooks-->>Tool: 返回 result + messages
```

## 6. Stop Hooks

### 6.1 Stop Hook 类型

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["handleStopHooks()"] --> B["获取 stop hooks"]

    B --> C["按优先级排序"]

    C --> D{"遍历 hooks"}

    D --> E["shouldRunHook()?"]

    E -->|否| F["跳过"]
    E -->|是| G["executeStopHook()"]

    G --> H{"结果类型?"}

    H -->|blocking| I["preventContinuation = true"]
    H -->|action| J["添加到 nonBlockingActions"]

    I --> D
    J --> D
    F --> D

    D -->|完成| K["发送非阻塞通知"]
    K --> L["返回 StopHookResult"]
```

### 6.2 Stop Hook 条件

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["shouldRunHook()"] --> B{"file_path 条件?"}

    B -->|有| C["matchesModifiedPaths?"]
    B -->|无| D{"exit_code 条件?"}

    C -->|不匹配| E["返回 false"]
    C -->|匹配| D
    D -->|有| F["matchesLastExitCode?"]
    D -->|无| G["返回 true"]

    F -->|不匹配| E
    F -->|匹配| G
```

## 7. Sampling Hooks

### 7.1 PreSampling Hook

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant PreSample as PreSampling Hooks
    participant Params as SamplingParams

    PreSample->>Params: 获取 params
    loop 每个 hook
        PreSample->>PreSample: executeHook()
        alt behavior === 'modify'
            PreSample->>Params: 添加到 system
        end
    end
    PreSample-->>Params: 返回修改后的 params
```

### 7.2 PostSampling Hook

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant PostSample as PostSampling Hooks
    participant Response as AssistantMessage

    PostSample->>PostSample: 获取 hooks
    loop 每个 hook
        PostSample->>PostSample: executeHook()
    end
    Note over PostSample: 不修改返回值
```

## 8. Hook 错误处理

### 8.1 错误策略

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["executeHook()"] --> B{"执行中出错?"}

    B -->|否| C["返回结果"]
    B -->|是| D{"errorPolicy?"}

    D -->|fail_open| E["返回 allow"]
    D -->|fail_closed| F["返回 deny"]
    D -->|ignore| G["返回 allow"]
```

### 8.2 超时处理

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Hook as executeHook()
    participant Timer as Promise.race()

    Hook->>Timer: 启动
    Note over Timer: 5秒超时

    Timer->>Hook: timeout
    Hook->>Hook: 返回 allow
```

## 9. Hook 调试

### 9.1 调试模式

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["enableHookDebugging()"] --> B["registry.on()"]

    B --> C["hook_execute 事件"]

    C --> D["console.debug()"]
```

### 9.2 Hook 日志

```typescript
// 记录 hook 执行
logEvent('hook_executed', {
  hook_name: hook.name,
  hook_phase: phase,
  tool_name: input.tool?.name,
  behavior: result.behavior,
  duration_ms: duration,
})
```

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
