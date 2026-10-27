"""Real network-free Unix broker concurrency with isolated synthetic policy."""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

TOKEN = "synthetic-offline-only-reader-token"


def rpc(peer, stream, sequence, method, params):
    peer.sendall(json.dumps({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}).encode() + b"\n")
    while True:
        line = stream.readline()
        assert line
        message = json.loads(line)
        if message.get("id") == sequence:
            return message


def connect(path):
    peer = socket.socket(socket.AF_UNIX)
    peer.settimeout(15)
    peer.connect(str(path))
    peer.sendall(TOKEN.encode() + b"\n")
    stream = peer.makefile("rb")
    assert "result" in rpc(
        peer,
        stream,
        1,
        "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "synthetic", "version": "1"}},
    )
    peer.sendall(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    return peer, stream


def close(connection):
    peer, stream = connection
    peer.shutdown(socket.SHUT_RDWR)
    stream.close()
    peer.close()


def test_clients_excess_rejected_races_and_repeated_cleanup(tmp_path, cap=8):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "consumers": [
                    {
                        "id": "reader",
                        "account": "synthetic",
                        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                        "capabilities": [
                            "messages.read",
                            "contacts.read",
                            "media.read",
                            "media.download",
                            "calls.read",
                        ],
                    }
                ]
            }
        )
    )
    policy.chmod(0o600)
    endpoint = tmp_path / "mcp.sock"
    source = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "WHATSAPP_AUTH_POLICY": str(policy),
        "WHATSAPP_ACCOUNT_ALIAS": "synthetic",
        "WHATSAPP_MCP_SOCKET": str(endpoint),
        "TMPDIR": str(tmp_path),
        **({"MAX_MCP_CLIENTS": "4"} if cap == 4 else {}),
        "WHATSAPP_DB_PATH": str(tmp_path / "messages.db"),
        "WHATSMEOW_DB_PATH": str(tmp_path / "whatsapp.db"),
    }
    broker = subprocess.Popen(
        [sys.executable, str(source / "consumer_broker.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    clients = []
    child_pids = set()
    try:
        deadline = time.monotonic() + 10
        while not endpoint.exists():
            assert broker.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        baseline_fds = len(list(Path(f"/proc/{broker.pid}/fd").iterdir()))
        for _ in range(cap):
            clients.append(connect(endpoint))
        for connection in clients:
            peer, stream = connection
            result = rpc(peer, stream, 2, "tools/list", {})
            assert len(result["result"]["tools"]) == 12
            denied = rpc(peer, stream, 3, "tools/call", {"name": "set_typing", "arguments": {}})
            assert "error" in denied or denied["result"]["isError"]
        child_pids.update(
            int(x)
            for task in Path(f"/proc/{broker.pid}/task").iterdir()
            for x in (task / "children").read_text().split()
        )
        assert len(child_pids) == cap
        ninth = socket.socket(socket.AF_UNIX)
        ninth.settimeout(3)
        ninth.connect(str(endpoint))
        assert ninth.recv(1) == b""
        ninth.close()
        close(clients.pop())
        deadline = time.monotonic() + 6
        while len(list(tmp_path.glob("wa-consumer-*"))) == cap:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert "result" in rpc(*clients[0], 4, "tools/list", {})
        for _ in range(3):
            connection = connect(endpoint)
            close(connection)
            deadline = time.monotonic() + 6
            while len(list(tmp_path.glob("wa-consumer-*"))) > cap - 1:
                assert time.monotonic() < deadline
                time.sleep(0.05)
        for connection in clients:
            close(connection)
        clients.clear()
        deadline = time.monotonic() + 8
        while list(tmp_path.glob("wa-consumer-*")) or len(list(Path(f"/proc/{broker.pid}/task").iterdir())) > 1:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert len(list(Path(f"/proc/{broker.pid}/fd").iterdir())) == baseline_fds
        assert all(not Path(f"/proc/{pid}").exists() for pid in child_pids)
        for _ in range(cap):
            clients.append(connect(endpoint))
        child_pids.update(
            int(x)
            for task in Path(f"/proc/{broker.pid}/task").iterdir()
            for x in (task / "children").read_text().split()
        )
        # Stop while peers are active. The worker alone owns each child's teardown.
        broker.send_signal(signal.SIGTERM)
        broker.wait(timeout=12)
        assert broker.returncode == 0
        assert not endpoint.exists()
        assert not list(tmp_path.glob("wa-consumer-*"))
        assert all(not Path(f"/proc/{pid}").exists() for pid in child_pids)
        diagnostics = broker.stderr.read()
        assert TOKEN.encode() not in diagnostics
        assert b"ERROR" not in diagnostics
    finally:
        for connection in clients:
            try:
                close(connection)
            except OSError:
                pass
        if broker.poll() is None:
            broker.send_signal(signal.SIGTERM)
            broker.wait(timeout=12)
        broker.stdout.close()
        broker.stderr.close()


def test_direct_child_stderr_unexpected_exit_and_pipe_cleanup(tmp_path, monkeypatch, capsys):
    import threading

    import consumer_broker as broker

    private = "SYNTHETIC_BODY_AUTH_HEADER_ENV_MEDIA_URL_PATH"
    source = Path(broker.__file__)
    (tmp_path / "consumer_broker.py").write_text(source.read_text())
    (tmp_path / "main.py").write_text(f"import sys\nprint({private!r},file=sys.stderr)\nraise SystemExit(7)\n")
    monkeypatch.setattr(broker, "__file__", str(tmp_path / "consumer_broker.py"))
    monkeypatch.setattr(broker, "authenticate", lambda _token: "synthetic")
    monkeypatch.setattr(broker.tempfile, "tempdir", str(tmp_path))
    broker.STOPPING.clear()
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(broker.subprocess, "Popen", spawn)
    client, server = socket.socketpair()
    client.sendall(TOKEN.encode() + b"\n")
    worker = threading.Thread(target=broker.serve_peer, args=(server,))
    worker.start()
    worker.join(timeout=10)
    client.close()
    assert not worker.is_alive()
    assert len(children) == 1 and children[0].returncode == 7
    assert all(pipe.closed for pipe in (children[0].stdin, children[0].stdout, children[0].stderr))
    assert not broker.CHILDREN and not list(tmp_path.glob("wa-consumer-*"))
    diagnostics = capsys.readouterr().err
    assert private not in diagnostics
    assert "ERROR" in diagnostics


def test_four_clients_fifth_rejected(tmp_path):
    test_clients_excess_rejected_races_and_repeated_cleanup(tmp_path, 4)
