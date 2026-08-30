$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir

if (-not $env:GEMMA_BRIDGE_MODEL_NAME) {
	$env:GEMMA_BRIDGE_MODEL_NAME = "gemma4"
}

if (-not $env:GEMMA_BRIDGE_HOST) {
	$env:GEMMA_BRIDGE_HOST = "127.0.0.1"
}

if (-not $env:GEMMA_BRIDGE_PORT) {
	$env:GEMMA_BRIDGE_PORT = "8787"
}

if (-not $env:OLLAMA_BASE_URL) {
	$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
}

if (-not $env:OLLAMA_MODEL) {
	$env:OLLAMA_MODEL = "gemma4:e4b"
}

$bridgeLog = Join-Path $projectDir ".gemma-bridge.log"
$bridgeErr = Join-Path $projectDir ".gemma-bridge.err.log"

$bridgeArgs = @(
	"`"$projectDir\scripts\ollama_anthropic_bridge.py`"",
	"--host", $env:GEMMA_BRIDGE_HOST,
	"--port", $env:GEMMA_BRIDGE_PORT,
	"--model-name", $env:GEMMA_BRIDGE_MODEL_NAME,
	"--ollama-base-url", $env:OLLAMA_BASE_URL,
	"--ollama-model", $env:OLLAMA_MODEL
)

$bridge = Start-Process `
	-FilePath python `
	-ArgumentList $bridgeArgs `
	-WorkingDirectory $projectDir `
	-RedirectStandardOutput $bridgeLog `
	-RedirectStandardError $bridgeErr `
	-PassThru

Start-Sleep -Seconds 2

$env:ANTHROPIC_BASE_URL = "http://$($env:GEMMA_BRIDGE_HOST):$($env:GEMMA_BRIDGE_PORT)"
$env:ANTHROPIC_API_KEY = "local-gemma"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION = $env:GEMMA_BRIDGE_MODEL_NAME
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_NAME = "Gemma 4 (Local)"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION = "本地 Ollama 上的 Gemma 4，经 Anthropic Messages 兼容桥接"
$env:ANTHROPIC_MODEL = $env:GEMMA_BRIDGE_MODEL_NAME

Write-Host "Gemma bridge PID: $($bridge.Id)"
Write-Host "Bridge URL: $env:ANTHROPIC_BASE_URL"
Write-Host "Ollama URL: $env:OLLAMA_BASE_URL"
Write-Host "Ollama model: $env:OLLAMA_MODEL"
Write-Host "Bridge stdout: $bridgeLog"
Write-Host "Bridge stderr: $bridgeErr"

Set-Location $projectDir
bun run src/entrypoints/cli.tsx --model $env:GEMMA_BRIDGE_MODEL_NAME
