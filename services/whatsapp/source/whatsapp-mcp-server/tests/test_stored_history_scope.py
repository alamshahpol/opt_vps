"""Exact group admission and participant privacy, using the existing reader contract."""

import importlib.util
import sqlite3
import sys
import threading
import types
from pathlib import Path

import pytest


def module(monkeypatch, principal, account="wa-01"):
    class DeniedError(ValueError):
        pass

    db_uri = f"file:scope-{id(principal)}?mode=memory&cache=shared"
    db = sqlite3.connect(db_uri, uri=True, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE p1_privacy_barriers(chat_jid text,message_id text)")
    reader = types.SimpleNamespace(account=account, binding={}, deadline=1, _slot=threading.Lock())
    reader._principal = lambda chat: principal

    def open_db(deadline):
        connection = sqlite3.connect(db_uri, uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    reader._db = open_db
    monkeypatch.setitem(
        sys.modules, "native_reader", types.SimpleNamespace(_reader=reader, NativeReadError=DeniedError)
    )
    path = Path(__file__).resolve().parents[1] / "stored_history_reader.py"
    spec = importlib.util.spec_from_file_location("scope_test_history", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded, reader, db, DeniedError


def test_exact_group_and_current_participant(monkeypatch):
    chat = "120363408741101070@g.us"
    p = types.SimpleNamespace(content=True, participants=((chat, frozenset({"fixture-admin"})),))
    history, reader, db, denied = module(monkeypatch, p)
    row = {
        "id": "fixture",
        "sender": "outsider",
        "content": "private",
        "deleted_at": None,
        "timestamp": "2026-10-15T00:00:00Z",
        "is_from_me": False,
    }
    proof, body = history._message(reader, db, chat, row)
    assert proof["state"] == "UNKNOWN" and body is None
    proof, body = history._message(reader, db, chat, {**row, "sender": "fixture-admin"})
    assert proof["state"] == "VISIBLE" and body["sender"] == "fixture-admin"
    with pytest.raises(denied, match="GROUP_SCOPE_DENIED"):
        history._read("999999@g.us", lambda *_: None)
    reader.account = "wa-02"
    with pytest.raises(denied, match="GROUP_SCOPE_DENIED"):
        history._read(chat, lambda *_: None)


def test_missing_participant_scope_denied_before_database(monkeypatch):
    p = types.SimpleNamespace(content=True, participants=None)
    history, _, _, denied = module(monkeypatch, p)
    with pytest.raises(denied, match="PARTICIPANT_SCOPE_DENIED"):
        history._read("120363408741101070@g.us", lambda *_: None)


def test_group_privacy_barrier_withholds_permitted_participant(monkeypatch):
    chat = "120363408741101070@g.us"
    p = types.SimpleNamespace(content=True, participants=((chat, frozenset({"fixture-admin"})),))
    history, reader, db, _ = module(monkeypatch, p)
    db.execute("INSERT INTO p1_privacy_barriers VALUES (?,?)", (chat, "fixture"))
    row = {
        "id": "fixture",
        "sender": "fixture-admin",
        "content": "private",
        "deleted_at": None,
        "timestamp": "2026-10-15T00:00:00Z",
        "is_from_me": True,
    }
    proof, body = history._message(reader, db, chat, row)
    assert proof["state"] == "SUPPRESSED" and body is None and proof["sourceHash"] is None


def test_archive_page_preserves_raw_timestamp_and_resumes_by_rowid(monkeypatch):
    p = types.SimpleNamespace(content=True, participants=None)
    history, reader, db, _ = module(monkeypatch, p)
    db.execute("""CREATE TABLE messages(
        id text, chat_jid text, sender text, content text, timestamp text,
        is_from_me integer, deleted_at text, media_type text, filename text,
        file_sha256 blob, file_length integer, quoted_message_id text)""")
    chat = "8801670535255@s.whatsapp.net"
    db.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "m1",
                chat,
                "8801880446111",
                "hello",
                "2026-10-15T06:03:41.123456+06:00",
                0,
                None,
                None,
                None,
                None,
                None,
                "quoted-m0",
            ),
            (
                "m2",
                chat,
                "8801880446111",
                "",
                "2026-10-15T06:04:00.000001+06:00",
                0,
                None,
                "image",
                "photo.jpg",
                bytes.fromhex("ab" * 32),
                12,
                None,
            ),
        ],
    )
    first = history.list_archive_messages(chat, limit=1)
    assert first["previousAfter"] == "0"
    assert first["nextAfter"] == "1" and first["complete"] is False
    assert first["records"][0]["message"]["sourceTimestamp"] == "2026-10-15T06:03:41.123456+06:00"
    assert first["records"][0]["message"]["quotedMessageId"] == "quoted-m0"
    second = history.list_archive_messages(chat, after_rowid=first["nextAfter"], limit=1)
    assert second["records"][0]["rowid"] == "2"
    assert second["nextAfter"] == "2" and second["complete"] is True
    assert second["records"][0]["message"]["media"] == {
        "type": "image",
        "filename": "photo.jpg",
        "contentHash": "ab" * 32,
        "byteLength": 12,
        "storedFileRef": None,
    }


def test_archive_page_withholds_suppressed_content(monkeypatch):
    p = types.SimpleNamespace(content=True, participants=None)
    history, _, db, _ = module(monkeypatch, p)
    db.execute("""CREATE TABLE messages(
        id text, chat_jid text, sender text, content text, timestamp text,
        is_from_me integer, deleted_at text, media_type text, filename text,
        file_sha256 blob, file_length integer, quoted_message_id text)""")
    chat = "8801670535255@s.whatsapp.net"
    db.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("m1", chat, "sender", "private", "2026-10-15T00:00:00Z", 0, None, None, None, None, None, None),
    )
    db.execute("INSERT INTO p1_privacy_barriers VALUES (?,?)", (chat, "m1"))
    record = history.list_archive_messages(chat)["records"][0]
    assert record["state"] == "SUPPRESSED"
    assert record["sourceHash"] is None and record["message"] is None


def test_archive_page_preserves_source_deletion_time_without_body(monkeypatch):
    p = types.SimpleNamespace(content=True, participants=None)
    history, _, db, _ = module(monkeypatch, p)
    db.execute("""CREATE TABLE messages(
        id text, chat_jid text, sender text, content text, timestamp text,
        is_from_me integer, deleted_at text, media_type text, filename text,
        file_sha256 blob, file_length integer, quoted_message_id text)""")
    chat = "8801670535255@s.whatsapp.net"
    deleted_at = "2026-10-16T12:30:45.123456+06:00"
    db.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("m1", chat, "sender", "revoked body", "2026-10-15T00:00:00Z", 0, deleted_at, None, None, None, None, None),
    )
    record = history.list_archive_messages(chat)["records"][0]
    assert record["state"] == "REVOKED"
    assert record["deletedAt"] == deleted_at
    assert record["message"] is None and record["sourceHash"] is None
