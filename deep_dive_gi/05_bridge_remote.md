# 05. Bridge 远程系统深度解析

Bridge 是 `claude-code` 实现远程控制（Remote Control）、云端协作（Cowork）及跨环境执行的核心枢纽。它不仅是一层通信代理，更是一个复杂的状态机，负责管理传输链路、会话生命周期、权限协调以及多实例并发控制。

## 5.1. 架构演进：从 V1 到 V2 (Env-less)

在最新的实现中，Bridge 系统已经从依赖中间层（Environments API）的 V1 架构演进到了直接连接会话接入层（Session Ingress）的 V2（Env-less）架构。

### 5.1.1. V2 (Env-less) 流程
1. **会话创建**：`POST /v1/code/sessions` 获取 `sessionId`。
2. **凭证获取 (Register)**：`POST /v1/code/sessions/{id}/bridge` 获取 `worker_jwt`、`worker_epoch` 和 `api_base_url`。
    - **关键点**：每次调用 `/bridge` 都会增加 `worker_epoch`，这起到了分布式锁的作用。
3. **传输层建立**：创建 `ReplBridgeTransport`，组合 `SSETransport`（下行）与 `CCRClient`（上行）。
4. **令牌自刷新**：通过 `jwtUtils.ts` 监控 JWT 过期，并在过期前 5 分钟自动重建链路。

### 5.1.2. 核心组件分布
| 组件 | 文件 | 职责 |
| :--- | :--- | :--- |
| `RemoteBridgeCore` | `remoteBridgeCore.ts` | 顶层状态机，处理初始化、重连、纪元切换及 401/409 恢复逻辑。 |
| `ReplBridgeTransport` | `replBridgeTransport.ts` | 传输抽象层，封装了 SSE 监听与 CCR v2 协议细节。 |
| `CCRClient` | `ccrClient.ts` | 实现 Cloud Control Runtime v2 协议，处理上报、心跳及状态更新。 |
| `SSETransport` | `SSETransport.ts` | 处理基于 SSE 的服务器事件流，支持消息定序与断线重连。 |
| `FlushGate` | `flushGate.ts` | 消息闸门，确保在历史消息（History Flush）完成前拦截并排队实时消息。 |

## 5.2. 协议栈细节

Bridge V2 采用了双工通信模式，但上下行使用了不同的传输协议。

### 5.2.1. 下行链路 (Downstream): SSE
服务器通过 `SSETransport` 推送 `SDKMessage` 和 `SDKControlRequest`。
- **消息定序**：每个 SSE 事件带有 `sequence_num`。客户端在重连时会通过 `Last-Event-ID` 或 `from_sequence_num` 参数告知服务器从何处恢复，避免全量历史回放。
- **回显过滤 (Echo Dedup)**：客户端发送的消息会通过 SSE 再次下发。系统使用 `BoundedUUIDSet`（一个固定容量的环形缓冲区）记录已发送消息的 UUID，从而过滤掉回显。

### 5.2.2. 上行链路 (Upstream): CCR v2
客户端通过 `CCRClient` 向 `/worker/*` 接口发送数据。
- **批量上报**：使用 `SerialBatchEventUploader` 异步、有序地将消息批量 POST 到服务器。
- **状态报告**：通过 `reportState` 实时同步当前 Worker 的状态（`running`、`idle`、`requires_action`）。
- **心跳机制**：定时发送心跳包以维持会话租约，并在心跳中携带当前 epoch，一旦检测到 409 冲突即刻断开旧连接。

## 5.3. 关键数据结构分析

### 5.3.1. 远程凭证 (RemoteCredentials)
```typescript
export type RemoteCredentials = {
  worker_jwt: string;    // 用于 CCR 和 SSE 鉴权的 JWT
  expires_in: number;    // 过期时间（秒）
  api_base_url: string;  // 接入层基准 URL
  worker_epoch: number;  // 纪元号，用于多实例竞争检测
}
```

### 5.3.2. 控制请求与响应 (Control Protocol)
服务器可以主动向客户端发起控制请求，例如：
- `initialize`: 建立连接时的握手。
- `set_model`: 强制更改当前使用的模型。
- `interrupt`: 停止当前 AI 任务。
- `can_use_tool`: 申请工具执行权限。

客户端必须在 ~10-14s 内响应 `control_response`，否则服务器将断开连接。

## 5.4. 核心逻辑深潜

### 5.4.1. 纪元管理 (Epoch Management)
`worker_epoch` 是 Bridge 系统的“护城河”。
- 当用户在多个标签页中运行同一个 `claude remote-control` 时，后启动的实例会通过 `/bridge` 接口获取到更高的 epoch。
- 服务器会拒绝（409 Conflict）任何持有旧 epoch 的写请求。
- 旧实例收到 409 后，会通过 `onEpochMismatch` 逻辑主动断开连接，避免多点写导致的数据混乱。

### 5.4.2. 故障恢复与重连逻辑
`remoteBridgeCore.ts` 实现了精密的恢复策略：
1. **401 恢复**：当监听到 SSE 401 错误时，`recoverFromAuthFailure` 会触发 OAuth 刷新，重新调用 `/bridge` 获取新 JWT，并以相同的 `sessionId` 和 `sequence_num` 重建 Transport。
2. **主动刷新 (Proactive Refresh)**：`createTokenRefreshScheduler` 会在 JWT 到期前 5 分钟启动重建流程，整个过程对用户近乎无感。
3. **FlushGate 同步**：
   - 在初始化或重连后，首先发起 `flushHistory`（POST 所有历史消息）。
   - 同时，新的用户输入会被拦截在 `FlushGate` 中。
   - 待历史消息 POST 成功后，调用 `drainFlushGate` 将排队的消息按序发出。

### 5.4.3. 优雅停机 (Teardown)
在进程退出时，Bridge 会执行一系列清理动作：
- 发送 `result_success` 消息，确保服务器正确归档当前会话。
- 调用 `archiveSession` 接口。
- 关闭所有 SSE 和 CCR 连接。

## 5.5. 两种 Bridge 模式对比

根据使用场景的不同，`claude-code` 实际上维护了两套 Bridge 运行模式：

| 特性 | Env-less REPL Bridge (V2) | Poll-based Bridge Environment |
| :--- | :--- | :--- |
| **主要用途** | 个人 REPL 远程连接、Cowork | `claude remote-control` (多会话 Worker) |
| **调度方式** | 直接连接 (OAuth -> Session Ingress) | 轮询 (Poll) -> 认领 (Ack) -> 执行 |
| **并发能力** | 单一会话 | 支持多会话并行 (Spawn Mode) |
| **状态维护** | 内存状态机 (RemoteBridgeCore) | 持久化环境 (Environments API) |
| **代码文件** | `remoteBridgeCore.ts`, `replBridge.ts` | `bridgeMain.ts`, `bridgeApi.ts` |

### 5.5.1. 多会话管理的复杂度
在 `bridgeMain.ts` 实现的“环境模式”中，Bridge 需要管理：
- **工作树隔离 (Worktree Isolation)**：在 `worktree` 模式下，为每个远程会话创建独立的 git worktree。
- **看门狗计时器 (Watchdog)**：监控 `sessionTimeoutMs`，强制杀死超时的僵尸会话。
- **负载控制 (Capacity)**：根据 `maxSessions` 限制并发，并在满载时进入休眠等待 `capacityWake` 信号。

## 5.6. 总结
Bridge 系统通过解耦上下行链路（SSE + CCR），结合严格的纪元锁（Epoch Lock）和自动刷新机制，在复杂的网络环境下实现了极致的远程交互体验。它是 `claude-code` 从单机工具走向分布式云端助手的技术基石。
