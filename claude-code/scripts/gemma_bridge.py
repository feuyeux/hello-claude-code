#!/usr/bin/env python3
"""Anthropic Messages-compatible bridge for a local Gemma 4 checkpoint.

This lets the reconstructed Claude Code CLI talk to a locally hosted Gemma 4
model through `ANTHROPIC_BASE_URL`, without rewriting the CLI's main query
loop. The bridge accepts a small Anthropic Messages subset and maps it to a
single stateless Gemma prompt per request.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*\})\s*</tool_call>", re.DOTALL)
DEFAULT_MODEL_NAME = "gemma4"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


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
		"--variant",
		default=os.environ.get("GEMMA_VARIANT", "gemma4-e2b-it"),
		help="Gemma 4 variant to load: gemma4-e2b-it, gemma4-e4b-it, gemma4-31b-it, gemma4-26b-a4b-it.",
	)
	parser.add_argument(
		"--checkpoint",
		default=os.environ.get("GEMMA_CKPT_PATH"),
		help="Local checkpoint directory for the downloaded Gemma 4 weights.",
	)
	parser.add_argument(
		"--gemma-repo",
		default=os.environ.get("GEMMA_REPO_PATH"),
		help="Path to the cloned google-deepmind/gemma repository.",
	)
	return parser.parse_args()


def resolve_default_gemma_repo() -> Path | None:
	try:
		root = Path(__file__).resolve().parents[3]
	except IndexError:
		return None
	default_repo = root / "gemma"
	return default_repo if default_repo.exists() else None


def bootstrap_gemma_repo(repo_arg: str | None) -> Path:
	repo = Path(repo_arg).resolve() if repo_arg else resolve_default_gemma_repo()
	if repo is None or not repo.exists():
		raise RuntimeError(
			"Cannot locate the Gemma repository. Set GEMMA_REPO_PATH or pass --gemma-repo."
		)
	if str(repo) not in sys.path:
		sys.path.insert(0, str(repo))
	return repo


def require_checkpoint(path_value: str | None) -> str:
	if not path_value:
		raise RuntimeError(
			"Missing checkpoint path. Set GEMMA_CKPT_PATH or pass --checkpoint."
		)
	if path_value.startswith("gs://"):
		return path_value
	path = Path(path_value).expanduser().resolve()
	if not path.exists():
		raise RuntimeError(f"Gemma checkpoint path does not exist: {path}")
	return str(path)


def chunk_text(text: str, size: int = 96) -> list[str]:
	if not text:
		return [""]
	return [text[i : i + size] for i in range(0, len(text), size)]


def json_dumps(data: Any) -> str:
	return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


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
		return f"[Unsupported {block_type} content omitted by Gemma bridge]"
	return json_dumps(block)


def build_prompt(payload: dict[str, Any], model_name: str) -> str:
	system_text = normalize_system(payload.get("system"))
	tools = payload.get("tools") or []
	messages = payload.get("messages") or []

	sections: list[str] = [
		f"You are {model_name}, reached through an Anthropic Messages compatibility bridge.",
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


@dataclass
class BridgeResult:
	message: dict[str, Any]
	raw_text: str


class GemmaBridge:
	def __init__(self, *, variant: str, checkpoint: str, model_name: str):
		self.variant = variant
		self.checkpoint = checkpoint
		self.model_name = model_name
		self._lock = threading.Lock()
		self._sampler = self._load_sampler()

	def _load_sampler(self) -> Any:
		from gemma import gm

		variant_key = self.variant.strip().lower()
		model_factories = {
			"gemma4-e2b-it": lambda: gm.nn.Gemma4_E2B(text_only=True),
			"gemma4-e4b-it": lambda: gm.nn.Gemma4_E4B(text_only=True),
			"gemma4-31b-it": lambda: gm.nn.Gemma4_31B(text_only=True),
			"gemma4-26b-a4b-it": lambda: gm.nn.Gemma4_26B_A4B(text_only=True),
		}
		if variant_key not in model_factories:
			raise RuntimeError(f"Unsupported Gemma variant: {self.variant}")

		print(
			f"[gemma-bridge] Loading {self.variant} from {self.checkpoint}",
			flush=True,
		)
		model = model_factories[variant_key]()
		params = gm.ckpts.load_params(self.checkpoint, text_only=True)
		return gm.text.ChatSampler(model=model, params=params, multi_turn=False)

	def generate(self, payload: dict[str, Any]) -> BridgeResult:
		prompt = build_prompt(payload, self.model_name)
		max_new_tokens = int(payload.get("max_tokens") or 1024)

		with self._lock:
			raw_text = self._sampler.chat(
				prompt,
				max_new_tokens=max_new_tokens,
				multi_turn=False,
			)

		message = self._message_from_text(raw_text)
		return BridgeResult(message=message, raw_text=raw_text)

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
	server_version = "GemmaAnthropicBridge/0.1"
	protocol_version = "HTTP/1.1"

	@property
	def bridge(self) -> GemmaBridge:
		return self.server.bridge  # type: ignore[attr-defined]

	def do_GET(self) -> None:
		if self.path in {"/health", "/healthz"}:
			self._send_json(HTTPStatus.OK, {"ok": True, "model": self.bridge.model_name})
			return
		self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

	def do_POST(self) -> None:
		if self.path.rstrip("/") != "/v1/messages":
			self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
			return

		try:
			payload = self._read_json_body()
			result = self.bridge.generate(payload)
			if bool(payload.get("stream")):
				self._send_sse(make_sse_events(result.message))
			else:
				self._send_json(HTTPStatus.OK, result.message)
		except Exception as exc:  # pragma: no cover - bridge errors are surfaced to caller
			traceback.print_exc()
			self._send_json(
				HTTPStatus.INTERNAL_SERVER_ERROR,
				{
					"error": {
						"type": "api_error",
						"message": str(exc),
					}
				},
			)

	def log_message(self, format: str, *args: Any) -> None:
		sys.stderr.write(f"[gemma-bridge] {format % args}\n")

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
	bootstrap_gemma_repo(args.gemma_repo)
	checkpoint = require_checkpoint(args.checkpoint)
	bridge = GemmaBridge(
		variant=args.variant,
		checkpoint=checkpoint,
		model_name=args.model_name,
	)

	server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
	server.bridge = bridge  # type: ignore[attr-defined]
	print(
		f"[gemma-bridge] Ready on http://{args.host}:{args.port} using {args.model_name}",
		flush=True,
	)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print("[gemma-bridge] Shutting down", flush=True)


if __name__ == "__main__":
	main()
