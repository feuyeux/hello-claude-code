# 百炼兼容 API 接入手册

本文说明如何把这个仓库切到阿里云百炼的 Anthropic 兼容接口，并解释为什么原始版本在国内兼容网关场景下会遇到 `Not logged in` 和官方 `preflight` 检查失败。

适用对象：

- 在中国大陆使用这个仓库
- 不走 Anthropic 官方账号
- 改用阿里云百炼的 Anthropic 兼容 API

## 1. 结论

这个仓库可以直接接阿里云百炼，因为它本身就是围绕 Anthropic 协议实现的，核心使用的是：

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`

但是，原始代码对“非 Anthropic 官方 host”的兼容并不完整，主要会卡在两处：

1. 首次交互启动时的 onboarding `preflight` 会硬连 `api.anthropic.com`
2. 环境变量里的 `ANTHROPIC_API_KEY` 在交互模式下默认需要本地批准后才会被视为有效认证

本仓库当前已经做了两处补丁来适配百炼。

## 2. 当前接入方式

百炼官方提供了 Anthropic 兼容接口，推荐环境变量如下：

```powershell
$env:ANTHROPIC_BASE_URL="https://dashscope.aliyuncs.com/apps/anthropic"
$env:ANTHROPIC_API_KEY="你的百炼API Key"
$env:ANTHROPIC_MODEL="qwen3.6-plus"
```

然后在 `claude-code/` 目录启动：

```powershell
cd d:\dev\git\branch\rust_project\hello-claude-code\claude-code
bun run dev
```

如果当前终端曾经配置过无效代理，建议一并清理：

```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
```

## 3. 为什么原始代码会失败

### 3.1 官方连通性预检会先失败

首次启动时，交互模式会进入 onboarding。onboarding 中的 `PreflightStep` 会调用：

- `https://api.anthropic.com/api/hello`
- OAuth 令牌域名下的 `/v1/oauth/hello`

这一步没有读取 `ANTHROPIC_BASE_URL`，所以即使已经配置成百炼，也会先因为访问官方地址失败而退出。

相关代码：

- [Onboarding.tsx](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/components/Onboarding.tsx)
- [preflightChecks.tsx](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/preflightChecks.tsx)

### 3.2 API Key 在交互模式默认要先经过本地批准

`getAnthropicApiKeyWithSource()` 在默认交互模式下，不会仅凭 `ANTHROPIC_API_KEY` 环境变量就认为已经登录。原始逻辑要求：

- 当前 key 在本地 `customApiKeyResponses.approved` 里
- 或者来自 file descriptor
- 或者来自 `apiKeyHelper`

这对 Anthropic 官方 onboarding 是合理的，但对阿里云百炼这类兼容网关来说，会导致：

- 明明设置了 `ANTHROPIC_API_KEY`
- `auth status --json` 仍显示 `loggedIn: false`
- 交互界面持续显示 `Not logged in · Please run /login`

相关代码：

- [auth.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/auth.ts)

## 4. 已做的源码补丁

### 4.1 非官方 host 时跳过官方 onboarding 预检

当前仓库已在 [Onboarding.tsx](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/components/Onboarding.tsx) 中增加判断：

- 如果 `ANTHROPIC_BASE_URL` 不是 Anthropic 官方 host
- 就不再加入 `preflight` 步骤
- 也不再加入官方 OAuth 登录引导

保留：

- 主题选择
- API key 批准界面
- 安全提示

这样可以避免在真正请求百炼前先被官方连通性检查拦截。

### 4.2 非官方 host 时直接信任环境变量中的 API Key

当前仓库已在 [auth.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/auth.ts) 中增加判断：

- 如果 `ANTHROPIC_BASE_URL` 不是 Anthropic 官方 host
- 且存在 `ANTHROPIC_API_KEY`
- 则直接返回该 key 作为有效认证来源

这样交互模式和 `-p` 非交互模式都能正确识别百炼的 API key。

## 5. 验证命令

### 5.1 验证当前 shell 中环境变量是否真的生效

```powershell
echo $env:ANTHROPIC_BASE_URL
echo $env:ANTHROPIC_MODEL
echo ($env:ANTHROPIC_API_KEY.Length -gt 0)
```

如果你是新开了一个 PowerShell 窗口，需要在那个窗口里重新设置这些变量。PowerShell 的 `$env:` 默认是当前会话级，不会自动传播到后开的新窗口。

### 5.2 验证 CLI 当前是否已识别为已认证

```powershell
bun run dev auth status --json
```

预期应类似于：

```json
{
  "loggedIn": true,
  "authMethod": "api_key",
  "apiProvider": "firstParty",
  "apiKeySource": "ANTHROPIC_API_KEY"
}
```

说明：

- `apiProvider` 仍可能是 `firstParty`
- 这是正常的，因为百炼这里走的是 Anthropic 兼容网关，不是 Bedrock、Vertex 或 Foundry

### 5.3 验证非交互请求链路

```powershell
bun run dev -p "你好，请只回复ok"
```

如果这里能返回正常文本，说明：

- 百炼地址可达
- API key 可用
- 模型名可用
- 请求头与 SDK 组织方式基本可用

## 6. 推荐的日常启动方式

每次启动前，在同一个 PowerShell 会话执行：

```powershell
$env:ANTHROPIC_BASE_URL="https://dashscope.aliyuncs.com/apps/anthropic"
$env:ANTHROPIC_API_KEY="你的百炼API Key"
$env:ANTHROPIC_MODEL="qwen3.6-plus"
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
cd d:\dev\git\branch\rust_project\hello-claude-code\claude-code
bun run dev
```

如果要避免每次手动输入，推荐单独写一个本地启动脚本，但不要把真实 key 提交到 Git 仓库。

## 7. 常见问题

### 7.1 明明配置过环境变量，为什么 `auth status --json` 还是 `loggedIn: false`

最常见原因是变量设在了另一个窗口里。PowerShell 中：

- `setx` 是持久化到未来新窗口
- `$env:NAME=...` 是只对当前窗口生效

如果你新开了 PowerShell，需要重新设置 `$env:ANTHROPIC_BASE_URL`、`$env:ANTHROPIC_API_KEY`、`$env:ANTHROPIC_MODEL`。

### 7.2 为什么界面里还会出现 `/login`

这个仓库的很多提示文案默认是围绕 Anthropic 官方账号体系写的，所以在兼容网关场景里，部分文案依然可能出现 `/login` 提示。但只要：

- `auth status --json` 显示 `loggedIn: true`
- `-p` 请求能成功

那么这类提示更多是文案惯性，不等于必须走 Anthropic 官方登录。

### 7.3 `ANTHROPIC_MODEL` 应该填什么

应以阿里云百炼官方当前支持的模型名为准。本文示例使用：

```powershell
$env:ANTHROPIC_MODEL="qwen3.6-plus"
```

如果后续模型更新，以百炼控制台和官方文档为准。

## 8. 相关源码位置

- [Onboarding.tsx](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/components/Onboarding.tsx)
- [preflightChecks.tsx](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/preflightChecks.tsx)
- [auth.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/auth.ts)
- [client.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/services/api/client.ts)
- [providers.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/model/providers.ts)
- [model.ts](d:/dev/git/branch/rust_project/hello-claude-code/claude-code/src/utils/model/model.ts)

## 9. 外部参考

- 阿里云百炼 Claude Code 接入文档：<https://help.aliyun.com/zh/model-studio/claude-code>
- 阿里云百炼 Anthropic 兼容接口：<https://help.aliyun.com/zh/model-studio/anthropic-api-messages>

