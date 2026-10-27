import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("value,expected", [(None, 8), ("1", 1), ("2", 2), ("4", 4), ("8", 8)])
def test_client_limit_valid(monkeypatch, value, expected):
    from consumer_broker import configured_client_limit

    monkeypatch.delenv("MAX_MCP_CLIENTS", raising=False)
    if value is not None:
        monkeypatch.setenv("MAX_MCP_CLIENTS", value)
    assert configured_client_limit() == expected


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "", "9", "secret-environment-value", " 4", "4\n"])
def test_client_limit_invalid_startup(tmp_path, value):
    env = {**os.environ, "MAX_MCP_CLIENTS": value, "WHATSAPP_MCP_SOCKET": str(tmp_path / "mcp.sock")}
    source = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(source / "consumer_broker.py")], env=env, capture_output=True, timeout=10
    )
    assert result.returncode != 0
    assert b"Invalid MAX_MCP_CLIENTS: expected integer from 1 through 8" in result.stderr
    assert not (tmp_path / "mcp.sock").exists()
    assert not list(tmp_path.glob("wa-consumer-*"))
    assert b"secret-environment-value" not in result.stderr


def test_app_socket_acl_reapplied_on_new_inode(monkeypatch, tmp_path):
    import ctypes
    import socket

    from consumer_broker import apply_app_socket_acl

    monkeypatch.setenv("ALRIFAI_MCP_SOCKET_ACL", "uid10001")
    path = tmp_path / "mcp.sock"
    monkeypatch.setattr(os, "fsencode", lambda _: str(path).encode())
    acl = ctypes.CDLL("libacl.so.1")
    acl.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    acl.acl_get_file.restype = ctypes.c_void_p
    acl.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    acl.acl_to_text.restype = ctypes.c_void_p
    acl.acl_free.argtypes = [ctypes.c_void_p]
    for _ in range(2):
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(path))
        apply_app_socket_acl("/runtime/control/app-broker/mcp.sock")
        value = acl.acl_get_file(str(path).encode(), 0x8000)
        text = acl.acl_to_text(value, None)
        try:
            rendered = ctypes.string_at(text)
            assert b"user:10001:rw-" in rendered
            assert b"other::---" in rendered
        finally:
            acl.acl_free(text)
            acl.acl_free(value)
            server.close()
            path.unlink()


def test_app_acl_refuses_broad_or_wrong_path(monkeypatch):
    from consumer_broker import apply_app_socket_acl

    monkeypatch.setenv("ALRIFAI_MCP_SOCKET_ACL", "uid10001")
    with pytest.raises(SystemExit, match="Invalid application socket ACL"):
        apply_app_socket_acl("/runtime/control/mcp.sock")
    monkeypatch.setenv("ALRIFAI_MCP_SOCKET_ACL", "world")
    with pytest.raises(SystemExit, match="Invalid application socket ACL"):
        apply_app_socket_acl("/runtime/control/app-broker/mcp.sock")
