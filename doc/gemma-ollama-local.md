# 本地 Gemma 4 + Ollama 集成说明

本项目通过一个本地兼容桥把 Claude Code 的 Anthropic Messages 请求转发到 Ollama，再由 Ollama 调用本机的 `gemma4`。

## 新增内容

- `claude-code/scripts/gemma_bridge.py`
  - 把 Anthropic Messages 请求转成单轮 prompt
  - 调用本地 Ollama `api/generate`
  - 再包装回 Anthropic 风格 JSON / SSE
- `claude-code/scripts/start-gemma-ollama.ps1`
  - 启动桥接服务
  - 注入 Claude Code 需要的环境变量
  - 直接用 `gemma4` 启动 CLI

## 运行前准备

- 本机 Ollama 已启动
- Ollama 已下载 `gemma4`
- Python 3.12+
- Bun 依赖已安装

可选环境变量：

```powershell
$env:GEMMA_BRIDGE_MODEL_NAME = "gemma4"
$env:GEMMA_BRIDGE_PORT = "8787"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "gemma4:e4b"
```

## 启动方式

在 `claude-code/` 目录执行：

```powershell
bun run dev:gemma
```

或直接执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-gemma-ollama.ps1
```

## 当前默认值

- Claude Code 模型名：`gemma4`
- 实际 Ollama 模型：`gemma4:e4b`
- Ollama 地址：`http://127.0.0.1:11434`
- 兼容桥地址：`http://127.0.0.1:8787`
