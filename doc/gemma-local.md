# 本地 Gemma 4 集成说明

本项目已经补了一层 `Gemma -> Anthropic Messages` 兼容桥，目标是尽量不改 Claude Code 主调用链，让现有 CLI 通过 `ANTHROPIC_BASE_URL` 直接接到本地 Gemma 4。

## 新增内容

- `claude-code/scripts/gemma_bridge.py`
  - 一个本地 HTTP 服务，暴露 `POST /v1/messages`
  - 接收 Anthropic Messages 风格请求
  - 转成单轮 Gemma prompt
  - 输出 Anthropic 风格 JSON / SSE
- `claude-code/scripts/start-gemma-local.ps1`
  - 启动桥接服务
  - 自动注入 Claude Code 需要的环境变量
  - 用 `gemma4` 作为当前模型启动 CLI

## 当前实现范围

当前桥接层优先打通下面这条链路：

1. Claude Code 发起 `beta.messages.create`
2. 请求进入本地 `gemma_bridge.py`
3. 桥接层把消息历史和工具定义拼成单轮 prompt
4. Gemma 4 生成普通文本，或者生成一个 `<tool_call>{...}</tool_call>`
5. 桥接层把结果重新包装成 Anthropic `text` / `tool_use` block

这意味着：

- 普通对话可用
- 基础工具调用链路可用
- CLI 侧原本的工具执行器仍然继续工作

暂未做深度适配的部分：

- 多模态输入
- Anthropic thinking / signature 类 block
- 多工具并发输出
- 精确 token 统计

## 运行前准备

需要你本机已经满足：

- Python 3.12+
- 可导入本地 `gemma` 仓库
- Gemma 4 的本地 checkpoint 已下载
- Bun 依赖已安装

至少设置这个环境变量：

```powershell
$env:GEMMA_CKPT_PATH = "D:\path\to\your\gemma4-checkpoint"
```

可选环境变量：

```powershell
$env:GEMMA_REPO_PATH = "D:\dev\git\branch\rust_project\gemma"
$env:GEMMA_VARIANT = "gemma4-e2b-it"
$env:GEMMA_BRIDGE_MODEL_NAME = "gemma4"
$env:GEMMA_BRIDGE_PORT = "8787"
```

支持的 `GEMMA_VARIANT`：

- `gemma4-e2b-it`
- `gemma4-e4b-it`
- `gemma4-31b-it`
- `gemma4-26b-a4b-it`

## 启动方式

在 `claude-code/` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-gemma-local.ps1
```

脚本会：

1. 启动本地桥接服务
2. 设置：
   - `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`
   - `ANTHROPIC_API_KEY=local-gemma`
   - `ANTHROPIC_MODEL=gemma4`
   - `ANTHROPIC_CUSTOM_MODEL_OPTION=gemma4`
3. 启动 Claude Code CLI

## 使用方式

启动后有两种方式切换到本地模型：

- 启动脚本已经默认用 `--model gemma4`
- 在 CLI 里使用 `/model`，选择 `Gemma 4 (Local)`

## 备注

桥接服务并没有把 Gemma 伪装成“真的 Anthropic 模型能力集合”，只是尽可能兼容 Claude Code 当前需要的最小 Messages 协议。所以如果某些高级特性依赖 Anthropic 专有流式块，仍可能需要继续补桥接逻辑。
