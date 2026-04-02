# Claude Code 的传输系统

## 1. 传输系统概述

本篇讨论 WebSocket、SSE、HybridTransport 与批量上传器如何构成 Claude Code 的网络传输层。

如果要继续看这层能力如何被组织成远程桥接与会话控制，请继续看 [20-bridge-system.md](./20-bridge-system.md)。

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Interface["Transport 接口"]
        A1["connect()"]
        A2["write(message)"]
        A3["writeBatch()"]
        A4["close()"]
        A5["setOnConnect()"]
        A6["setOnData()"]
    end

    subgraph Implementations["传输实现"]
        B1["HybridTransport"]
        B2["WebSocketTransport"]
        B3["SSETransport"]
    end

    subgraph Uploader["批量上传器"]
        C1["SerialBatchEventUploader"]
    end

    Interface <--> Implementations
    B1 --> C1
```

## 2. 传输接口定义

**位置**: `src/cli/transports/transport.ts`

```typescript
export interface Transport {
  // 连接管理
  connect(): void
  close(): void

  // 写入
  write(message: StdoutMessage): Promise<void>
  writeBatch(messages: StdoutMessage[]): Promise<void>

  // 回调设置
  setOnConnect(handler: () => void): void
  setOnData(handler: (data: string) => void): void
  setOnClose(handler: (code?: number) => void): void
  setOnError(handler: (error: Error) => void): void

  // 状态
  getLastSequenceNum(): number
  reportState(state: 'idle' | 'running' | 'requires_action'): void
}
```

## 3. WebSocket 传输

**位置**: `src/cli/transports/WebSocketTransport.ts`

### 3.1 基本实现

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["connect()"] --> B["刷新 Headers"]
    B --> C["创建 WebSocket"]
    C --> D{"连接成功?"}

    D -->|是| E["重置重试计数"]
    D -->|否| F["触发重连"]

    E --> G["flushQueue()"]
    G --> H["发送队列消息"]

    F --> H
```

### 3.2 重连机制

```typescript
private handleReconnect(): void {
  if (this.reconnectAttempts >= this.options?.maxReconnectAttempts ?? 5) {
    this.onClose?.(1006)  // 异常关闭
    return
  }

  // 指数退避
  const delay = Math.min(
    1000 * 2 ** this.reconnectAttempts,
    30000  // 最大 30 秒
  )

  this.reconnectTimer = setTimeout(() => {
    this.reconnectAttempts++
    this.connect()
  }, delay)
}
```

## 4. SSE 传输

**位置**: `src/cli/transports/SSETransport.ts`

### 4.1 SSE 客户端实现

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["connect()"] --> B["创建 AbortController"]
    B --> C["fetch SSE 端点"]
    C --> D["读取 ReadableStream"]

    D --> E{"数据块?"}
    E -->|yes| F["解码"]
    E -->|no| G["继续读取"]

    F --> H["解析 SSE 格式"]
    H --> I["提取 data: 字段"]
    I --> J["触发 onData"]

    J --> D
    G --> D
```

## 5. 混合传输 (HybridTransport)

**位置**: `src/cli/transports/HybridTransport.ts`

### 5.1 设计原理

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Write["写入流程"]
        A1["write(stream_event)"] --> A2["加入缓冲"]
        A2 --> A3["设置 100ms 定时器"]

        B1["write(other)"] --> B2["立即 flush"]
        B2 --> A3

        A3 -->|定时触发| B4["enqueue + flush"]
        B4 --> B5["SerialBatchEventUploader"]
    end

    subgraph Post["POST 处理"]
        B5 --> C1{"状态码?"}
        C1 -->|2xx| C2["成功"]
        C1 -->|4xx 非 429| C3["丢弃"]
        C1 -->|429/5xx| C4["重试"]
    end
```

### 5.2 实现细节

```typescript
export class HybridTransport extends WebSocketTransport {
  private postUrl: string
  private uploader: SerialBatchEventUploader<StdoutMessage>
  private streamEventBuffer: StdoutMessage[] = []

  // 写入消息
  async write(message: StdoutMessage): Promise<void> {
    if (message.type === 'stream_event') {
      // 缓冲流事件
      this.streamEventBuffer.push(message)
      if (!this.streamEventTimer) {
        this.streamEventTimer = setTimeout(
          () => this.flushStreamEvents(),
          BATCH_FLUSH_INTERVAL_MS
        )
      }
      return
    }

    // 非流事件: 立即 flush 缓冲 + POST
    await this.uploader.enqueue([...this.takeStreamEvents(), message])
    return this.uploader.flush()
  }

  // 单次 HTTP POST
  private async postOnce(events: StdoutMessage[]): Promise<void> {
    const sessionToken = getSessionIngressAuthToken()

    const response = await axios.post(
      this.postUrl,
      { events },
      {
        headers: {
          Authorization: `Bearer ${sessionToken}`,
          'Content-Type': 'application/json',
        },
        timeout: POST_TIMEOUT_MS,
      }
    )

    if (response.status >= 200 && response.status < 300) {
      return  // 成功
    }

    if (response.status >= 400 && response.status < 500 && response.status !== 429) {
      return  // 永久失败
    }

    throw new Error(`POST failed with ${response.status}`)  // 可重试
  }
}
```

## 6. 批量事件上传器

**位置**: `src/cli/transports/SerialBatchEventUploader.ts`

### 6.1 核心功能

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    subgraph Enqueue["入队"]
        A1["enqueue(items)"] --> A2{"队列满?"}
        A2 -->|是| A3["drain()"]
        A2 -->|否| A4["加入队列"]
    end

    subgraph Drain["发送"]
        A4 --> B1["flush()"]
        A3 --> B1

        B1 --> B2{"队列非空?"}
        B2 -->|是| B3["sendWithRetry()"]
        B2 -->|否| B4["完成"]

        B3 -->|成功| B5["shift()"]
        B3 -->|失败| B6["超过最大失败?"]
        B6 -->|是| B7["dropBatch()"]
        B6 -->|否| B8["指数退避"]
        B8 --> B3
    end
```

### 6.2 发送与重试

```typescript
private async sendWithRetry(batch: T[]): Promise<void> {
  let attempts = 0

  while (true) {
    try {
      await this.config.send(batch)
      return  // 成功
    } catch (error) {
      attempts++

      // 计算延迟: 指数退避 + 抖动
      const baseDelay = Math.min(
        this.config.baseDelayMs * 2 ** attempts,
        this.config.maxDelayMs
      )
      const jitter = (Math.random() - 0.5) * 2 * this.config.jitterMs
      const delay = baseDelay + jitter

      await sleep(delay)
    }
  }
}
```

## 7. CCR 客户端

**位置**: `src/cli/transports/ccrClient.ts`

CCR (Cloud Code Runtime) 是远程执行协议：

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant CCR as CCRClient
    participant Transport as Transport

    CCR->>Transport: initialize()
    CCR->>Transport: sendEvents()
    CCR->>Transport: reportState()
```

## 8. Worker 状态上传器

**位置**: `src/cli/transports/WorkerStateUploader.ts`

### 8.1 后台状态报告

```typescript
export class WorkerStateUploader {
  private pending: StateUpdate[] = []
  private timer: ReturnType<typeof setInterval> | null = null

  constructor(private transport: Transport) {
    // 定期发送状态
    this.timer = setInterval(() => {
      this.flush()
    }, 1000)
  }

  push(update: StateUpdate): void {
    this.pending.push(update)
  }

  private async flush(): Promise<void> {
    if (this.pending.length === 0) return

    const updates = this.pending.splice(0, this.pending.length)

    await this.transport.write({
      type: 'worker_state',
      updates,
    })
  }
}
```

## 9. 传输工厂

**位置**: `src/cli/transports/transportUtils.ts`

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["createTransport(type, url, params)"] --> B{"type?"}

    B -->|hybrid| C["HybridTransport"]
    B -->|websocket| D["WebSocketTransport"]
    B -->|sse| E["SSETransport"]

    C --> F["返回 Transport 实例"]
    D --> F
    E --> F
```

## 10. 错误处理与恢复

### 10.1 错误类型

```typescript
enum TransportErrorType {
  NETWORK_ERROR = 'network_error',
  TIMEOUT = 'timeout',
  AUTH_ERROR = 'auth_error',      // 401
  PROTOCOL_ERROR = 'protocol_error', // 409
  SERVER_ERROR = 'server_error',  // 5xx
}
```

### 10.2 恢复策略

```mermaid
---
config:
  theme: neutral
---
flowchart LR
    A["传输错误"] --> B{"错误类型?"}

    B -->|auth_error| C["刷新 JWT"]
    C --> D["重建传输"]

    B -->|protocol_error| E["完全重连"]

    B -->|network_error| F["尝试重连"]
    B -->|timeout| F

    B -->|server_error| G["指数退避重试"]

    F --> H{"成功?"}
    H -->|是| I["恢复"]
    H -->|否| G
```

## 10. 补充：关键实现细节

### 10.1 具体退避参数

SerialBatchEventUploader 的 sendWithRetry 使用以下参数：
- baseDelayMs: 1000（1 秒）
- maxDelayMs: 30000（30 秒）
- 抖动：每次延迟加上 0-50% 的随机值
- maxConsecutiveFailures: 5（超过后永久标记为 failed）

### 10.2 HTTP POST 状态码处理

HybridTransport 的 POST 请求处理逻辑：
- 2xx：成功，继续下一批
- 401：触发 JWT 刷新，然后重建整个传输层
- 409：协议错误（epoch 不匹配），触发完全重连
- 429：指数退避重试
- 其他 4xx：永久失败，不重试
- 5xx：指数退避重试

### 10.3 CCR 客户端

Cloud Code Runtime (CCR) 客户端是一个独立的通信通道，用于远程会话管理。它不走 HybridTransport，而是直接 HTTP POST。CCR 客户端负责：
- initialize()：注册 worker
- sendEvents()：上报事件
- reportState()：定期状态快照

WorkerStateUploader 以 1 秒间隔批量上报 worker 状态，包括当前活动的工具、消息队列长度等。

### 10.4 流式传输的背压控制

streamEventBuffer 使用固定的 100ms 批量间隔，但当缓冲区超过 1000 条消息时（实际上不太可能），会立即 flush。这个设计在 99.9% 的情况下是按时间触发的，只在极端流量下才触发大小限制。

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
