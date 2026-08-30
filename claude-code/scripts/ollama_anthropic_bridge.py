#!/usr/bin/env python3
"""Anthropic Messages-compatible bridge backed by a local Ollama model."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*\})\s*</tool_call>", re.DOTALL)
DEFAULT_MODEL_NAME = "gemma4"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:e4b"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--host", default=os.environ.get("GEMMA_BRIDGE_HOST", DEFAULT_HOST))
	parser.add_argument(
		"--port",
		type=int,
		default=int(os.environ.get("GEMMA_BRIDGE_PORT", str(DEFAULT_PORT))),
	)
	parser.add_argument(
		"--model-name",
		default=os.environ.get("GEMMA_BRIDGE_MODEL_NAME", DEFAULT_MODEL_NAME),
		help="Model name exposed to Claude Code.",
	)
	parser.add_argument(
		"--ollama-base-url",
		default=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
		help="Base URL for the local Ollama server.",
	)
	parser.add_argument(
		"--ollama-model",
		default=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
		help="Concrete Ollama model tag to invoke, e.g. gemma4:e4b.",
	)
	return parser.parse_args()


def json_dumps(data: Any) -> str:
	return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def chunk_text(text: str, size: int = 96) -> list[str]:
	if not text:
		return [""]
	return [text[i : i + size] for i in range(0, len(text), size)]


def coerce_text(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, str):
		return value
	if isinstance(value, list):
		return "\n".join(filter(None, (coerce_text(item) for item in value)))
	if isinstance(value, dict):
		if value.get("type") == "text":
			return str(value.get("text", ""))
		return json_dumps(value)
	return str(value)


def normalize_system(system_value: Any) -> str:
	if isinstance(system_value, str):
		return system_value
	if isinstance(system_value, list):
		parts: list[str] = []
		for item in system_value:
			if isinstance(item, dict):
				if item.get("type") == "text":
					parts.append(str(item.get("text", "")))
				else:
					parts.append(json_dumps(item))
			else:
				parts.append(str(item))
		return "\n".join(part for part in parts if part)
	return ""


def describe_block(block: Any) -> str:
	if isinstance(block, str):
		return block
	if not isinstance(block, dict):
		return str(block)

	block_type = block.get("type")
	if block_type == "text":
		return str(block.get("text", ""))
	if block_type == "tool_use":
		payload = {
			"id": block.get("id"),
			"name": block.get("name"),
			"input": block.get("input", {}),
		}
		return f"<tool_call>{json_dumps(payload)}</tool_call>"
	if block_type == "tool_result":
		content_text = coerce_text(block.get("content"))
		is_error = bool(block.get("is_error"))
		tool_use_id = block.get("tool_use_id", "")
		error_attr = ' is_error="true"' if is_error else ""
		return (
			f'<tool_result tool_use_id="{tool_use_id}"{error_attr}>'
			f"{content_text}"
			f"</tool_result>"
		)
	if block_type in {"image", "document"}:
		return f"[Unsupported {block_type} content omitted by Ollama bridge]"
	return json_dumps(block)


def build_prompt(payload: dict[str, Any], model_name: str) -> str:
	system_text = normalize_system(payload.get("system"))
	tools = payload.get("tools") or []
	messages = payload.get("messages") or []

	sections: list[str] = [
		f"You are {model_name}, reached through an Anthropic Messages compatibility bridge backed by Ollama.",
		"Respond naturally unless you need a tool.",
		"When you need exactly one tool call, output only this XML tag and nothing else:",
		'<tool_call>{"name":"tool_name","input":{"key":"value"}}</tool_call>',
		"Do not use markdown fences around the JSON.",
	]

	if system_text:
		sections.extend(["", "System instructions:", system_text])

	if tools:
		sections.extend(
			[
				"",
				"Available tools:",
				json.dumps(tools, ensure_ascii=False, indent=2),
				"",
				"If a tool is needed, choose from the list above and return exactly one <tool_call> block.",
			]
		)

	sections.append("")
	sections.append("Conversation:")

	for message in messages:
		role = str(message.get("role", "user")).upper()
		content = message.get("content", [])
		if isinstance(content, str):
			content = [{"type": "text", "text": content}]
		sections.append(f"{role}:")
		if not isinstance(content, list):
			sections.append(coerce_text(content))
			continue
		for block in content:
			sections.append(describe_block(block))

	sections.extend(
		[
			"",
			"Now produce the next assistant turn.",
			"Either reply with plain text, or with one exact <tool_call>...</tool_call> block.",
		]
	)
	return "\n".join(sections)


def build_fallback_prompt(payload: dict[str, Any], model_name: str) -> str:
	messages = payload.get("messages") or []
	latest_user_text = ""
	for message in reversed(messages):
		if str(message.get("role")) != "user":
			continue
		content = message.get("content", [])
		if isinstance(content, str):
			latest_user_text = content
			break
		if isinstance(content, list):
			parts = [describe_block(block) for block in content]
			latest_user_text = "\n".join(part for part in parts if part)
			break
	system_text = normalize_system(payload.get("system"))
	sections = [
		f"You are {model_name}.",
		"Reply to the user directly.",
		"Do not return an empty answer.",
	]
	if system_text:
		sections.extend(["", "System instructions:", system_text])
	sections.extend(["", "User request:", latest_user_text or "Hello"])
	return "\n".join(sections)


class OllamaBridge:
	def __init__(self, *, ollama_base_url: str, ollama_model: str, model_name: str):
		self.ollama_base_url = ollama_base_url.rstrip("/")
		self.ollama_model = ollama_model
		self.model_name = model_name

	def generate(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
		prompt = build_prompt(payload, self.model_name)
		max_new_tokens = int(payload.get("max_tokens") or 1024)
		temperature = payload.get("temperature")
		raw = self._run_generate(prompt, max_new_tokens, temperature)
		text = str(raw.get("response", "")).strip()
		if not text:
			fallback_prompt = build_fallback_prompt(payload, self.model_name)
			raw = self._run_generate(fallback_prompt, max_new_tokens, temperature)
			text = str(raw.get("response", "")).strip()
		return self._message_from_text(text), text

	def _run_generate(
		self,
		prompt: str,
		max_new_tokens: int,
		temperature: Any,
	) -> dict[str, Any]:
		options: dict[str, Any] = {"num_predict": max_new_tokens}
		if temperature is not None:
			options["temperature"] = temperature

		request_payload = {
			"model": self.ollama_model,
			"prompt": prompt,
			"stream": False,
			"options": options,
		}
		return self._post_json("/api/generate", request_payload)

	def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
		request = urllib.request.Request(
			self.ollama_base_url + path,
			data=json.dumps(payload).encode("utf-8"),
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(request, timeout=600) as response:
				return json.loads(response.read().decode("utf-8"))
		except urllib.error.HTTPError as exc:
			body = exc.read().decode("utf-8", errors="replace")
			raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
		except urllib.error.URLError as exc:
			raise RuntimeError(
				f"Cannot reach Ollama at {self.ollama_base_url}: {exc.reason}"
			) from exc

	def _message_from_text(self, raw_text: str) -> dict[str, Any]:
		text = raw_text.strip()
		tool_match = TOOL_CALL_RE.search(text)
		content: list[dict[str, Any]]
		stop_reason = "end_turn"

		if tool_match:
			try:
				tool_payload = json.loads(tool_match.group(1))
				tool_name = str(tool_payload["name"])
				tool_input = tool_payload.get("input", {})
				if not isinstance(tool_input, dict):
					tool_input = {"value": tool_input}
				content = [
					{
						"type": "tool_use",
						"id": f"toolu_{uuid.uuid4().hex}",
						"name": tool_name,
						"input": tool_input,
					}
				]
				stop_reason = "tool_use"
			except Exception:
				content = [{"type": "text", "text": text}]
			else:
				return make_message(self.model_name, content, stop_reason)
		else:
			content = [{"type": "text", "text": text}]

		return make_message(self.model_name, content, stop_reason)


def make_usage() -> dict[str, int]:
	return {
		"input_tokens": 0,
		"output_tokens": 0,
		"cache_creation_input_tokens": 0,
		"cache_read_input_tokens": 0,
	}


def make_message(
	model_name: str,
	content: list[dict[str, Any]],
	stop_reason: str,
) -> dict[str, Any]:
	return {
		"id": f"msg_{uuid.uuid4().hex}",
		"type": "message",
		"role": "assistant",
		"model": model_name,
		"content": content,
		"stop_reason": stop_reason,
		"stop_sequence": None,
		"usage": make_usage(),
	}


def make_sse_events(message: dict[str, Any]) -> list[dict[str, Any]]:
	message_start = {
		"type": "message_start",
		"message": {
			"id": message["id"],
			"type": "message",
			"role": "assistant",
			"model": message["model"],
			"content": [],
			"stop_reason": None,
			"stop_sequence": None,
			"usage": make_usage(),
		},
	}
	content_block = message["content"][0]
	events: list[dict[str, Any]] = [message_start]

	if content_block["type"] == "tool_use":
		events.append(
			{
				"type": "content_block_start",
				"index": 0,
				"content_block": {
					"type": "tool_use",
					"id": content_block["id"],
					"name": content_block["name"],
					"input": {},
				},
			}
		)
		events.append(
			{
				"type": "content_block_delta",
				"index": 0,
				"delta": {
					"type": "input_json_delta",
					"partial_json": json_dumps(content_block.get("input", {})),
				},
			}
		)
	else:
		events.append(
			{
				"type": "content_block_start",
				"index": 0,
				"content_block": {
					"type": "text",
					"text": "",
				},
			}
		)
		for chunk in chunk_text(content_block.get("text", "")):
			events.append(
				{
					"type": "content_block_delta",
					"index": 0,
					"delta": {
						"type": "text_delta",
						"text": chunk,
					},
				}
			)

	events.append({"type": "content_block_stop", "index": 0})
	events.append(
		{
			"type": "message_delta",
			"delta": {
				"stop_reason": message["stop_reason"],
				"stop_sequence": None,
			},
			"usage": {"output_tokens": 0},
		}
	)
	events.append({"type": "message_stop"})
	return events


class BridgeHandler(BaseHTTPRequestHandler):
	server_version = "OllamaAnthropicBridge/0.1"
	protocol_version = "HTTP/1.1"

	@property
	def bridge(self) -> OllamaBridge:
		return self.server.bridge  # type: ignore[attr-defined]

	def do_HEAD(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path in {"", "/", "/health", "/healthz"}:
			self.send_response(HTTPStatus.OK.value)
			self.send_header("Connection", "close")
			self.end_headers()
			return
		self.send_response(HTTPStatus.NOT_FOUND.value)
		self.send_header("Connection", "close")
		self.end_headers()

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path in {"/", "/health", "/healthz"}:
			self._send_json(
				HTTPStatus.OK,
				{
					"ok": True,
					"model": self.bridge.model_name,
					"ollama_model": self.bridge.ollama_model,
					"ollama_base_url": self.bridge.ollama_base_url,
				},
			)
			return
		self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

	def do_POST(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path.rstrip("/") != "/v1/messages":
			self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
			return

		try:
			payload = self._read_json_body()
			message, _raw_text = self.bridge.generate(payload)
			if bool(payload.get("stream")):
				self._send_sse(make_sse_events(message))
			else:
				self._send_json(HTTPStatus.OK, message)
		except Exception as exc:
			traceback.print_exc()
			self._send_json(
				HTTPStatus.INTERNAL_SERVER_ERROR,
				{"error": {"type": "api_error", "message": str(exc)}},
			)

	def log_message(self, format: str, *args: Any) -> None:
		sys.stderr.write(f"[ollama-bridge] {format % args}\n")

	def _read_json_body(self) -> dict[str, Any]:
		content_length = int(self.headers.get("Content-Length", "0"))
		raw = self.rfile.read(content_length)
		if not raw:
			return {}
		return json.loads(raw.decode("utf-8"))

	def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status.value)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Connection", "close")
		self.end_headers()
		self.wfile.write(body)
		self.wfile.flush()

	def _send_sse(self, events: list[dict[str, Any]]) -> None:
		self.send_response(HTTPStatus.OK.value)
		self.send_header("Content-Type", "text/event-stream; charset=utf-8")
		self.send_header("Cache-Control", "no-cache")
		self.send_header("Connection", "close")
		self.end_headers()
		for event in events:
			payload = f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
			self.wfile.write(payload.encode("utf-8"))
			self.wfile.flush()


def main() -> None:
	args = parse_args()
	bridge = OllamaBridge(
		ollama_base_url=args.ollama_base_url,
		ollama_model=args.ollama_model,
		model_name=args.model_name,
	)
	server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
	server.bridge = bridge  # type: ignore[attr-defined]
	print(
		f"[ollama-bridge] Ready on http://{args.host}:{args.port} using Ollama model {args.ollama_model}",
		flush=True,
	)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print("[ollama-bridge] Shutting down", flush=True)


if __name__ == "__main__":
	main()
