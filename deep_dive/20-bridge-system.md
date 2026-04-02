# Claude Code 的桥接系统

## 1. 桥接系统概述

本篇讨论远程桥接、会话同步、JWT 刷新与写入缓冲如何共同构成远程控制链路。

桥接直接建立在底层 transport 之上；网络通道与事件上传器的细节见 [19-transport-system.md](./19-transport-system.md)。

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Local["本地 CLI"]
        A1["REPL<br/>本地命令行"]
    end

    subgraph Bridge["Bridge 系统"]
        B1["HybridTransport<br/>WebSocket + HTTP"]
        B2["FlushGate<br/>写入缓冲"]
        B3["TokenRefreshScheduler<br/>JWT 刷新"]
    end

    subgraph Remote["远程服务器"]
        C1["Session Ingress"]
        C2["Bridge Endpoint"]
        C3["Worker JWT"]
    end

    subgraph Client["Remote Client"]
        D1["移动端/网页"]
    end

    A1 <--> B1
    B1 <-->|SSE/POST| C1
    D1 <-->|WebSocket| C1

    B2 --> B1
    B3 --> B1
```

## 2. 远程桥接核心

**位置**: `src/bridge/remoteBridgeCore.ts`

### 2.1 EnvLessBridge 初始化流程

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant CLI as Claude Code CLI
    participant API as Session API
    participant Bridge as Bridge Endpoint
    participant Transport as HybridTransport

    CLI->>API: POST /v1/code/sessions
    API-->>CLI: sessionId

    CLI->>Bridge: POST /bridge
    Bridge-->>CLI: worker_jwt, expires_in

    CLI->>Transport: createV2ReplTransport()
    Transport->>Transport: 创建 WebSocket + HTTP

    CLI->>Transport: transport.connect()
    Transport-->>CLI: 连接就绪

    Note over CLI: 启动 JWT 刷新调度器
```

### 2.2 凭证获取

```typescript
// 获取远程桥接凭证
async function fetchRemoteCredentials(
  sessionId: string,
  baseUrl: string,
  accessToken: string,
  timeoutMs: number,
): Promise<RemoteCredentials | null> {
  const response = await axios.post(
    `${baseUrl}/bridge`,
    { session_id: sessionId },
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'anthropic-version': ANTHROPIC_VERSION,
      },
      timeout: timeoutMs,
    }
  )

  return {
    worker_jwt: response.data.worker_jwt,
    expires_in: response.data.expires_in,
    api_base_url: response.data.api_base_url,
    worker_epoch: response.data.worker_epoch,
  }
}
```

## 3. 传输层实现

### 3.1 HybridTransport

**位置**: `src/cli/transports/HybridTransport.ts`

混合传输：WebSocket 用于读取，HTTP POST 用于写入。

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["write(stream_event)"] --> B["缓冲队列<br/>100ms 定时器"]
    A1["write(other)"] --> C["立即 flush"]

    B -->|定时触发| D["SerialBatchEventUploader"]
    C --> D

    D -->|批量| E["POST /events"]
    D -->|重试| D

    E -->|成功| F["继续"]
    E -->|429/5xx| D
    E -->|4xx| G["丢弃"]
```

### 3.2 SerialBatchEventUploader

**位置**: `src/cli/transports/SerialBatchEventUploader.ts`

串行批量上传器：

```typescript
export class SerialBatchEventUploader<T> {
  private queue: T[][] = []
  private inFlight: boolean = false

  constructor(private config: {
    maxBatchSize: number
    maxQueueSize: number
    baseDelayMs: number
    maxDelayMs: number
    maxConsecutiveFailures?: number
    send: (batch: T[]) => Promise<void>
  }) {}

  async enqueue(items: T[]): Promise<void> {
    // 背压检查
    if (this.queueLength > this.config.maxQueueSize) {
      await this.drain()
    }

    this.queue.push(items)
  }

  async flush(): Promise<void> {
    while (this.queue.length > 0) {
      const batch = this.queue.shift()!
      await this.sendWithRetry(batch)
    }
  }
}
```

## 4. 消息处理

### 4.1 入口消息处理

**位置**: `src/bridge/bridgeMessaging.ts`

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["SSE/WebSocket 消息"] --> B{"消息类型?"}

    B -->|user| C["onInboundMessage"]
    B -->|control_request| D{"子类型?"}
    B -->|control_response| E["onPermissionResponse"]
    B -->|control_cancel| F["处理取消"]

    D -->|can_use_tool| G["权限请求"]
    D -->|其他| H["控制请求"]

    C --> I["去重检查"]
    G --> I
    H --> I
```

### 4.2 服务器控制请求

```typescript
export async function handleServerControlRequest(
  req: SDKControlRequest,
  handlers: {
    transport: ReplBridgeTransport
    sessionId: string
    onInterrupt?: () => void
    onSetModel?: (model: string) => void
    onSetMaxThinkingTokens?: (tokens: number | null) => void
    onSetPermissionMode?: (mode: PermissionMode) => {...}
  }
): Promise<void> {

  switch (req.request.subtype) {
    case 'interrupt':
      handlers.onInterrupt?.()
      break

    case 'set_model':
      handlers.onSetModel?.(req.request.model)
      break

    case 'set_permission_mode':
      handlers.onSetPermissionMode?.(req.request.mode)
      break

    case 'update_max_thinking_tokens':
      handlers.onSetMaxThinkingTokens?.(req.request.max_tokens)
      break
  }
}
```

## 5. JWT 刷新机制

### 5.1 Token 刷新调度

**位置**: `src/bridge/jwtUtils.ts`

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Scheduler as TokenRefreshScheduler
    participant Auth as Auth Server
    participant Transport as Transport

    Note over Scheduler: 启动时设置定时器
    Note over Scheduler: expiresIn - refreshBufferMs 后触发

    Scheduler->>Auth: 获取新 OAuth Token
    Auth-->>Scheduler: oauthToken

    Scheduler->>Transport: rebuildTransport(fresh)
    Transport->>Transport: 关闭旧连接
    Transport->>Transport: 创建新连接
    Transport-->>Scheduler: 完成

    Note over Scheduler: 重新调度下一次刷新
```

### 5.2 认证失败恢复

```typescript
async function recoverFromAuthFailure(): Promise<void> {
  authRecoveryInFlight = true
  onStateChange?.('reconnecting', 'JWT expired — refreshing')

  try {
    // 刷新 OAuth token
    const stale = getAccessToken()
    if (onAuth401) await onAuth401(stale ?? '')

    const oauthToken = getAccessToken() ?? stale
    if (!oauthToken) {
      onStateChange?.('failed', 'JWT refresh failed: no OAuth token')
      return
    }

    // 获取新凭证
    const fresh = await fetchRemoteCredentials(
      sessionId,
      baseUrl,
      oauthToken,
      cfg.http_timeout_ms,
    )

    // 重建传输
    await rebuildTransport(fresh, 'auth_401_recovery')
  } finally {
    authRecoveryInFlight = false
  }
}
```

## 6. 传输重建

### 6.1 重建流程

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["JWT 刷新/401 错误"] --> B["flushGate.start()"]

    B --> C["暂停写入"]
    C --> D["获取当前序列号"]

    D --> E["关闭旧传输"]
    E --> F["创建新传输"]

    F --> G["重新连接回调"]
    G --> H["transport.connect()"]

    H --> I["刷新缓冲队列"]
    I --> J["flushGate.drop()"]
```

### 6.2 FlushGate

**位置**: `src/bridge/flushGate.ts`

在传输重建期间缓冲写入：

```typescript
export class FlushGate<T> {
  private queue: T[] = []
  private active: boolean = false

  start() {
    this.active = true
  }

  enqueue(...items: T[]): boolean {
    if (!this.active) return false  // 不在门内，直接发送

    this.queue.push(...items)
    return true  // 已入队
  }

  end(): T[] {
    this.active = false
    const items = this.queue
    this.queue = []
    return items
  }

  drop() {
    this.active = false
    this.queue = []
  }
}
```

## 7. 桥接状态

### 7.1 状态定义

```typescript
export type BridgeState =
  | 'idle'           // 初始状态
  | 'ready'          // 凭证获取完成
  | 'connected'      // 传输已连接
  | 'reconnecting'   // 重连中
  | 'failed'         // 失败
```

### 7.2 状态转换

```mermaid
---
config:
  theme: neutral
---
stateDiagram-v2
    [*] --> idle: 启动
    idle --> ready: createCodeSession
    ready --> connected: transport.connect()
    connected --> reconnecting: JWT refresh / 401
    reconnecting --> connected: 成功
    reconnecting --> failed: 失败
    connected --> [*]: 关闭
    failed --> [*]: 关闭
```

## 8. 历史记录同步

### 8.1 历史记录上传

```typescript
async function flushHistory(msgs: Message[]): Promise<void> {
  // 过滤可上传的消息
  const eligible = msgs.filter(isEligibleBridgeMessage)

  // 限制大小
  const capped = eligible.length > initialHistoryCap
    ? eligible.slice(-initialHistoryCap)
    : eligible

  const events = toSDKMessages(capped).map(m => ({
    ...m,
    session_id: sessionId,
  }))

  // 发送
  await transport.writeBatch(events)
}
```

### 8.2 消息去重

```typescript
// 最近发送的 UUID (用于识别服务器回显)
const recentPostedUUIDs = new BoundedUUIDSet(cfg.uuid_dedup_buffer_size)

// 最近接收的 UUID (用于识别重复消息)
const recentInboundUUIDs = new BoundedUUIDSet(cfg.uuid_dedup_buffer_size)

function writeMessages(messages: Message[]) {
  const filtered = messages.filter(m =>
    isEligibleBridgeMessage(m) &&
    !initialMessageUUIDs.has(m.uuid) &&
    !recentPostedUUIDs.has(m.uuid)
  )

  // 添加到已发送
  for (const msg of filtered) {
    recentPostedUUIDs.add(msg.uuid)
  }

  // 发送
  transport.writeBatch(filtered)
}
```

## 9. 会话归档

### 9.1 关闭时归档

```typescript
async function teardown(): Promise<void> {
  tornDown = true
  refresh.cancelAll()

  // 发送空闲状态
  transport.reportState('idle')
  void transport.write(makeResultMessage(sessionId))

  // 归档会话
  let status = await archiveSession(
    sessionId,
    baseUrl,
    token,
    orgUUID,
    cfg.teardown_archive_timeout_ms,
  )

  // 关闭传输
  transport.close()
}
```

## 11. 补充：关键实现细节

### 11.1 Worker Epoch 语义

worker_epoch 是 Bridge 会话的版本号。当远程服务器重启或发生故障转移时，epoch 会递增。客户端收到新的 epoch 后必须重建传输层，因为旧的 WebSocket 连接已经失效。这是一个幂等性保证机制——即使客户端收到多次相同的 epoch，也不会重复重建。

### 11.2 并发消息处理

Bridge 使用 BoundedUUIDSet 做消息去重，分别维护 sent 和 received 两个集合。集合大小有上限，超过后自动驱逐最旧的条目。这意味着在极端情况下（非常长的会话），理论上可能出现重复消息。但实际上 UUID 冲突的概率极低。

### 11.3 WebSocket 心跳

HybridTransport 继承自 WebSocketTransport，后者实现了基于 ping/pong 帧的心跳机制。心跳间隔和超时由服务端配置控制。心跳失败会触发重连流程。

### 11.4 重连退避策略

WebSocket 重连使用指数退避：1 秒起步，最大 30 秒，每次失败翻倍。成功连接后重置计数器。重连期间通过 FlushGate 缓冲所有写操作，防止消息丢失。

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
