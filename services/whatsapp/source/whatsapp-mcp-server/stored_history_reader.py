"""Read stored text/proofs through the existing native principal and SQLite owner.

No new socket, service, credential, grant, database or native cursor is created.
"""

import hashlib
import json
import re
import time
from datetime import UTC, datetime

import native_reader


def _message(reader, db, chat, row):
    mid = row["id"]
    if chat.endswith("@g.us"):
        principal = reader._principal(chat)
        participants = dict(principal.participants or ())
        if row["sender"] not in participants.get(chat, frozenset()):
            return {"messageId": mid, "state": "UNKNOWN", "sourceHash": None}, None
    suppressed = db.execute(
        "SELECT 1 FROM p1_privacy_barriers WHERE chat_jid=? AND message_id=?", (chat, mid)
    ).fetchone()
    state = "SUPPRESSED" if suppressed else "REVOKED" if row["deleted_at"] else "VISIBLE"
    if not row["content"] or len(row["content"].encode("utf-8")) > 64000:
        state = state if state != "VISIBLE" else "UNKNOWN"
    result = {"messageId": mid, "state": state, "sourceHash": None}
    if state != "VISIBLE":
        return result, None
    stamp = (
        datetime.fromisoformat(row["timestamp"])
        .astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    message = {
        "accountId": reader.account,
        "chatJid": chat,
        "id": mid,
        "sender": row["sender"] or "",
        "text": row["content"],
        "sourceTime": stamp,
        "direction": "OUTGOING" if row["is_from_me"] else "INCOMING",
        "deletedAt": None,
    }
    result["sourceHash"] = hashlib.sha256(
        json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return result, message


def _read(chat_jid, work):
    reader = native_reader._reader
    if (
        reader is None
        or not isinstance(chat_jid, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}@(s\.whatsapp\.net|lid|g\.us)", chat_jid)
    ):
        raise native_reader.NativeReadError("STORED_HISTORY_SCOPE_DENIED")
    if chat_jid.endswith("@g.us") and (
        reader.account != "wa-01"
        or chat_jid
        not in {
            "120363426895117693@g.us",
            "120363408741101070@g.us",
            "120363428977781821@g.us",
        }
    ):
        raise native_reader.NativeReadError("STORED_HISTORY_GROUP_SCOPE_DENIED")
    principal = reader._principal(chat_jid)
    if chat_jid.endswith("@g.us") and not dict(principal.participants or ()).get(chat_jid):
        raise native_reader.NativeReadError("STORED_HISTORY_PARTICIPANT_SCOPE_DENIED")
    if not principal.content or not reader._slot.acquire(blocking=False):
        raise native_reader.NativeReadError("STORED_HISTORY_CONTENT_OR_SLOT_DENIED")
    db = None
    try:
        db = reader._db(time.monotonic() + reader.deadline)
        result = work(reader, db)
        if principal != reader._principal(chat_jid):
            raise native_reader.NativeReadError("NATIVE_ACCESS_REVOKED")
        if len(json.dumps(result, ensure_ascii=False).encode()) > 80000:
            raise native_reader.NativeReadError("STORED_HISTORY_PAGE_BUDGET")
        return result
    finally:
        if db is not None:
            db.close()
        reader._slot.release()


def get_stored_message_proofs(chat_jid: str, message_ids: list[str]):
    if (
        not isinstance(message_ids, list)
        or not 1 <= len(message_ids) <= 10
        or any(not isinstance(v, str) or not 0 < len(v) <= 256 for v in message_ids)
        or len(set(message_ids)) != len(message_ids)
    ):
        raise native_reader.NativeReadError("STORED_HISTORY_INPUT_INVALID")

    def work(reader, db):
        results = []
        for mid in message_ids:
            row = db.execute(
                "SELECT id,sender,content,timestamp,is_from_me,deleted_at FROM messages WHERE chat_jid=? AND id=?",
                (chat_jid, mid),
            ).fetchone()
            proof = (
                _message(reader, db, chat_jid, row)[0]
                if row
                else {"messageId": mid, "state": "UNKNOWN", "sourceHash": None}
            )
            results.append(proof)
        return {
            "version": "stored-history-proofs-v1",
            "accountId": reader.account,
            "nativeScope": dict(reader.binding),
            "chatJid": chat_jid,
            "results": results,
        }

    return _read(chat_jid, work)


def list_stored_messages(chat_jid: str, after_rowid: str = "0", limit: int = 10):
    if (
        not isinstance(after_rowid, str)
        or not re.fullmatch(r"0|[1-9][0-9]{0,18}", after_rowid)
        or int(after_rowid) > 2**63 - 1
        or type(limit) is not int
        or not 1 <= limit <= 10
    ):
        raise native_reader.NativeReadError("STORED_HISTORY_INPUT_INVALID")

    def work(reader, db):
        rows = db.execute(
            "SELECT rowid,id,sender,content,timestamp,is_from_me,deleted_at FROM messages WHERE chat_jid=? AND rowid>? ORDER BY rowid LIMIT ?",
            (chat_jid, int(after_rowid), limit + 1),
        ).fetchall()
        records = []
        for row in rows[:limit]:
            proof, message = _message(reader, db, chat_jid, row)
            records.append({"rowid": str(row["rowid"]), **proof, "message": message})
        return {
            "version": "stored-history-page-v1",
            "accountId": reader.account,
            "nativeScope": dict(reader.binding),
            "chatJid": chat_jid,
            "previousAfter": after_rowid,
            "nextAfter": records[-1]["rowid"] if records else after_rowid,
            "complete": len(rows) <= limit,
            "records": records,
        }

    return _read(chat_jid, work)


def _archive_message(reader, db, chat, row):
    mid = row["id"]
    if chat.endswith("@g.us"):
        participants = dict(reader._principal(chat).participants or ())
        if row["sender"] not in participants.get(chat, frozenset()):
            return {
                "messageId": mid,
                "state": "UNKNOWN",
                "deletedAt": None,
                "sourceHash": None,
                "message": None,
            }
    suppressed = db.execute(
        "SELECT 1 FROM p1_privacy_barriers WHERE chat_jid=? AND message_id=?",
        (chat, mid),
    ).fetchone()
    state = "SUPPRESSED" if suppressed else "REVOKED" if row["deleted_at"] else "VISIBLE"
    media_hash = row["file_sha256"]
    if media_hash is not None and not isinstance(media_hash, str):
        media_hash = bytes(media_hash).hex()
    media = None
    if row["media_type"] or row["filename"] or media_hash or row["file_length"] is not None:
        media = {
            "type": row["media_type"],
            "filename": row["filename"],
            "contentHash": media_hash,
            "byteLength": int(row["file_length"]) if row["file_length"] is not None else None,
            "storedFileRef": None,
        }
    content = row["content"]
    if state == "VISIBLE" and content and len(content.encode("utf-8")) > 64000:
        state = "UNKNOWN"
    if state == "VISIBLE" and not content and media is None:
        state = "UNKNOWN"
    message = None
    source_hash = None
    if state == "VISIBLE":
        timestamp = row["timestamp"]
        message = {
            "accountId": reader.account,
            "chatJid": chat,
            "id": mid,
            "sender": row["sender"] or "",
            "sourceTimestamp": str(timestamp) if timestamp is not None else None,
            "text": content or "",
            "direction": "OUTGOING" if row["is_from_me"] else "INCOMING",
            "deletedAt": None,
            "messageType": row["media_type"] or ("text" if content else "unknown"),
            "quotedMessageId": row["quoted_message_id"],
            "media": media,
        }
        source_hash = hashlib.sha256(
            json.dumps(message, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    return {
        "messageId": mid,
        "state": state,
        "deletedAt": str(row["deleted_at"]) if state == "REVOKED" and row["deleted_at"] is not None else None,
        "sourceHash": source_hash,
        "message": message,
    }


def list_archive_messages(chat_jid: str, after_rowid: str = "0", limit: int = 10):
    """Read a bounded archive page without normalizing the stored source timestamp."""
    if (
        not isinstance(after_rowid, str)
        or not re.fullmatch(r"0|[1-9][0-9]{0,18}", after_rowid)
        or int(after_rowid) > 2**63 - 1
        or type(limit) is not int
        or not 1 <= limit <= 10
    ):
        raise native_reader.NativeReadError("STORED_HISTORY_INPUT_INVALID")

    def work(reader, db):
        rows = db.execute(
            """SELECT rowid,id,sender,content,timestamp,is_from_me,deleted_at,
                      media_type,filename,file_sha256,file_length,quoted_message_id
               FROM messages WHERE chat_jid=? AND rowid>?
               ORDER BY rowid LIMIT ?""",
            (chat_jid, int(after_rowid), limit + 1),
        ).fetchall()
        records = []
        for row in rows[:limit]:
            record = _archive_message(reader, db, chat_jid, row)
            records.append({"rowid": str(row["rowid"]), **record})
        next_after = records[-1]["rowid"] if records else after_rowid
        return {
            "version": "archive-history-page-v1",
            "accountId": reader.account,
            "nativeScope": dict(reader.binding),
            "chatJid": chat_jid,
            "previousAfter": after_rowid,
            "nextAfter": next_after,
            "complete": len(rows) <= limit,
            "records": records,
        }

    return _read(chat_jid, work)


def register(mcp):
    from capabilities import TOOL_CAPABILITIES

    for function in [get_stored_message_proofs, list_stored_messages, list_archive_messages]:
        TOOL_CAPABILITIES[function.__name__] = {"stored.history.read"}
        mcp.tool()(function)
