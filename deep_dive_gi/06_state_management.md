# 06. 状态管理系统深度分析

`claude-code` 的状态管理系统是一个高度优化的“中心化存储 + 响应式更新”架构。它不仅支撑着复杂的终端 TUI 渲染（基于 Ink），还负责协调多进程任务、远程协作（Bridge）以及复杂的 AI 预测逻辑（Speculation）。

## 6.1. 核心存储架构：Custom Zustand-like Store

不同于常规 Web 开发中常用的 Redux 或 Zustand，`claude-code` 实现了一个轻量且框架无关的 `Store` 模式（位于 `src/state/store.ts`）。

### 6.1.1. Store 实现原理
`createStore` 提供了一个闭包环境来持有状态，并通过 `Set<Listener>` 管理订阅：

```typescript
// src/state/store.ts
export function createStore<T>(initialState: T, onChange?: OnChange<T>): Store<T> {
  let state = initialState
  const listeners = new Set<Listener>()

  return {
    getState: () => state,
    setState: (updater: (prev: T) => T) => {
      const prev = state
      const next = updater(prev)
      if (Object.is(next, prev)) return // 引用相等则跳过更新
      state = next
      onChange?.({ newState: next, oldState: prev }) // 触发外部副作用钩子
      for (const listener of listeners) listener()
    },
    subscribe: (listener: Listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}
```

**关键设计：**
- **Object.is 检查**：严格的引用一致性检查，确保只有在状态真正改变时才触发渲染。
- **框架无关**：Store 不依赖 React，可以在任何 Node.js 逻辑层（如 `QueryEngine`）中直接使用 `getState`/`setState`。

## 6.2. AppState：宏大的状态版图

`AppState`（定义于 `src/state/AppStateStore.ts`）是系统的单一真理来源。它使用了 `DeepImmutable` 类型约束，强制执行不可变更新模式。

### 6.2.1. 状态分片解析
`AppState` 包含以下核心领域：

1.  **任务引擎 (`tasks`)**：
    一个以 `taskId` 为键的字典，存储 `TaskState`。由于任务包含复杂的函数回调，它被排除在 `DeepImmutable` 之外。
2.  **权限与上下文 (`toolPermissionContext`)**：
    管理当前的权限模式（`default`, `plan`, `yolo`）和工具调用的审批状态。
3.  **MCP 与插件系统 (`mcp`, `plugins`)**：
    动态存储连接的 MCP 服务器、可用工具、资源以及插件的加载状态。
4.  **预测与超计划 (`speculation`, `ultraplan`)**：
    - `speculation`: 记录 AI 预执行的状态、已写入的临时文件和“节省的时间”。
    - `ultraplan`: 复杂的计划执行状态，支持跨会话的异步任务。
5.  **终端集成工具**：
    - `tungsten`: Tmux 会话与窗格状态。
    - `bagel`: 内置浏览器的 URL 和面板可见性。
    - `chicago`: Computer Use (屏幕截图、应用授权) 的会话状态。

## 6.3. React/Ink 的响应式链路

`AppState.tsx` 将 Store 桥接到 React 上下文中，利用 `useSyncExternalStore` 实现高效渲染。

### 6.3.1. Selector 模式
为了防止 TUI 在大型状态更新时产生闪烁或卡顿，系统极度依赖选择器：

```typescript
// src/state/AppState.tsx
export function useAppState<R>(selector: (state: AppState) => R): R {
  const store = useAppStore();
  const get = () => selector(store.getState());
  // 使用 React 18 的标准钩子订阅外部存储
  return useSyncExternalStore(store.subscribe, get, get);
}
```

**性能优化策略：**
- **精细化订阅**：组件只订阅最小必要的状态分片（如 `useAppState(s => s.statusLineText)`）。
- **稳定的 Updater**：`useSetAppState` 返回的引用在组件整个生命周期内保持不变，避免子组件不必要的重绘。

## 6.4. 状态变更的副作用：onChangeAppState

当状态发生改变时，`src/state/onChangeAppState.ts` 会捕获 diff 并触发持久化或外部通知。

### 6.4.1. 自动同步逻辑
- **配置持久化**：
  当 `verbose`、`mainLoopModel` 或 `expandedView` 改变时，系统会自动调用 `saveGlobalConfig` 将更改写入磁盘。
- **外部元数据同步 (CCR/SDK)**：
  权限模式（`PermissionMode`）的改变会触发 `notifySessionMetadataChanged`，这确保了 CLI 的状态能实时同步给 Claude.ai Web 端或开发者 SDK。
- **缓存清理**：
  当设置（`settings`）改变时，系统会自动清理 API Key 和云端凭证的缓存，确保新的配置立即生效。

## 6.5. 项目记忆与持久化

除了全局的 `AppState`，系统还通过专用的持久化层管理项目特定的记忆：

### 6.5.1. 项目入驻状态 (`projectOnboardingState.ts`)
记录用户是否已经完成了项目的初始化（如创建 `CLAUDE.md`）。这通过读取/写入项目根目录的配置来实现，并不完全依赖内存中的 `AppState`。

### 6.5.2. 文件历史与归因
- `fileHistory`: 维护文件的快照序列，支持“撤销”操作。
- `attribution`: 记录 AI 生成代码的归因信息。

## 6.6. 总结

`claude-code` 的状态管理展现了高性能 CLI 应用的最佳实践：
1.  **解耦**：核心逻辑不依赖 UI 框架。
2.  **高性能**：通过选择器和 `useSyncExternalStore` 极大地减少了终端渲染的开销。
3.  **健壮性**：严格的不可变类型（DeepImmutable）减少了竞态条件和难以追踪的 Bug。
4.  **同步性**：完善的 `onChange` 钩子确保了内存状态、磁盘配置与远程会话之间的强一致性。
