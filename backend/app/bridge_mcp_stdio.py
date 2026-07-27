"""Bounded newline-delimited JSON-RPC transport for the CML MCP server."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import BinaryIO, Callable

MAX_STDIN_MESSAGE_BYTES = 1_048_576


def _bridge_defaults():
    # Lazy import avoids a module cycle while keeping the transport reusable.
    from backend.app import bridge_mcp

    return {
        "handler": bridge_mcp.handle_message,
        "error_factory": bridge_mcp.error,
        "application_error_type": bridge_mcp.CMLBridgeApplicationError,
        "application_error_response": bridge_mcp._application_error_response,
        "request_context": bridge_mcp._REQUEST_CONTEXT,
    }


def run_stdio(
    *,
    stdin: BinaryIO | None = None,
    handler: Callable | None = None,
    writer: Callable[[dict], None] | None = None,
    max_message_bytes: int = MAX_STDIN_MESSAGE_BYTES,
) -> int:
    stream = stdin or sys.stdin.buffer
    runtime = ConcurrentMCPRuntime(handler=handler, writer=writer)
    try:
        while True:
            raw_line = stream.readline(max_message_bytes + 1)
            if not raw_line:
                break
            if len(raw_line) > max_message_bytes:
                _discard_line_remainder(stream, max_message_bytes=max_message_bytes)
                runtime.write(runtime.error_factory(None, -32001, "MCP request is too large."))
                continue
            try:
                line = raw_line.decode("utf-8-sig")
            except UnicodeDecodeError:
                runtime.write(runtime.error_factory(None, -32700, "Invalid UTF-8 JSON request."))
                continue
            if not line.strip():
                continue
            try:
                runtime.dispatch(json.loads(line))
            except json.JSONDecodeError:
                runtime.write(runtime.error_factory(None, -32700, "Invalid JSON request."))
    finally:
        runtime.close()
    return 0


class ConcurrentMCPRuntime:
    def __init__(
        self,
        *,
        handler=None,
        writer=None,
        max_workers: int = 8,
        max_inflight: int = 16,
        error_factory=None,
        application_error_type=None,
        application_error_response=None,
        request_context=None,
    ):
        defaults = _bridge_defaults()
        self.handler = handler or defaults["handler"]
        self.writer = writer or self._stdout_writer
        self.error_factory = error_factory or defaults["error_factory"]
        self.application_error_type = application_error_type or defaults["application_error_type"]
        self.application_error_response = (
            application_error_response or defaults["application_error_response"]
        )
        self.request_context = request_context or defaults["request_context"]
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cml-mcp")
        self.capacity = threading.BoundedSemaphore(max_inflight)
        self.retrieval_capacity = threading.BoundedSemaphore(4)
        self.write_capacity = threading.BoundedSemaphore(2)
        self.lightweight_capacity = threading.BoundedSemaphore(8)
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.inflight = {}
        self.closed = False

    def dispatch(self, message) -> None:
        if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
            params = message.get("params") or {}
            request_id = params.get("requestId") if isinstance(params, dict) else None
            self.cancel(request_id)
            return
        if not isinstance(message, dict):
            self.write(self.error_factory(None, -32600, "Request must be a JSON object."))
            return
        request_id = message.get("id")
        if request_id is None:
            return
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int, float)):
            self.write(self.error_factory(None, -32600, "Request ID must be a string or number."))
            return
        with self.lock:
            if self.closed:
                return
            if request_id in self.inflight:
                self.write(
                    self.error_factory(request_id, -32600, "Duplicate in-flight request ID.")
                )
                return
            if not self.capacity.acquire(blocking=False):
                self.write(self._rate_limited_response(request_id))
                return
            call_capacity = self._capacity_for_message(message)
            if not call_capacity.acquire(blocking=False):
                self.capacity.release()
                self.write(self._rate_limited_response(request_id))
                return
            cancelled = RequestCancellation()
            future = self.executor.submit(self._invoke, message, cancelled)
            self.inflight[request_id] = (future, cancelled, call_capacity)
        future.add_done_callback(
            lambda completed, rid=request_id, marker=cancelled: self._complete(
                rid, completed, marker
            )
        )

    def cancel(self, request_id) -> None:
        with self.lock:
            active = self.inflight.get(request_id)
            if not active:
                return
            future, cancelled, _call_capacity = active
            cancelled.set()
            future.cancel()

    def _complete(self, request_id, future, cancelled) -> None:
        try:
            if cancelled.is_set():
                response = self.error_factory(request_id, -32800, "Request cancelled.")
                response["error"]["data"] = {
                    "error_code": "cancelled",
                    "retriable": True,
                    "correlation_id": str(request_id),
                }
            else:
                try:
                    response = future.result()
                except self.application_error_type as exc:
                    response = self.application_error_response(exc)
                except Exception:
                    response = self.error_factory(
                        request_id, -32603, "Internal bridge error."
                    )
            if response is not None:
                self.write(response)
        finally:
            with self.lock:
                active = self.inflight.get(request_id)
                if active and active[0] is future:
                    self.inflight.pop(request_id, None)
                    active[2].release()
                    self.capacity.release()

    def _invoke(self, message, cancellation):
        self.request_context.cancellation = cancellation
        try:
            if cancellation.is_set():
                return None
            return self.handler(message)
        finally:
            self.request_context.cancellation = None

    def write(self, response: dict) -> None:
        with self.write_lock:
            self.writer(response)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            active = list(self.inflight.values())
        for future, cancelled, _call_capacity in active:
            cancelled.set()
            future.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def _capacity_for_message(self, message):
        if message.get("method") != "tools/call":
            return self.lightweight_capacity
        params = message.get("params") or {}
        name = params.get("name") if isinstance(params, dict) else ""
        if name in {"get_cluster_context", "expand_context_item"}:
            return self.retrieval_capacity
        if name in {
            "log_external_turn",
            "capture_external_artifact",
            "decide_writeback_review",
        }:
            return self.write_capacity
        return self.lightweight_capacity

    def _rate_limited_response(self, request_id) -> dict:
        response = self.error_factory(
            request_id, -32006, "Too many requests. Try again shortly."
        )
        response["error"]["data"] = {
            "error_code": "rate_limited",
            "retriable": True,
            "correlation_id": str(request_id),
        }
        return response

    @staticmethod
    def _stdout_writer(response: dict) -> None:
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


class RequestCancellation:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.closers = []

    def is_set(self) -> bool:
        return self.event.is_set()

    def set(self) -> None:
        self.event.set()
        with self.lock:
            closers = list(self.closers)
        for closer in closers:
            try:
                closer()
            except Exception:
                pass

    def add_closer(self, closer) -> None:
        with self.lock:
            if self.event.is_set():
                closer()
            else:
                self.closers.append(closer)

    def remove_closer(self, closer) -> None:
        with self.lock:
            if closer in self.closers:
                self.closers.remove(closer)


def _discard_line_remainder(stream: BinaryIO, *, max_message_bytes: int) -> None:
    while True:
        chunk = stream.readline(max_message_bytes + 1)
        if not chunk or chunk.endswith(b"\n"):
            return


if __name__ == "__main__":
    raise SystemExit(run_stdio())
