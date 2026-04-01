# Claude Code 源码分析：上下文压缩系统

## 1. 上下文压缩概述

Claude Code 实现了多层次的上下文压缩系统，以管理对话历史带来的令牌消耗。

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["消息令牌数"] --> B{超过阈值?}

    B -->|150K| C["Snip 裁剪"]
    B -->|180K| D["Autocompact"]
    B -->|160K| E["Context Collapse"]
    B -->|正常| F["直接使用"]

    C --> G{"还需压缩?"}
    G -->|是| D
    G -->|否| F

    D --> H["生成摘要"]
    H --> F

    E --> F
```

## 2. Snip (裁剪)

**位置**: `src/services/compact/snipCompact.ts`

### 2.1 设计原理

Snip 通过分析消息内容，移除对当前对话贡献最小的消息：

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["snipCompactIfNeeded()"] --> B{"token > 阈值?"}

    B -->|否| C["直接返回"]
    B -->|是| D["identifyLowValueMessages()"]

    D --> E["计算消息分数"]
    E --> F["选择要移除的消息"]

    F --> G["创建边界消息"]
    G --> H["返回裁剪结果"]
```

### 2.2 低价值消息识别

```typescript
function identifyLowValueMessages(messages: Message[]): ScoredMessage[] {
  return messages
    .map((msg, index) => ({
      message: msg,
      index,
      score: calculateMessageValue(msg, {
        position: index / messages.length,      // 位置权重
        isToolResult: msg.type === 'user',       // 工具结果权重低
        hasUserContent: hasUserContent(msg),     // 用户内容权重高
        isAssistantReasoning: isReasoning(msg), // 思考过程权重低
      })
    }))
    .filter scored => scored.score < VALUE_THRESHOLD
    .sort((a, b) => a.score - b.score)  // 低分在前
}
```

## 3. Microcompact (微压缩)

**位置**: `src/services/compact/microCompact.ts`

### 3.1 设计原理

Microcompact 合并连续的工具调用和结果，生成简洁的摘要：

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["microcompact()"] --> B["identifyMergeableGroups()"]

    B --> C{"组类型?"}

    C -->|tool_sequence| D["summarizeToolSequence()"]
    C -->|read_sequence| E["summarizeFileReads()"]
    C -->|其他| F["保持不变"]

    D --> G["合并结果"]
    E --> G
    F --> G

    G --> H["返回压缩消息"]
```

### 3.2 工具序列摘要

```typescript
async function summarizeToolSequence(
  messages: Message[]
): Promise<SystemMessage> {
  const toolCalls = messages
    .filter(m => m.type === 'assistant')
    .flatMap(m => m.message.content.filter(c => c.type === 'tool_use'))

  const toolResults = messages
    .filter(m => m.type === 'user')
    .flatMap(m => m.message.content.filter(c => c.type === 'tool_result'))

  // 生成摘要
  const summary = toolCalls.map((call, i) => {
    const result = toolResults[i]
    return `${call.name}(${JSON.stringify(call.input)}) → ${truncate(result.content, 100)}`
  }).join('\n')

  return createSystemMessage(
    `Executed ${toolCalls.length} operations:\n${summary}`,
    'compact_summary'
  )
}
```

## 4. Autocompact (自动压缩)

**位置**: `src/services/compact/autoCompact.ts`

### 4.1 触发条件

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["shouldAutoCompact()"] --> B{"token > 阈值?"}

    B -->|否| C["返回 false"]
    B -->|是| D{"冷却期中?"}

    D -->|是| C
    D -->|否| E{"连续失败超限?"}

    E -->|是| C
    E -->|否| F["返回 true"]
```

### 4.2 压缩执行

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant QE as QueryEngine
    participant Compact as Autocompact
    participant API as Claude API

    QE->>Compact: autocompact()
    Compact->>Compact: buildCompactPrompt()
    Compact->>API: callModelWithMessages()
    API-->>Compact: summary

    Compact->>Compact: buildCompactedMessages()
    Compact-->>QE: CompactionResult
```

## 5. Context Collapse (上下文折叠)

**位置**: `src/services/contextCollapse/index.ts`

### 5.1 设计原理

Context Collapse 通过选择性折叠次要消息来管理上下文：

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    subgraph Stage["阶段折叠"]
        A1["stageCollapse()"]
        A2["shouldCollapse()?"]
        A3["计算优先级"]
        A4["添加到 stagedCollapses"]
    end

    subgraph Commit["提交折叠"]
        B1["commitCollapses()"]
        B2["按优先级排序"]
        B3["执行折叠"]
        B4["生成摘要"]
        B5["存储到 collapsedMessages"]
    end

    A1 --> A2 --> A3 --> A4
    B1 --> B2 --> B3 --> B4 --> B5
```

### 5.2 恢复折叠

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["recoverFromOverflow()"] --> B{"遍历消息"}

    B --> C{"是 collapse_marker?"}

    C -->|是| D["查找折叠组"]
    C -->|否| F["添加到结果"]

    D --> E{"找到?"}

    E -->|是| G["展开折叠消息"]
    E -->|否| F

    G --> F
    F --> B
```

## 6. 缓存管理

### 6.1 缓存令牌

**位置**: `src/services/api/promptCacheBreakDetection.ts`

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["detectCacheBreak()"] --> B{"有 cache_read_input_tokens?"}

    B -->|否| C["返回 null"]
    B -->|是| D["计算缓存效率"]

    D --> E{"效率 > 阈值?"}

    E -->|是| F["返回 null"]
    E -->|否| G["返回 CacheBreakInfo"]
```

### 6.2 缓存感知压缩

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    A["cacheAwareCompact()"] --> B["过滤缓存贡献消息"]

    B --> C{"消息类型?"}

    C -->|assistant| D{"有工具调用?"}
    C -->|user| E{"有用户内容?"}
    C -->|其他| F["保留"]

    D -->|是| F
    D -->|否| G["移除"]
    E -->|是| F
    E -->|否| G
```

## 7. 压缩配置

### 7.1 配置参数

```mermaid
---
config:
  theme: neutral
---
flowchart TB
    subgraph Config["CompactConfig"]
        A1["snip"]
        A2["microcompact"]
        A3["autocompact"]
        A4["contextCollapse"]
    end

    subgraph Snip["snip 配置"]
        B1["thresholdTokens: 150K"]
        B2["targetTokens: 100K"]
    end

    subgraph Auto["autocompact 配置"]
        C1["thresholdTokens: 180K"]
        C2["targetTokens: 120K"]
        C3["cooldownMs: 60s"]
    end
```

## 8. 压缩事件

### 8.1 事件跟踪

```mermaid
---
config:
  theme: neutral
---
sequenceDiagram
    participant Compact as Autocompact
    participant Logger as Analytics

    Compact->>Compact: 执行压缩
    Compact->>Logger: logEvent
    Note over Logger: tengu_auto_compact_succeeded

    Logger->>Logger: 记录指标
```

---

*文档版本: 1.0*
*分析日期: 2026-03-31*
