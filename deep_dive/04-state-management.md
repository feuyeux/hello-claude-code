# Claude Code 的状态管理系统

## 1. 状态管理概述

本篇讨论 `AppState`、store、selector 与状态更新模式如何共同构成 Claude Code 的运行时状态底座。

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Store["AppStateStore"]
        A1["AppState<br/>全局唯一状态"]
        A2["createStore<br/>状态仓库"]
    end

    subgraph Subscribe["订阅层"]
        B1["React Components<br/>订阅状态变化"]
        B2["Selectors<br/>派生状态计算"]
    end

    subgraph Middleware["中间件层"]
        C1["onChangeAppState<br/>变更钩子"]
        C2["Persistence<br/>状态持久化"]
    end

    A1 --> A2 --> B1
    B1 --> B2
    B2 --> C1
    C1 --> C2
```

## 2. AppState 定义

**位置**: `src/state/AppStateStore.ts`

### 2.1 核心状态结构

```typescript
export type AppState = DeepImmutable<{
  // ── 设置 ────────────────────────────────────────────────────
  settings: SettingsJson                    // 用户设置
  verbose: boolean                          // 详细输出模式
  mainLoopModel: ModelSetting              // 主循环模型
  mainLoopModelForSession: ModelSetting    // 会话级模型覆盖

  // ── 视图状态 ────────────────────────────────────────────────
  statusLineText: string | undefined      // 状态栏文本
  expandedView: 'none' | 'tasks' | 'teammates'  // 扩展视图
  isBriefOnly: boolean                     // 简洁模式
  coordinatorTaskIndex: number            // 协调任务索引
  viewSelectionMode: 'none' | 'selecting-agent' | 'viewing-agent'

  // ── 工具权限 ────────────────────────────────────────────────
  toolPermissionContext: ToolPermissionContext

  // ── 任务系统 ────────────────────────────────────────────────
  tasks: TaskState[]

  // ── MCP ────────────────────────────────────────────────────
  mcp: {
    clients: MCPServerConnection[]
    commands: Command[]
    tools: Tools
    resources: Record<string, ServerResource[]>
    installationErrors: PluginError[]
  }

  // ── 桥接 ───────────────────────────────────────────────────
  replBridgeEnabled: boolean
  replBridgeExplicit: boolean
  replBridgeConnected: boolean
  replBridgeSessionActive: boolean
  replBridgeReconnecting: boolean
  replBridgeConnectUrl: string | undefined
  replBridgeSessionUrl: string | undefined
  replBridgeEnvironmentId: string | undefined

  // ── 特性 ────────────────────────────────────────────────────
  agent: string | undefined
  kairosEnabled: boolean                  // Assistant 模式
  remoteSessionUrl: string | undefined
  remoteConnectionStatus: 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
  remoteBackgroundTaskCount: number

  // ── 推测执行 ────────────────────────────────────────────────
  speculation: SpeculationState

  // ── 文件历史 ────────────────────────────────────────────────
  fileHistory: FileHistoryState

  // ── 归因 ───────────────────────────────────────────────────
  attribution: AttributionState

  // ── 主题 ───────────────────────────────────────────────────
  theme: ThemeName
  terminalTheme: TerminalTheme | undefined
}>
```

### 2.2 DeepImmutable 类型

```typescript
// 深度不可变类型
type DeepImmutable<T> = {
  readonly [K in keyof T]: T[K] extends object
    ? DeepImmutable<T[K]>
    : T[K]
}
```

## 3. Store 实现

**位置**: `src/state/store.ts`

### 3.1 Store 接口

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Interface["Store 接口"]
        A1["getState()"]
        A2["setState(updater)"]
        A3["subscribe(listener)"]
    end
```

### 3.2 Store 实现

```typescript
export function createStore<S>(initialState: S): Store<S> {
  let state = initialState
  const listeners = new Set<Listener>()

  return {
    getState(): S {
      return state
    },

    setState(updater: (prev: S) => S): void {
      const newState = updater(state)

      // 引用比较优化
      if (newState === state) {
        return
      }

      state = newState

      // 通知所有监听器
      for (const listener of listeners) {
        listener()
      }
    },

    subscribe(listener: Listener): Unsubscribe {
      listeners.add(listener)
      return () => listeners.delete(listener)
    }
  }
}
```

## 4. AppStateStore

**位置**: `src/state/AppStateStore.ts`

### 4.1 创建 Store

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["createAppStore()"] --> B["createStore<br/>AppState"]
    B --> C["appStore 实例"]
    C --> D["导出方法"]
    D --> E["getAppState"]
    D --> F["setAppState"]
    D --> G["subscribeAppState"]
```

### 4.2 初始状态

```typescript
const createInitialState = (): AppState => ({
  // 设置
  settings: getInitialSettings(),
  verbose: false,
  mainLoopModel: 'claude-sonnet-4-5',
  mainLoopModelForSession: 'claude-sonnet-4-5',

  // 视图
  expandedView: 'none',
  isBriefOnly: false,
  coordinatorTaskIndex: -1,
  viewSelectionMode: 'none',
  footerSelection: null,

  // 权限
  toolPermissionContext: getEmptyToolPermissionContext(),

  // 任务
  tasks: [],

  // MCP
  mcp: {
    clients: [],
    commands: [],
    tools: [],
    resources: {},
    installationErrors: [],
  },

  // 桥接
  replBridgeEnabled: false,
  replBridgeExplicit: false,
  replBridgeConnected: false,
  replBridgeSessionActive: false,
  replBridgeReconnecting: false,

  // 特性
  kairosEnabled: false,
  remoteConnectionStatus: 'disconnected',
  remoteBackgroundTaskCount: 0,

  // 推测
  speculation: IDLE_SPECULATION_STATE,

  // 文件历史
  fileHistory: createEmptyFileHistoryState(),

  // 归因
  attribution: createEmptyAttributionState(),
})
```

## 5. 状态选择器

**位置**: `src/state/selectors.ts`

### 5.1 选择器工厂

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["createSelector(selector)"] --> B{"state 变化?"}

    B -->|相同| C["返回缓存值"]
    B -->|不同| D["重新计算"]

    D --> E["返回新值"]
    C --> E
```

### 5.2 常用选择器

```typescript
// 任务选择器
export const selectTasks = (state: AppState) => state.tasks
export const selectTaskById = (state: AppState, id: string) =>
  state.tasks.find(t => t.id === id)

// MCP 选择器
export const selectMcpTools = (state: AppState) => state.mcp.tools
export const selectMcpClients = (state: AppState) => state.mcp.clients

// 桥接选择器
export const selectBridgeState = (state: AppState) => ({
  enabled: state.replBridgeEnabled,
  connected: state.replBridgeConnected,
  sessionActive: state.replBridgeSessionActive,
})

// 模型选择器
export const selectMainLoopModel = (state: AppState) =>
  state.mainLoopModel ?? state.settings.model
```

## 6. 状态变更处理

**位置**: `src/state/onChangeAppState.ts`

### 6.1 变更钩子

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Store as AppStateStore
    participant Handler as Handler

    Store->>Handler: 状态变化
    Handler->>Handler: 处理 prev -> next
    Handler-->>Store: 返回 unsubscribe
```

### 6.2 特定变更处理

```typescript
// 任务变更处理
export function onTasksChange(handler: (tasks: TaskState[]) => void): () => void {
  return onAppStateChange((prev, next) => {
    if (prev.tasks !== next.tasks) {
      handler(next.tasks)
    }
  })
}

// MCP 工具变更处理
export function onMcpToolsChange(handler: (tools: Tools) => void): () => void {
  return onAppStateChange((prev, next) => {
    if (prev.mcp.tools !== next.mcp.tools) {
      handler(next.mcp.tools)
    }
  })
}
```

## 7. 状态更新模式

### 7.1 不可变更新

```typescript
// 添加任务
setAppState(prev => ({
  ...prev,
  tasks: [...prev.tasks, newTask]
}))

// 更新任务
setAppState(prev => ({
  ...prev,
  tasks: prev.tasks.map(t =>
    t.id === taskId ? { ...t, status: 'running' } : t
  )
}))

// 删除任务
setAppState(prev => ({
  ...prev,
  tasks: prev.tasks.filter(t => t.id !== taskId)
}))
```

### 7.2 批量更新

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["setAppState(prev => ...)"] --> B["执行多个更新"]
    B --> C["合并为单一状态"]
    C --> D["触发一次监听"]
```

## 8. React 集成

### 8.1 Hook

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Component as React Component
    participant Store as AppStateStore
    participant Selector as Selector

    Component->>Selector: useAppState(selector)
    Selector->>Store: getState()
    Store-->>Selector: state
    Selector-->>Component: value

    Note over Component: 首次渲染

    Store->>Component: 状态变化
    Component->>Selector: 重新计算
    Selector-->>Component: 新值
```

## 9. 持久化

### 9.1 设置持久化

**位置**: `src/utils/settings/settings.ts`

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["loadSettings()"] --> B{"settings.json 存在?"}
    B -->|是| C["读取并解析"]
    B -->|否| D["返回默认设置"]

    C --> E["返回 SettingsJson"]
    D --> E
```

### 9.2 会话持久化

**位置**: `src/utils/sessionStorage.ts`

```typescript
interface SessionData {
  messages: Message[]
  taskState: TaskState[]
  // ...
}

// 保存会话
export async function saveSession(data: SessionData): Promise<void> {
  const sessionPath = getSessionPath()

  await writeFile(
    sessionPath,
    JSON.stringify(data),
    { mode: 'fsync' }
  )
}

// 恢复会话
export async function loadSession(): Promise<SessionData | null> {
  const sessionPath = getSessionPath()

  if (!existsSync(sessionPath)) {
    return null
  }

  const content = await readFile(sessionPath, 'utf-8')
  return JSON.parse(content)
}
```

## 10. 状态调试

### 10.1 状态快照

```typescript
// 获取状态快照用于调试
export function getStateSnapshot(): string {
  const state = appStore.getState()
  return JSON.stringify(state, null, 2)
}

// 状态变更日志
export function enableStateLogging(): void {
  appStore.subscribe(() => {
    const state = appStore.getState()
    console.debug('[State]', JSON.stringify(state, null, 2))
  })
}
```

## 11. 补充：关键实现细节

### 11.1 DeepImmutable 的实际效果

DeepImmutable<T> 是一个递归类型，将所有属性标记为 readonly，将所有数组标记为 ReadonlyArray。但这只是编译时约束——运行时没有任何 freeze 操作。这意味着如果有代码绕过 TypeScript 类型检查直接修改状态（比如通过 as any），不会有运行时错误。

### 11.2 setState 的引用比较优化

setState 内部使用严格相等（===）比较新旧状态。如果 updater 函数返回了与之前相同的引用，不会触发任何 subscriber 通知。这对性能至关重要——在 REPL 渲染循环中，每秒可能有数十次 setState 调用，但只有真正发生变化的才会触发 UI 重渲染。

### 11.3 状态持久化的选择性

不是所有状态都会持久化。持久化到 session transcript 的包括：messages、taskState、worktree 信息。但像 mcp.clients（连接对象）、replBridgeConnected（运行时状态）这些字段不会也不能持久化。恢复会话时，这些运行时状态需要重新初始化。

### 11.4 Selector 缓存策略

createSelector 使用简单的上一次结果缓存（not LRU）。如果输入引用不变，直接返回上次计算结果。这足够了，因为每个 selector 通常只被一个 useAppState hook 实例消费。

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
