"""Offline synthetic reproductions at the pinned MCP/logger boundaries."""

import logging
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import mcp
import pytest
import requests
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import capabilities
import media_preview
from tests.test_capabilities import configure

PRIVATE = "SYNTHETIC_PHONE_LID_BODY_MEDIA_PATH_TOKEN_CREDENTIAL"


async def protocol_call(server, arguments):
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="get_message_context", arguments=arguments),
    )
    return await server._mcp_server.request_handlers[types.CallToolRequest](request)


def error_server(monkeypatch, server_type, error):
    server = server_type("synthetic-privacy")
    monkeypatch.setattr(server, "get_context", lambda: None)

    @server.tool()
    def get_message_context(message_id: str):
        raise error

    return server


@pytest.mark.asyncio
async def test_framework_baseline_exposes_error_in_response(monkeypatch):
    monkeypatch.delenv("WHATSAPP_AUTH_POLICY", raising=False)
    raw = error_server(monkeypatch, FastMCP, sqlite3.OperationalError(PRIVATE))
    result = await protocol_call(raw, {"message_id": "synthetic"})
    assert result.root.isError
    assert PRIVATE in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [sqlite3.OperationalError(PRIVATE), OSError(PRIVATE), requests.RequestException(PRIVATE)]
)
async def test_framework_tool_error_contained(monkeypatch, tmp_path, capsys, caplog, error):
    configure(monkeypatch, tmp_path, ["messages.read", "contacts.read"])
    server = error_server(monkeypatch, capabilities.CapabilityMCP, error)
    with caplog.at_level(logging.ERROR):
        result = await protocol_call(server, {"message_id": "synthetic"})
    assert result.root.isError
    assert "failed" in result.model_dump_json().lower()
    if isinstance(error, sqlite3.Error):
        assert "database operation failed" in result.model_dump_json()
    elif isinstance(error, requests.RequestException):
        assert "HTTP operation failed" in result.model_dump_json()
    else:
        assert "storage or file operation failed" in result.model_dump_json()
    assert PRIVATE not in result.model_dump_json() + caplog.text
    capture = capsys.readouterr()
    assert PRIVATE not in capture.out + capture.err
    assert "MCP tool call failed" in caplog.text


@pytest.mark.asyncio
async def test_framework_validation_error_redacts_input(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["messages.read", "contacts.read"])
    server = error_server(monkeypatch, capabilities.CapabilityMCP, AssertionError("must not execute"))
    result = await protocol_call(server, {"message_id": {"private": PRIVATE}})
    assert result.root.isError
    assert PRIVATE not in result.model_dump_json()
    assert "Invalid tool arguments" in result.model_dump_json()


@pytest.mark.asyncio
async def test_unauthorized_consumer_never_reaches_function(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, [])
    server = error_server(monkeypatch, capabilities.CapabilityMCP, AssertionError(PRIVATE))
    result = await protocol_call(server, {"message_id": PRIVATE})
    assert result.root.isError
    assert "capability" in result.model_dump_json()
    assert PRIVATE not in result.model_dump_json()
    with pytest.raises(PermissionError):
        await server.call_tool("get_message_context", {"message_id": PRIVATE})


@pytest.mark.parametrize("root", [False, True])
def test_framework_log_filter_redacts_payload_and_traceback(root):
    name = "root" if root else "mcp.server.lowlevel.server"
    pathname = str(Path(mcp.__file__).parent / "shared/session.py")
    record = logging.LogRecord(name, logging.ERROR, pathname, 1, f"Failed to validate request: {PRIVATE}", (), None)
    record.exc_text = PRIVATE
    record.stack_info = PRIVATE
    privacy = capabilities.FrameworkPrivacyFilter()
    assert privacy.filter(record)
    assert PRIVATE not in logging.Formatter("%(levelname)s %(message)s").format(record)
    assert record.levelno == logging.ERROR
    assert "MCP request validation failed" in record.getMessage()
    assert record.exc_text is None and record.stack_info is None


def test_media_error_omits_path_and_renderer_stderr(tmp_path, monkeypatch):
    source = tmp_path / PRIVATE
    with pytest.raises(media_preview.PreviewError) as missing:
        media_preview.render_preview(source)
    assert PRIVATE not in str(missing.value)
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(media_preview, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media_preview.subprocess, "run", Mock(return_value=Mock(returncode=1, stderr=PRIVATE.encode())))
    with pytest.raises(media_preview.PreviewError) as renderer:
        media_preview.render_preview(source)
    assert PRIVATE not in str(renderer.value)
    assert "renderer failed" in str(renderer.value)


@pytest.mark.asyncio
async def test_direct_framework_exception_is_safe(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["messages.read", "contacts.read"])
    server = error_server(monkeypatch, capabilities.CapabilityMCP, OSError(PRIVATE))
    with pytest.raises(ToolError) as failed:
        await server.call_tool("get_message_context", {"message_id": "synthetic"})
    assert PRIVATE not in str(failed.value)
    assert failed.value.__suppress_context__


def test_stdio_parse_and_exception_logs_are_private(monkeypatch, tmp_path):
    import json
    import os
    import select
    import subprocess
    import sys

    configure(monkeypatch, tmp_path, ["messages.read", "contacts.read"])
    probe = tmp_path / "stdio_probe.py"
    probe.write_text(
        "from capabilities import CapabilityMCP\n"
        "s = CapabilityMCP('synthetic-stdio')\n"
        "@s.tool()\n"
        "def get_message_context(message_id: str):\n"
        f"    raise OSError({PRIVATE!r})\n"
        "s.run()\n"
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "synthetic", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": [PRIVATE]}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_message_context", "arguments": {"message_id": "synthetic"}},
        },
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(capabilities.__file__).parent)
    process = subprocess.Popen(
        [sys.executable, str(probe)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    responses = []
    try:
        for message in messages:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            if "id" in message:
                while True:
                    ready, _, _ = select.select([process.stdout], [], [], 10)
                    assert ready, "stdio response deadline exceeded"
                    response = json.loads(process.stdout.readline())
                    responses.append(response)
                    if response.get("id") == message["id"]:
                        break
        remaining, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert process.returncode == 0
    assert PRIVATE not in json.dumps(responses) + remaining + stderr
    assert "MCP request validation failed" in stderr
    assert any(item.get("id") == 2 and "error" in item for item in responses)
    assert any(item.get("id") == 3 and item.get("result", {}).get("isError") for item in responses)
