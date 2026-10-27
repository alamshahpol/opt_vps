"""Trusted service-side consumer policy. Client tool arguments cannot change grants."""

import functools
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import stat
import sys
import threading
from pathlib import Path

import mcp
import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

TOOL_CAPABILITIES = {
    "search_contacts": {"contacts.read"},
    "get_contact": {"contacts.read"},
    "list_messages": {"messages.read", "contacts.read"},
    "list_chats": {"messages.read"},
    "get_chat": {"messages.read"},
    "get_direct_chat_by_contact": {"messages.read"},
    "get_contact_chats": {"messages.read", "contacts.read"},
    "get_last_interaction": {"messages.read", "contacts.read"},
    "get_message_context": {"messages.read", "contacts.read"},
    "send_message": {"messages.send"},
    "send_file": {"media.send"},
    "send_audio_message": {"media.send"},
    "send_reaction": {"reactions.send"},
    "mark_messages_read": {"receipts.write"},
    "download_media": {"media.download"},
    "view_media": {"media.read", "media.download"},
    "transcribe_audio": {"audio.transcribe", "media.download"},
    "list_calls": {"calls.read"},
    "get_native_account_identity": {"native.identity.read"},
    "list_native_events": {"native.events.read"},
    "list_native_messages": {"native.events.read", "native.content.read"},
    "set_typing": {"typing.send"},
    "request_history": {"history.request"},
}

TOOL_CAPABILITY_ALTERNATIVES = {
    "get_contact": ({"contacts.read"}, {"native.events.read", "native.contacts.read"}),
}


def tool_is_granted(name: str, scopes: set[str]) -> bool:
    alternatives = TOOL_CAPABILITY_ALTERNATIVES.get(name)
    if alternatives is not None:
        return any(required <= scopes for required in alternatives)
    return TOOL_CAPABILITIES.get(name, {"unsupported"}) <= scopes


def private_text(path: str) -> str:
    target = Path(path)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o027:
        raise PermissionError("Consumer configuration must be private and not group writable")
    return target.read_text()


def consumer_token() -> str:
    return private_text(os.environ["WHATSAPP_CONSUMER_TOKEN_FILE"]).strip()


def grants() -> set[str] | None:
    policy_path = os.getenv("WHATSAPP_AUTH_POLICY")
    if not policy_path:
        return None  # Preserve upstream compatibility; secured launcher requires a policy.
    try:
        digest = hashlib.sha256(consumer_token().encode()).hexdigest()
        policy = json.loads(private_text(policy_path))
        for consumer in policy["consumers"]:
            if (
                consumer["id"] == os.environ["WHATSAPP_CONSUMER_ID"]
                and consumer["account"] == os.environ["WHATSAPP_ACCOUNT_ALIAS"]
                and hmac.compare_digest(digest, consumer["token_sha256"])
            ):
                return set(consumer["capabilities"])
    except (OSError, KeyError, ValueError, TypeError):
        pass
    raise PermissionError("Consumer authentication failed")


def require_tool(name: str) -> None:
    scopes = grants()
    if scopes is not None and not tool_is_granted(name, scopes):
        raise PermissionError("Consumer lacks the required capability")


_PRIVATE_RECORD = object()


class FrameworkPrivacyFilter(logging.Filter):
    """Contain framework diagnostics, including root logs from mcp.shared.session."""

    def filter(self, record):
        if getattr(record, "_framework_private", None) is _PRIVATE_RECORD:
            return True
        framework_path = str(Path(mcp.__file__).parent) + os.sep
        if (
            record.name.startswith("mcp.")
            or record.name in {"mcp", "asyncio"}
            or record.pathname.startswith(framework_path)
        ):
            # Never render args/exception/stack fields: they may contain request data.
            message = record.msg if isinstance(record.msg, str) else ""
            categories = {
                "Received exception from stream:": "MCP stream receive failed",
                "Failed to validate request:": "MCP request validation failed",
                "Failed to validate notification:": "MCP notification validation failed",
                "Unhandled exception in receive loop:": "MCP receive loop failed",
                "Progress callback raised an exception:": "MCP progress callback failed",
                "Processing request of type": "MCP request processing",
                "Warning:": "MCP framework warning",
                "MCP unexpected consumer failure": "MCP unexpected consumer failure",
            }
            record.msg = (
                next(
                    (safe for prefix, safe in categories.items() if message.startswith(prefix)),
                    "Asyncio unexpected diagnostic" if record.name == "asyncio" else "MCP framework diagnostic",
                )
                + " (details redacted)"
            )
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            record._framework_private = _PRIVATE_RECORD
        return True


_ORIGINAL_HANDLER_HANDLE = logging.Handler.handle


def _private_handle(handler, record):
    if getattr(record, "_diagnostic_private", None) is _PRIVATE_RECORD:
        return _ORIGINAL_HANDLER_HANDLE(handler, record)
    framework = (
        record.name.startswith("mcp")
        or record.name == "asyncio"
        or record.pathname.startswith(str(Path(mcp.__file__).parent) + os.sep)
    )
    # Sanitize at emission, including handlers added/reconfigured after startup.
    FrameworkPrivacyFilter().filter(record)
    if not framework:
        if record.name == __name__ and record.msg == "MCP tool call failed: %s":
            safe = {
                "Invalid tool arguments",
                "Invalid tool arguments: Input should be a valid integer",
                "Tool database operation failed",
                "Tool HTTP operation failed",
                "Tool storage or file operation failed",
                "Tool execution failed",
            }
            category = record.args[0] if isinstance(record.args, tuple) and len(record.args) == 1 else ""
            record.msg = "MCP tool call failed: " + (category if category in safe else "Tool execution failed")
        else:
            record.msg = "Python application diagnostic (details redacted)"
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
    # Custom formatters must not expose source paths or arbitrary extra fields.
    for key in list(record.__dict__):
        if key not in _STANDARD_RECORD_FIELDS and key != "_framework_private":
            del record.__dict__[key]
    record.__dict__.pop("message", None)
    record.__dict__.pop("asctime", None)
    record._diagnostic_private = _PRIVATE_RECORD
    record.pathname = record.filename = "python"
    record.module = record.funcName = "runtime"
    record.threadName = "worker"
    record.processName = "consumer"
    record.levelname = next(
        (
            name
            for floor, name in ((50, "CRITICAL"), (40, "ERROR"), (30, "WARNING"), (20, "INFO"), (10, "DEBUG"))
            if record.levelno >= floor
        ),
        "DEBUG",
    )
    record.name = "asyncio" if record.name == "asyncio" else "mcp" if record.name.startswith("mcp") else "application"
    return _ORIGINAL_HANDLER_HANDLE(handler, record)


_STANDARD_RECORD_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def install_diagnostic_privacy():
    logging.Handler.handle = _private_handle
    sys.excepthook = lambda *_args: print("ERROR Python unhandled exception (details redacted)", file=sys.stderr)
    threading.excepthook = lambda _args: print("ERROR Python thread failure (details redacted)", file=sys.stderr)


class CapabilityMCP(FastMCP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        install_diagnostic_privacy()
        for handler in logging.getLogger().handlers:
            if not any(isinstance(item, FrameworkPrivacyFilter) for item in handler.filters):
                handler.addFilter(FrameworkPrivacyFilter())

    def tool(self, *args, **kwargs):
        register = super().tool(*args, **kwargs)

        def decorator(function):
            @functools.wraps(function)
            def guarded(*args, **kwargs):
                require_tool(function.__name__)
                return function(*args, **kwargs)

            return register(guarded)

        return decorator

    async def list_tools(self):
        tools = await super().list_tools()
        scopes = grants()
        return tools if scopes is None else [tool for tool in tools if tool_is_granted(tool.name, scopes)]

    async def call_tool(self, name: str, arguments: dict):
        require_tool(name)
        try:
            return await super().call_tool(name, arguments)
        except Exception as exc:
            cause = exc.__cause__ if isinstance(exc, ToolError) else exc
            if isinstance(cause, ValidationError):
                category = "Invalid tool arguments"
                if any(item["type"] == "int_type" for item in cause.errors(include_input=False)):
                    category += ": Input should be a valid integer"
            elif isinstance(cause, sqlite3.Error):
                category = "Tool database operation failed"
            elif isinstance(cause, requests.RequestException):
                category = "Tool HTTP operation failed"
            elif isinstance(cause, OSError):
                category = "Tool storage or file operation failed"
            else:
                category = "Tool execution failed"
            logging.getLogger(__name__).error("MCP tool call failed: %s", category)
            raise ToolError(category) from None
