"""Cancellable POSIX stdio runner using the pinned MCP transport API."""

import asyncio
import logging
import signal
import subprocess
from contextlib import suppress

import anyio
from mcp.server.stdio import stdio_server


class AsyncStdin:
    def __init__(self, reader):
        self.reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.reader.readline()
        if not line:
            raise StopAsyncIteration
        return line.decode("utf-8", errors="replace")


async def run_stdio(server, stdin=None):
    """Signals cancel the owning scope; EOF drains the SDK's normal lifecycle."""
    import sys

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, stdin or sys.stdin.buffer)
    loop.set_exception_handler(
        lambda _loop, _context: logging.getLogger("asyncio").error("Asyncio unexpected diagnostic")
    )
    installed = []
    previous = {}
    try:
        with anyio.CancelScope() as scope:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.getsignal(signum)
                loop.add_signal_handler(signum, scope.cancel)
                installed.append(signum)
            async with stdio_server(stdin=AsyncStdin(reader)) as (receive, send):
                await server._mcp_server.run(receive, send, server._mcp_server.create_initialization_options())
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)
            signal.signal(signum, previous[signum])
        transport.close()


def run_consumer(server):
    try:
        anyio.run(run_stdio, server)
    except BaseException:
        # Keep genuine failures visible and nonzero; never render traceback/context.
        logging.getLogger("mcp.consumer").error("MCP unexpected consumer failure")
        raise SystemExit(1) from None


def close_child(process, graceful=2, terminate=2, kill=2):
    """One worker owns teardown. Every wait is bounded, including the kill wait."""
    process.shutdown_escalated = False
    if process.stdin:
        with suppress(OSError, ValueError):
            process.stdin.close()
    for timeout, action in ((graceful, None), (terminate, process.terminate), (kill, process.kill)):
        if action and process.poll() is None:
            process.shutdown_escalated = True
            with suppress(ProcessLookupError):
                action()
        try:
            process.wait(timeout=timeout)
            return process.returncode
        except subprocess.TimeoutExpired:
            continue
    raise TimeoutError("Consumer reap deadline exceeded")
