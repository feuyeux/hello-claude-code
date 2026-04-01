# Claude Code 源码分析：启动流程

## 1. 启动流程概览

Claude Code 的启动流程分为以下几个阶段：

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    subgraph Entry["1. 入口点执行"]
        A1["Bun 运行时加载<br/>main.tsx / ink.ts"]
    end

    subgraph Init["2. 初始化 init.ts"]
        A2["配置加载、环境变量<br/>网络设置、遥测初始化"]
    end

    subgraph State["3. 状态初始化"]
        A3["AppStateStore 创建<br/>引导状态加载"]
    end

    subgraph Commands["4. 命令加载"]
        A4["内置命令 + 技能目录<br/>+ 插件命令"]
    end

    subgraph MCP["5. MCP 连接"]
        A5["启动 MCP 服务器连接"]
    end

    subgraph UI["6. REPL 渲染"]
        A6["Ink UI 渲染<br/>事件监听启动"]
    end

    Entry --> Init --> State --> Commands --> MCP --> UI
```

## 2. 详细启动流程

### 2.1 入口点 (main.tsx / ink.ts)

Bun 运行时会首先加载入口文件：

```typescript
// ink.ts - React Ink 应用入口
import { render } from 'ink'
import React from 'react'
import { App } from './components/App.js'

const app = render(React.createElement(App, {
  // 初始 props
}))

// 监听退出事件
app.waitUntilExit()
```

### 2.2 初始化模块 (entrypoints/init.ts)

**位置**: `src/entrypoints/init.ts`

初始化函数 `init()` 执行以下操作：

```typescript
export const init = memoize(async (): Promise<void> => {
  // 1. 启用配置系统
  enableConfigs()

  // 2. 应用安全的环境变量
  applySafeConfigEnvironmentVariables()

  // 3. 应用 CA 证书
  applyExtraCACertsFromConfig()

  // 4. 设置优雅关闭
  setupGracefulShutdown()

  // 5. 初始化遥测
  void Promise.all([
    import('../services/analytics/firstPartyEventLogger.js'),
    import('../services/analytics/growthbook.js'),
  ]).then(([fp, gb]) => {
    fp.initialize1PEventLogging()
    gb.onGrowthBookRefresh(() => {...})
  })

  // 6. 填充 OAuth 信息
  void populateOAuthAccountInfoIfNeeded()

  // 7. JetBrains IDE 检测
  void initJetBrainsDetection()

  // 8. GitHub 仓库检测
  void detectCurrentRepository()

  // 9. 远程托管设置
  if (isEligibleForRemoteManagedSettings()) {
    initializeRemoteManagedSettingsLoadingPromise()
  }

  // 10. 策略限制
  if (isPolicyLimitsEligible()) {
    initializePolicyLimitsLoadingPromise()
  }

  // 11. 配置 mTLS
  configureGlobalMTLS()

  // 12. 配置全局代理
  configureGlobalAgents()

  // 13. 预连接 Anthropic API
  preconnectAnthropicApi()

  // 14. 上游代理 (CCR 模式)
  if (isEnvTruthy(process.env.CLAUDE_CODE_REMOTE)) {
    await initUpstreamProxy()
  }

  // 15. 设置 Windows Git Bash
  setShellIfWindows()
})
```

### 2.3 引导状态 (bootstrap/state.ts)

**位置**: `src/bootstrap/state.ts`

```typescript
// Session ID 管理
let sessionId: string | undefined

export function getSessionId(): string {
  if (!sessionId) {
    sessionId = generateSessionId()
  }
  return sessionId
}

// 会话持久化控制
let sessionPersistenceDisabled = false
export function isSessionPersistenceDisabled(): boolean {
  return sessionPersistenceDisabled
}

// 附加目录管理
let additionalDirectoriesForClaudeMd: string[] = []
export function getAdditionalDirectoriesForClaudeMd(): string[] {
  return additionalDirectoriesForClaudeMd
}
```

### 2.4 应用状态 (AppStateStore)

**位置**: `src/state/AppStateStore.ts`

创建全局应用状态：

```typescript
// 初始状态工厂函数
const createInitialState = (): AppState => ({
  // 设置
  settings: getInitialSettings(),
  verbose: false,
  mainLoopModel: 'claude-sonnet-4-5',
  mainLoopModelForSession: 'claude-sonnet-4-5',

  // 视图状态
  expandedView: 'none',
  isBriefOnly: false,
  coordinatorTaskIndex: -1,

  // 工具权限上下文
  toolPermissionContext: getEmptyToolPermissionContext(),

  // 任务状态
  tasks: [],

  // MCP 状态
  mcp: {
    clients: [],
    commands: [],
    tools: [],
    resources: {},
    installationErrors: [],
  },

  // 桥接状态
  replBridgeEnabled: false,
  replBridgeConnected: false,
  replBridgeSessionActive: false,
  replBridgeReconnecting: false,

  // ... 更多字段
})

// 创建 Store
const appStore = createStore(createInitialState)
```

### 2.5 命令加载 (commands.ts)

**位置**: `src/commands.ts`

```typescript
// 命令注册 - 使用 memoize 缓存
const COMMANDS = memoize((): Command[] => [
  // 内置命令
  addDir,
  advisor,
  agents,
  branch,
  btw,
  chrome,
  clear,
  // ... 100+ 命令
])

// 异步加载所有命令源
const loadAllCommands = memoize(async (cwd: string): Promise<Command[]> => {
  const [
    { skillDirCommands, pluginSkills, bundledSkills, builtinPluginSkills },
    pluginCommands,
    workflowCommands,
  ] = await Promise.all([
    getSkills(cwd),           // 技能目录
    getPluginCommands(),      // 插件命令
    getWorkflowCommands(),    // 工作流命令
  ])

  return [
    ...bundledSkills,         // 捆绑技能
    ...builtinPluginSkills,   // 内置插件技能
    ...skillDirCommands,      // 技能目录命令
    ...workflowCommands,      // 工作流命令
    ...pluginCommands,        // 插件命令
    ...pluginSkills,          // 插件技能
    ...COMMANDS(),            // 内置命令
  ]
})

// 获取可用命令
export async function getCommands(cwd: string): Promise<Command[]> {
  const allCommands = await loadAllCommands(cwd)

  // 按可用性过滤
  const baseCommands = allCommands.filter(
    _ => meetsAvailabilityRequirement(_) && isCommandEnabled(_)
  )

  // 动态技能处理
  const dynamicSkills = getDynamicSkills()
  // ... 合并动态技能
}
```

### 2.6 工具加载 (tools.ts)

**位置**: `src/tools.ts`

```typescript
// 所有基础工具
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    TaskOutputTool,
    BashTool,
    // 条件编译的工具
    ...(feature('MONITOR_TOOL') ? [MonitorTool] : []),
    ...(feature('WORKFLOW_SCRIPTS') ? [WorkflowTool] : []),
    ...(feature('HISTORY_SNIP') ? [SnipTool] : []),
    // ... 更多工具
  ]
}

// 工具过滤
export function getTools(tools: ToolPreset | string[]): Tools {
  if (tools === 'default') {
    return getAllBaseTools().filter(t => t.isEnabled())
  }
  // 按名称过滤
  return getAllBaseTools().filter(t => tools.includes(t.name))
}
```

### 2.7 MCP 连接

**位置**: `src/services/mcp/`

```typescript
// MCP 客户端初始化
async function initMCP() {
  // 1. 加载 MCP 配置
  const mcpConfig = loadMcpConfig()

  // 2. 启动每个配置的服务器
  for (const server of mcpConfig.servers) {
    const connection = await connectToMCPServer(server)

    // 3. 获取可用工具
    const tools = await connection.listTools()

    // 4. 注册到状态
    appStore.setState(prev => ({
      mcp: {
        ...prev.mcp,
        clients: [...prev.mcp.clients, connection],
        tools: [...prev.mcp.tools, ...tools],
      }
    }))
  }
}
```

### 2.8 REPL 渲染 (ink.ts)

**位置**: `src/ink.ts`

```typescript
import { render, Box, Text } from 'ink'
import React from 'react'
import { App } from './components/App.js'

export async function startREPL() {
  // 创建 React 元素
  const app = render(
    <Box flexDirection="column">
      <StatusBar />
      <MainContent />
      <PromptInput />
    </Box>
  )

  // 监听 Ctrl+C
  process.on('SIGINT', () => {
    handleInterrupt()
  })

  // 等待退出
  await app.waitUntilExit()
}
```

## 3. 启动时序图

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant User as 用户
    participant Bun as Bun 运行时
    participant Init as init.ts
    participant State as AppStateStore
    participant Commands as 命令系统
    participant Tools as 工具系统
    participant MCP as MCP
    participant UI as Ink UI

    Bun->>Init: 启动
    Init->>Init: enableConfigs()
    Init->>Init: applySafeConfigEnvironmentVariables()
    Init->>Init: setupGracefulShutdown()
    Init->>Init: initialize1PEventLogging()
    Init->>Init: configureGlobalMTLS()
    Init->>Init: preconnectAnthropicApi()

    Init->>State: createInitialState()
    State-->>Init: AppStateStore

    Init->>Commands: getCommands(cwd)
    Commands-->>Init: Command[]

    Init->>Tools: getAllBaseTools()
    Tools-->>Init: Tools[]

    Init->>MCP: loadMcpConfig()
    MCP-->>Init: MCPConfig

    Init->>UI: render(<App />)
    UI-->>User: 显示界面

    User->>UI: 输入命令
```

## 4. 关键初始化时间点

| 阶段 | 操作 | 重要性 |
|------|------|--------|
| init() | 配置系统启用 | 必须 |
| init() | 遥测初始化 | 分析 |
| init() | mTLS/代理配置 | 网络 |
| AppStateStore | 状态创建 | 必须 |
| getCommands() | 命令加载 | 必须 |
| getAllBaseTools() | 工具注册 | 必须 |
| MCP 连接 | 服务连接 | 可选 |
| Ink render() | UI 渲染 | 必须 |

## 5. 启动优化

Claude Code 使用以下优化策略：

### 5.1 懒加载

```typescript
// 遥测延迟加载
void Promise.all([
  import('../services/analytics/firstPartyEventLogger.js'),
  import('../services/analytics/growthbook.js'),
]).then(([fp, gb]) => {...})
```

### 5.2 Memoization

```typescript
const COMMANDS = memoize((): Command[] => [...])
const loadAllCommands = memoize(async (cwd) => [...])
```

### 5.3 条件编译

```typescript
// bun:bundle 特性开关
const proactive = feature('PROACTIVE') || feature('KAIROS')
  ? require('./commands/proactive.js').default
  : null
```

### 5.4 预连接

```typescript
// API 预连接
preconnectAnthropicApi()
```

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
