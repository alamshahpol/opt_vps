"""Private Unix-socket authentication and per-connection stdio MCP lifecycle.

The peer receives only its granted MCP protocol. No command, environment,
consumer ID or filesystem path is accepted from the peer. No Docker access.
"""

import hashlib
import hmac
import io
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from capabilities import install_diagnostic_privacy, private_text
from consumer_lifecycle import close_child

MAX_AUTH_BYTES = 512
CHILDREN = {}
CHILD_LOCK = threading.Lock()
STOPPING = threading.Event()
PEERS = set()
WORKERS = set()


def configured_client_limit() -> int:
    """Explicit invalid settings fail closed without echoing configuration."""
    value = os.environ.get("MAX_MCP_CLIENTS", "8")
    if not re.fullmatch(r"[1-8]", value):
        raise SystemExit("Invalid MAX_MCP_CLIENTS: expected integer from 1 through 8")
    return int(value)


def authenticate(token: str) -> str:
    if len(token) < 16:
        raise PermissionError("Invalid consumer")
    digest = hashlib.sha256(token.encode()).hexdigest()
    policy = json.loads(private_text(os.environ["WHATSAPP_AUTH_POLICY"]))
    for consumer in policy["consumers"]:
        if consumer["account"] == os.environ["WHATSAPP_ACCOUNT_ALIAS"] and hmac.compare_digest(
            digest, consumer["token_sha256"]
        ):
            return consumer["id"]
    raise PermissionError("Invalid consumer")


def serve_peer(peer: socket.socket):
    process = None
    token_path = None
    threads = []
    try:
        if STOPPING.is_set():
            return
        peer.settimeout(5)
        # Read exactly one bounded authentication line, preserving the following MCP bytes.
        data = bytearray()
        while len(data) <= MAX_AUTH_BYTES:
            byte = peer.recv(1)
            if not byte:
                return
            if byte == b"\n":
                break
            data.extend(byte)
        else:
            return
        token = data.decode()
        consumer_id = authenticate(token)
        with tempfile.NamedTemporaryFile(mode="w", prefix="wa-consumer-", delete=False) as secret:
            secret.write(token)
            token_path = secret.name
        env = os.environ.copy()
        env.pop("WHATSAPP_BRIDGE_TOKEN", None)
        env.update(
            WHATSAPP_CONSUMER_ID=consumer_id, WHATSAPP_CONSUMER_TOKEN_FILE=token_path, WHATSAPP_MCP_TRANSPORT="stdio"
        )
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("main.py"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        with CHILD_LOCK:
            CHILDREN[process] = (token_path, peer)
        peer.settimeout(None)
        os.set_blocking(process.stdin.fileno(), False)

        def output():
            try:
                while chunk := os.read(process.stdout.fileno(), 65536):
                    peer.sendall(chunk)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def diagnostics():
            try:
                with io.BufferedReader(process.stderr) as stream:
                    while line := stream.readline(8192):
                        # Rich wraps one diagnostic over several indented lines.
                        # Do not promote those continuation lines to new ERRORs.
                        if line[:1].isspace():
                            continue
                        match = re.search(rb"^(?:\[[0-9/ :]+\]\s+)?(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG)\b", line)
                        severity = match[1].decode("ascii") if match else "ERROR"
                        print(f"{severity} MCP child stderr diagnostic (details redacted)", file=sys.stderr)
            except (OSError, ValueError):
                pass

        for target in (output, diagnostics):
            thread = threading.Thread(target=target, daemon=True)
            threads.append(thread)
            thread.start()
        while chunk := peer.recv(65536):
            pending = memoryview(chunk)
            deadline = time.monotonic() + 5
            while pending:
                if STOPPING.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("Consumer input deadline exceeded")
                if select.select([], [process.stdin], [], 0.1)[1]:
                    try:
                        pending = pending[os.write(process.stdin.fileno(), pending) :]
                    except BlockingIOError:
                        continue
    except (OSError, ValueError, KeyError, PermissionError):
        pass  # Authentication errors never echo credentials or peer data.
    finally:
        try:
            peer.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        peer.close()
        try:
            if process is not None:
                try:
                    status = close_child(process)
                    if status:
                        severity = (
                            "WARNING"
                            if process.shutdown_escalated and status in {-signal.SIGTERM, -signal.SIGKILL}
                            else "ERROR"
                        )
                        print(f"{severity} MCP consumer unexpected or forced exit (details redacted)", file=sys.stderr)
                except (OSError, TimeoutError):
                    print("ERROR MCP consumer cleanup failed (details redacted)", file=sys.stderr)
                finally:
                    for thread in threads:
                        thread.join(timeout=1)
                    for pipe in (process.stdin, process.stdout, process.stderr):
                        if pipe:
                            try:
                                pipe.close()
                            except OSError:
                                pass
        finally:
            with CHILD_LOCK:
                CHILDREN.pop(process, None)
            if token_path:
                try:
                    Path(token_path).unlink(missing_ok=True)
                except OSError:
                    print("ERROR MCP consumer token cleanup failed (details redacted)", file=sys.stderr)


def apply_app_socket_acl(path):
    """Opt-in named ACL on a socket in a dedicated socket-only directory.

    Directory traversal/mount is provisioned separately by the approved operator.
    Reapply to every new inode, before listen; never expose a TCP endpoint.
    """
    selected = os.environ.get("ALRIFAI_MCP_SOCKET_ACL")
    if selected is None:
        return
    if selected != "uid10001" or path != "/runtime/control/app-broker/mcp.sock":
        raise SystemExit("Invalid application socket ACL configuration")
    import ctypes

    acl = ctypes.CDLL("libacl.so.1", use_errno=True)
    acl.acl_from_text.argtypes = [ctypes.c_char_p]
    acl.acl_from_text.restype = ctypes.c_void_p
    acl.acl_set_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    acl.acl_free.argtypes = [ctypes.c_void_p]
    value = acl.acl_from_text(b"u::rw-,u:10001:rw-,g::rw-,m::rw-,o::---")
    if not value:
        raise SystemExit("Application socket ACL unavailable")
    try:
        if acl.acl_set_file(os.fsencode(path), 0x8000, value) != 0:
            raise SystemExit("Application socket ACL unavailable")
    finally:
        acl.acl_free(value)


def main():
    peer_limit = threading.BoundedSemaphore(configured_client_limit())
    path = os.environ["WHATSAPP_MCP_SOCKET"]
    if not Path(path).is_absolute():
        raise SystemExit("MCP socket must be absolute")
    # Fail if an endpoint exists. Do not replace a possibly active broker.
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    os.chmod(path, 0o660)
    apply_app_socket_acl(path)
    server.listen(8)

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        try:
            server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                peer, _ = server.accept()
            except OSError:
                if stopping:
                    break
                raise
            if not peer_limit.acquire(blocking=False):
                peer.close()
                print("INFO MCP admission capacity reached (details redacted)", file=sys.stderr)
                continue

            def worker(connection=peer):
                try:
                    serve_peer(connection)
                finally:
                    with CHILD_LOCK:
                        PEERS.discard(connection)
                        WORKERS.discard(threading.current_thread())
                    peer_limit.release()

            thread = threading.Thread(target=worker, daemon=True)
            with CHILD_LOCK:
                PEERS.add(peer)
                WORKERS.add(thread)
            thread.start()
    finally:
        STOPPING.set()
        server.close()
        with CHILD_LOCK:
            peers, workers = list(PEERS), list(WORKERS)
        for peer in peers:
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
        deadline = time.monotonic() + 10
        for thread in workers:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in workers):
            print("ERROR MCP broker cleanup deadline exceeded", file=sys.stderr)
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    install_diagnostic_privacy()
    main()
