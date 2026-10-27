import hashlib
import json
import sqlite3

import pytest

import capabilities
import main
import native_reader
from native_reader import DisposableNativeReader, NativePrincipal, NativeReadError


def configure(monkeypatch, tmp_path, scopes, account="test-account"):
    token = "synthetic-consumer-token-for-offline-tests"
    token_path = tmp_path / "consumer-token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "consumers": [
                    {
                        "id": "reader",
                        "account": account,
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "capabilities": scopes,
                    }
                ]
            }
        )
    )
    policy_path.chmod(0o600)
    monkeypatch.setenv("WHATSAPP_AUTH_POLICY", str(policy_path))
    monkeypatch.setenv("WHATSAPP_ACCOUNT_ALIAS", "test-account")
    monkeypatch.setenv("WHATSAPP_CONSUMER_ID", "reader")
    monkeypatch.setenv("WHATSAPP_CONSUMER_TOKEN_FILE", str(token_path))
    return policy_path, token_path


@pytest.mark.asyncio
async def test_tools_are_filtered_and_direct_calls_denied(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["messages.read", "contacts.read", "calls.read"])
    names = {tool.name for tool in await main.mcp.list_tools()}
    assert "list_messages" in names and "list_calls" in names
    for tool in (
        "send_message",
        "send_file",
        "send_audio_message",
        "send_reaction",
        "mark_messages_read",
        "download_media",
        "view_media",
        "transcribe_audio",
        "set_typing",
        "request_history",
    ):
        assert tool not in names
        with pytest.raises(PermissionError):
            getattr(main, tool)()  # Guard runs before arguments or side effects.
        with pytest.raises(PermissionError):
            await main.mcp.call_tool(tool, {})


def test_revocation_and_account_mismatch(monkeypatch, tmp_path):
    policy, _ = configure(monkeypatch, tmp_path, ["messages.send"])
    capabilities.require_tool("send_message")
    policy.write_text('{"consumers": []}')
    with pytest.raises(PermissionError):
        capabilities.require_tool("send_message")
    configure(monkeypatch, tmp_path, ["messages.send"], account="other-account")
    with pytest.raises(PermissionError):
        capabilities.grants()


def test_invalid_private_configuration(monkeypatch, tmp_path):
    _, token = configure(monkeypatch, tmp_path, ["messages.read"])
    token.chmod(0o644)
    with pytest.raises(PermissionError):
        capabilities.grants()


@pytest.mark.asyncio
async def test_native_identity_capability_is_isolated(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["native.identity.read"])
    names = {tool.name for tool in await main.mcp.list_tools()}
    assert "get_native_account_identity" in names
    assert "list_native_events" not in names
    assert "get_contact" not in names
    assert "search_contacts" not in names
    assert "list_messages" not in names
    assert "send_message" not in names
    for tool in ("list_native_events", "list_messages", "get_contact", "search_contacts", "send_message"):
        with pytest.raises(PermissionError):
            await main.mcp.call_tool(tool, {})


@pytest.mark.asyncio
async def test_native_contact_capability_exposes_only_scoped_get_contact(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["native.events.read", "native.contacts.read"])
    names = {tool.name for tool in await main.mcp.list_tools()}
    assert "get_contact" in names
    assert "search_contacts" not in names
    assert "list_messages" not in names

    with pytest.raises(PermissionError):
        await main.mcp.call_tool("search_contacts", {"query": "synthetic"})


@pytest.mark.asyncio
async def test_native_mirror_grants_do_not_expose_stored_history_tools(monkeypatch, tmp_path):
    configure(
        monkeypatch,
        tmp_path,
        ["native.identity.read", "native.events.read", "native.content.read", "native.contacts.read"],
    )
    names = {tool.name for tool in await main.mcp.list_tools()}
    assert {
        "get_native_account_identity",
        "list_native_events",
        "list_native_messages",
        "get_contact",
    } <= names
    assert (
        not {
            "get_stored_message_proofs",
            "list_stored_messages",
            "list_archive_messages",
        }
        & names
    )

    for tool in ("get_stored_message_proofs", "list_stored_messages", "list_archive_messages"):
        with pytest.raises(PermissionError):
            await main.mcp.call_tool(tool, {})


@pytest.mark.asyncio
async def test_native_events_capability_is_metadata_only(monkeypatch, tmp_path):
    account = "wa-01"
    chat = "15551234567@s.whatsapp.net"
    other_chat = "15557654321@s.whatsapp.net"
    stream_id = "12345678-1234-1234-1234-123456789abc"
    binding = {
        "accountId": "synthetic-wa-01",
        "streamId": stream_id,
        "pairedJid": "15550000001:1@s.whatsapp.net",
        "pairedLid": "15550000000001:1@lid",
    }
    database_dir = tmp_path / "disposable"
    database_dir.mkdir()
    database = database_dir / "native.db"
    header = {
        "account": {"streamId": stream_id},
        "event": {
            "chatJid": {"state": "present", "value": chat},
            "senderJid": {"state": "present", "value": chat},
            "direction": {"state": "present", "value": "incoming"},
        },
        "content": {"text": {"state": "present", "value": "synthetic-private-body"}},
    }
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE native_stream (
                singleton INTEGER, account_id TEXT, stream_id TEXT, paired_jid TEXT,
                paired_lid TEXT, identity_state TEXT, schema_version INTEGER
            );
            CREATE TABLE native_events (
                event_seq INTEGER, event_key TEXT, occurrence_key TEXT, native_event_id TEXT,
                message_id TEXT, original_chat_jid TEXT, original_sender_jid TEXT, kind TEXT,
                origin TEXT, source_time TEXT, ingested_at TEXT, semantic_hash BLOB,
                payload_hash BLOB, envelope_hash BLOB, prior_event_seq INTEGER,
                header_json TEXT, stream_id TEXT
            );
            CREATE TABLE p1_privacy_barriers (chat_jid TEXT, message_id TEXT);
        """)
        db.execute(
            "INSERT INTO native_stream VALUES (1, ?, ?, ?, ?, 'verified_native', 1)",
            (binding["accountId"], stream_id, binding["pairedJid"], binding["pairedLid"]),
        )
        db.execute(
            """INSERT INTO native_events VALUES (
                1, 'event-1', 'occurrence-1', 'native-1', 'message-1', ?, ?, 'message',
                'bridge', '2026-10-22T00:00:00Z', '2026-10-22T00:00:01Z', ?, ?, ?, NULL, ?, ?
            )""",
            (
                chat,
                chat,
                b"s" * 32,
                b"p" * 32,
                b"e" * 32,
                json.dumps(header),
                stream_id,
            ),
        )

    configure(monkeypatch, tmp_path, ["native.events.read"], account=account)
    monkeypatch.setenv("WHATSAPP_ACCOUNT_ALIAS", account)
    principal = NativePrincipal("reader", 1, account, frozenset({chat}), True)
    reader = DisposableNativeReader(
        str(database),
        account,
        binding,
        lambda: principal,
    )
    monkeypatch.setattr(native_reader, "_reader", reader)

    names = {tool.name for tool in await main.mcp.list_tools()}
    assert "list_native_events" in names
    assert "get_native_account_identity" not in names
    assert "list_messages" not in names
    assert "send_message" not in names

    result = main.list_native_events(chat, limit=1)
    assert result["nativeScope"] == {"accountId": account}
    record = result["records"][0]
    assert record["messageId"] == "message-1"
    assert record["sourceTime"] == "2026-10-22T00:00:00Z"
    assert record["senderJid"] == chat
    assert record["chatJid"] == chat
    assert record["status"] == "HELD"
    assert record["reason"] == "METADATA_ONLY"
    assert record["envelope"] is None
    assert record["quote"] is None
    assert "synthetic-private-body" not in json.dumps(result)
    assert binding["pairedJid"] not in json.dumps(result)
    assert binding["pairedLid"] not in json.dumps(result)
    with pytest.raises(NativeReadError, match="NATIVE_ACCESS_DENIED"):
        main.list_native_events(other_chat, limit=1)


@pytest.mark.asyncio
async def test_full_consumer_retains_every_original_tool(monkeypatch, tmp_path):
    all_scopes = sorted(set().union(*capabilities.TOOL_CAPABILITIES.values()))
    configure(monkeypatch, tmp_path, all_scopes)
    names = {tool.name for tool in await main.mcp.list_tools()}
    assert set(capabilities.TOOL_CAPABILITIES) == names


def test_consumer_never_uses_master_token(monkeypatch, tmp_path):
    import whatsapp

    _, token = configure(monkeypatch, tmp_path, ["media.download"])
    monkeypatch.setenv("WHATSAPP_BRIDGE_TOKEN", "unrestricted-master-should-never-be-used")
    assert whatsapp._read_bridge_token() == token.read_text()


def test_retrieval_never_creates_missing_db(monkeypatch, tmp_path):
    import whatsapp

    missing = tmp_path / "missing.db"
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(missing))
    assert whatsapp.list_chats() == []
    assert not missing.exists()


def test_context_rejects_ambiguous_native_id(monkeypatch, tmp_path):
    import sqlite3

    import whatsapp

    database = tmp_path / "messages.db"
    with sqlite3.connect(database) as conn:
        conn.executescript("""
        CREATE TABLE chats (jid TEXT, name TEXT);
        CREATE TABLE messages (id TEXT, chat_jid TEXT, timestamp TEXT, sender TEXT, content TEXT,
          is_from_me INTEGER, media_type TEXT, quoted_message_id TEXT, filename TEXT);
        INSERT INTO chats VALUES ('chat-a','A'),('chat-b','B');
        INSERT INTO messages VALUES ('duplicate','chat-a','2026-01-01T00:00:00','sender','A',0,'',NULL,''),
          ('duplicate','chat-b','2026-01-01T00:00:00','sender','B',0,'',NULL,'');
        """)
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(database))
    with pytest.raises(ValueError, match="Ambiguous"):
        whatsapp.get_message_context("duplicate")
    assert whatsapp.get_message_context("duplicate", chat_jid="chat-b").message.content == "B"


def test_outbound_media_cannot_read_private_store(monkeypatch, tmp_path):
    import whatsapp

    configure(monkeypatch, tmp_path, ["media.send"])
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    secret = tmp_path / "session.db"
    secret.write_bytes(b"private-fixture")
    monkeypatch.setenv("WHATSAPP_MEDIA_ROOTS", str(outbox))
    with pytest.raises(PermissionError):
        whatsapp._outbound_path(str(secret))
    link = outbox / "escape.ogg"
    link.symlink_to(secret)
    with pytest.raises(PermissionError):
        whatsapp._outbound_path(str(link))


def test_secure_voice_conversion_uses_approved_outbox(monkeypatch, tmp_path):
    import subprocess

    import whatsapp

    configure(monkeypatch, tmp_path, ["media.send"])
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    wav = outbox / "fixture.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.1", str(wav)], check=True
    )
    monkeypatch.setenv("WHATSAPP_MEDIA_ROOTS", str(outbox))
    sent_paths = []

    class Response:
        status_code = 200

        def json(self):
            return {"success": True, "message": "synthetic-ack"}

    def fake_post(url, json, headers):
        from pathlib import Path

        path = Path(json["media_path"])
        assert path.parent == outbox and path.read_bytes().startswith(b"OggS")
        sent_paths.append(path)
        return Response()

    monkeypatch.setattr(whatsapp, "_bridge_post", fake_post)
    assert whatsapp.send_audio_message("synthetic", str(wav))[0]
    assert len(sent_paths) == 1 and not sent_paths[0].exists() and wav.exists()
