"""Synthetic process, signal, diagnostic and cleanup regressions."""

import asyncio
import io
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from capabilities import CapabilityMCP
from consumer_lifecycle import close_child

SECRET = "SYNTHETIC_AUTHORIZATION_BODY_TASK_PATH_TOKEN"


@pytest.mark.parametrize("mode", ["eof", "term", "kill", "exited"])
def test_bounded_process_cleanup(mode):
    code = {
        "eof": "import sys; sys.stdin.read()",
        "term": "import time; time.sleep(30)",
        "kill": "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(30)",
        "exited": "pass",
    }[mode]
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        if mode == "kill":
            assert child.stdout.readline() == b"ready\n"
        if mode == "exited":
            child.wait(timeout=3)
        close_child(child, graceful=0.2, terminate=0.2, kill=2)
        assert child.poll() is not None
        assert child.stdin.closed
        if mode == "kill":
            assert child.returncode == -signal.SIGKILL
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        child.stdout.close()


@pytest.mark.parametrize("ending", ["eof", "term", "int"])
def test_real_pinned_stdio_shutdown(tmp_path, ending):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from capabilities import CapabilityMCP\nfrom consumer_lifecycle import run_consumer\nrun_consumer(CapabilityMCP('offline'))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    env.pop("WHATSAPP_AUTH_POLICY", None)
    child = subprocess.Popen(
        [sys.executable, str(probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    try:
        # An initialize reply establishes that async signal handlers are installed.
        child.stdin.write(
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"offline","version":"1"}}}\n'
        )
        child.stdin.flush()
        import select

        assert select.select([child.stdout], [], [], 10)[0]
        assert b'"id":1' in child.stdout.readline()
        if ending == "eof":
            child.stdin.close()
        else:
            child.send_signal(signal.SIGTERM if ending == "term" else signal.SIGINT)
        child.wait(timeout=5)
        assert child.returncode == 0
        assert b"ERROR" not in child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        for pipe in (child.stdin, child.stdout, child.stderr):
            pipe.close()


@pytest.mark.asyncio
async def test_new_handler_asyncio_context_and_nested_groups():
    CapabilityMCP("privacy")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(pathname)s %(message)s"))
    logger = logging.getLogger("asyncio")
    logger.addHandler(handler)
    try:
        task = asyncio.current_task()
        old_name = task.get_name()
        task.set_name(SECRET)
        group = ExceptionGroup(SECRET, [ValueError(SECRET), ExceptionGroup(SECRET, [RuntimeError(SECRET)])])
        asyncio.get_running_loop().default_exception_handler(
            {"message": SECRET, "exception": group, "task": asyncio.current_task(), "private": SECRET}
        )
        logger.error(SECRET, exc_info=group, stack_info=True, extra={"authorization": SECRET})
        assert SECRET not in stream.getvalue()
        assert "ERROR" in stream.getvalue()
        assert "Asyncio unexpected diagnostic" in stream.getvalue()
    finally:
        task.set_name(old_name)
        logger.removeHandler(handler)


def test_signal_during_inflight_read_request(tmp_path):
    import json
    import select
    import time

    marker = tmp_path / "started"
    probe = tmp_path / "active.py"
    probe.write_text(
        "import time\nfrom pathlib import Path\nfrom capabilities import CapabilityMCP\n"
        "from consumer_lifecycle import run_consumer\ns=CapabilityMCP('offline')\n@s.tool()\n"
        "def list_chats():\n"
        f" Path({str(marker)!r}).touch()\n"
        " time.sleep(0.3)\n return []\nrun_consumer(s)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    env.pop("WHATSAPP_AUTH_POLICY", None)
    child = subprocess.Popen(
        [sys.executable, str(probe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    try:
        child.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "offline", "version": "1"},
                    },
                }
            ).encode()
            + b"\n"
        )
        child.stdin.flush()
        assert select.select([child.stdout], [], [], 10)[0]
        child.stdout.readline()
        child.stdin.write(
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_chats","arguments":{}}}\n'
        )
        child.stdin.flush()
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        child.send_signal(signal.SIGTERM)
        child.wait(timeout=5)
        assert child.returncode == 0
        assert b"ERROR" not in child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        for pipe in (child.stdin, child.stdout, child.stderr):
            pipe.close()


def test_handler_reconfiguration_application_args_and_severity():
    CapabilityMCP("privacy")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger(SECRET)
    logger.addHandler(handler)
    try:
        logger.error(
            "Authorization: Bearer %s",
            SECRET,
            exc_info=(ValueError, ValueError(SECRET), None),
            extra={"request": SECRET},
        )
        assert SECRET not in stream.getvalue()
        assert "diagnostic" in stream.getvalue()
    finally:
        logger.removeHandler(handler)


def test_pipe_close_error_and_repeated_cleanup():
    class BrokenPipe:
        def close(self):
            raise OSError("synthetic pipe failure")

    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], stdin=subprocess.PIPE)
    pipe = child.stdin
    child.stdin = BrokenPipe()
    try:
        close_child(child, graceful=0.1, terminate=1, kill=1)
        close_child(child, graceful=0.1, terminate=1, kill=1)
        assert child.poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
    finally:
        pipe.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)


def test_client_auth_timeout_cleans_peer(monkeypatch):
    from unittest.mock import Mock

    import consumer_broker

    peer = Mock()
    peer.recv.side_effect = TimeoutError("synthetic timeout")
    consumer_broker.STOPPING.clear()
    consumer_broker.serve_peer(peer)
    peer.settimeout.assert_called_once_with(5)
    peer.close.assert_called_once()
    assert not consumer_broker.CHILDREN
