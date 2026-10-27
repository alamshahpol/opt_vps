import json
import os
import os.path
import sqlite3
import sys
from builtins import print as __builtins_print
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import audio
from capabilities import consumer_token


def print(*args, **kwargs):
    kwargs["file"] = sys.stderr
    __builtins_print(*args, **kwargs)


# Configuration via environment variables with sensible defaults
_DEFAULT_BRIDGE_STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "whatsapp-bridge", "store")
MESSAGES_DB_PATH = os.getenv(
    "WHATSAPP_DB_PATH",
    os.path.join(_DEFAULT_BRIDGE_STORE_DIR, "messages.db"),
)
WHATSMEOW_DB_PATH = os.getenv(
    "WHATSMEOW_DB_PATH",
    os.path.join(_DEFAULT_BRIDGE_STORE_DIR, "whatsapp.db"),
)
WHATSAPP_API_BASE_URL = os.getenv("WHATSAPP_API_URL", "http://localhost:8080/api")

_BRIDGE_TOKEN_PATH = os.path.join(os.path.dirname(WHATSMEOW_DB_PATH), ".bridge-token")


def _read_bridge_token() -> str | None:
    if os.getenv("WHATSAPP_AUTH_POLICY"):
        return consumer_token()
    env = os.getenv("WHATSAPP_BRIDGE_TOKEN", "").strip()
    if env:
        return env
    try:
        with open(_BRIDGE_TOKEN_PATH, encoding="utf-8") as fh:
            value = fh.read().strip()
            return value or None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _bridge_headers() -> dict[str, str]:
    token = _read_bridge_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _bridge_post(*args, **kwargs):
    if not os.getenv("WHATSAPP_AUTH_POLICY"):
        return requests.post(*args, **kwargs)
    with requests.Session() as session:
        session.trust_env = False
        return session.post(*args, **kwargs, timeout=(5, 60), allow_redirects=False)


@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: str | None = None
    media_type: str | None = None
    # For media_type == "reaction", the bridge stores the reacted-to message ID
    # in the `filename` column. Exposed to callers as `reaction_to_message_id`.
    filename: str | None = None
    # ID of the message this one is replying to (NULL for non-replies).
    quoted_message_id: str | None = None
    original_sender_jid: str | None = None
    original_chat_jid: str | None = None
    group_participant_jid: str | None = None
    resolved_sender_jid: str | None = None
    resolved_chat_jid: str | None = None
    identity_state: str | None = None
    chat_identity_state: str | None = None


@dataclass
class Chat:
    jid: str
    name: str | None
    last_message_time: datetime | None
    last_message: str | None = None
    last_sender: str | None = None
    last_is_from_me: bool | None = None
    # Bridge read marker (chats.last_read_time): how far we have read this
    # chat, from read receipts and history-sync backfill. NULL when the
    # bridge has never seen a read for the chat, or predates the column.
    last_read_time: datetime | None = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")

    @property
    def unread(self) -> bool:
        """Whether the chat's last message is inbound and unread by us.

        With a read marker this is genuine unread — a chat read on the phone
        or another linked device is not reported. Without one (older bridge,
        or a chat WhatsApp never reported a read for) it degrades to the old
        heuristic: unread if the last message is inbound.

        A missing last-message row (`last_is_from_me is None`) cannot establish
        direction — protocol/unsupported events can advance last_message_time
        without storing a message — so those chats are not reported as unread.
        """
        if self.last_message_time is None or self.last_is_from_me is None:
            return False
        if self.last_is_from_me:
            return False
        if self.last_read_time is None:
            return True
        return self.last_message_time > self.last_read_time


@dataclass
class Contact:
    phone_number: str
    name: str | None
    jid: str


@dataclass
class MessageContext:
    message: Message
    before: list[Message]
    after: list[Message]


def msg_to_dict(message: Message, include_sender_name: bool = True) -> dict[str, Any]:
    """Convert a Message dataclass to a dictionary for JSON serialization."""
    original_sender_jid = message.original_sender_jid or message.sender
    identity = _resolve_identity(original_sender_jid)
    identity_state = message.identity_state or identity["state"]
    resolved_sender_jid = message.resolved_sender_jid or identity["resolved_sender_jid"]
    sender_phone = identity["sender_pn"]
    if identity_state != "RESOLVED":
        sender_phone = None
        resolved_sender_jid = None
    elif resolved_sender_jid and resolved_sender_jid.endswith("@s.whatsapp.net"):
        sender_phone = resolved_sender_jid.partition("@")[0]
    sender_display_id = sender_phone or original_sender_jid

    sender_name = None
    sender_display = None
    if include_sender_name:
        if message.is_from_me:
            sender_name = "Me"
            sender_display = "Me"
        else:
            resolved_name = get_sender_name(message.sender)
            if resolved_name and resolved_name != message.sender and resolved_name != sender_display_id:
                sender_name = resolved_name
                sender_display = f"{resolved_name} ({sender_display_id})"
            else:
                sender_name = sender_display_id
                sender_display = sender_display_id

    return {
        "id": message.id,
        "timestamp": message.timestamp.isoformat(),
        "sender_jid": original_sender_jid,
        "sender_phone": sender_phone,
        "sender_lid": identity["sender_lid"],
        "resolved_sender_jid": resolved_sender_jid,
        "identity_state": identity_state,
        "original_sender_jid": message.original_sender_jid,
        "original_chat_jid": message.original_chat_jid,
        "group_participant_jid": message.group_participant_jid,
        "resolved_chat_jid": message.resolved_chat_jid,
        "chat_identity_state": message.chat_identity_state,
        "sender_push_name": None if message.is_from_me else _resolve_push_name_from_whatsmeow(original_sender_jid),
        "sender_name": sender_name,
        "sender_display": sender_display,  # "Name (phone)" or just phone if no name
        "content": message.content,
        "is_from_me": message.is_from_me,
        "chat_jid": message.chat_jid,
        "chat_name": message.chat_name,
        "media_type": message.media_type,
        "reaction_to_message_id": (message.filename if message.media_type == "reaction" else None),
        "quoted_message_id": message.quoted_message_id,
    }


def chat_to_dict(chat: "Chat") -> dict[str, Any]:
    """Convert a Chat dataclass to a dictionary for JSON serialization."""
    return {
        "jid": chat.jid,
        "name": chat.name,
        "is_group": chat.is_group,
        "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
        "last_message": chat.last_message,
        "last_sender": chat.last_sender,
        "last_is_from_me": chat.last_is_from_me,
        "last_read_time": chat.last_read_time.isoformat() if chat.last_read_time else None,
        "unread": chat.unread,
    }


def _lookup_lid_mapping(lid: str) -> tuple[str | None, str]:
    if not lid or not os.path.isfile(WHATSMEOW_DB_PATH):
        return None, "UNRESOLVED"
    try:
        with sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT pn FROM whatsmeow_lid_map WHERE lid = ? ORDER BY pn",
                (lid,),
            ).fetchall()
    except sqlite3.Error:
        return None, "UNRESOLVED"
    phones = {row[0] for row in rows if row[0]}
    if len(phones) > 1:
        return None, "AMBIGUOUS"
    if not phones:
        return None, "UNRESOLVED"
    return phones.pop(), "RESOLVED"


def _lids_for_phone(phone: str) -> list[str]:
    if not phone or not os.path.isfile(WHATSMEOW_DB_PATH):
        return []
    try:
        with sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT lid FROM whatsmeow_lid_map WHERE pn = ? ORDER BY lid",
                (phone,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [row[0] for row in rows if row[0]]


def _resolve_identity(jid: str) -> dict[str, str | None]:
    user, separator, server = jid.partition("@")
    identity: dict[str, str | None] = {
        "sender_lid": None,
        "sender_pn": None,
        "resolved_sender_jid": None,
        "state": "AMBIGUOUS",
    }
    if not separator or not user:
        return identity
    if server == "s.whatsapp.net":
        if not user.isdigit():
            return identity
        identity.update(sender_pn=user, resolved_sender_jid=jid, state="RESOLVED")
        return identity
    if server == "lid":
        identity["sender_lid"] = user
        phone, state = _lookup_lid_mapping(user)
        identity["state"] = state
        if phone:
            identity.update(sender_pn=phone, resolved_sender_jid=f"{phone}@s.whatsapp.net")
        return identity
    return identity


def _verified_phone(value: str) -> bool:
    return _resolve_identity(value)["sender_pn"] is not None


def contact_to_dict(contact: "Contact") -> dict[str, Any]:
    """Convert a Contact dataclass to a dictionary for JSON serialization."""
    return {
        "phone_number": contact.phone_number if contact.jid.endswith("@s.whatsapp.net") else None,
        "name": contact.name,
        "jid": contact.jid,
    }


def _last_read_time_select(cursor: sqlite3.Cursor, table_alias: str) -> str:
    """SELECT expression for chats.last_read_time, or a NULL literal.

    The bridge adds the column through its own migration, so a messages.db
    written by an older bridge doesn't have it yet. Reads must keep working
    against such a store — those chats simply report last_read_time = None.
    """
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(chats)").fetchall()}
    return f"{table_alias}.last_read_time" if "last_read_time" in columns else "NULL"


def _last_message_join(chat_alias: str, msg_alias: str) -> str:
    """Deterministic single-row join to the chat's latest message.

    Multiple messages can share last_message_time (history sync is second-
    resolution). Joining solely on timestamp would duplicate chat rows and
    make last_is_from_me / unread non-deterministic; pick one id as tie-break.
    """
    return f"""
            LEFT JOIN messages {msg_alias} ON {chat_alias}.jid = {msg_alias}.chat_jid
                AND {msg_alias}.id = (
                    SELECT m.id FROM messages m
                    WHERE m.chat_jid = {chat_alias}.jid
                      AND m.timestamp = {chat_alias}.last_message_time
                    ORDER BY m.id DESC
                    LIMIT 1
                )
    """


def _sender_aliases(value: str) -> list[str]:
    user, separator, server = value.partition("@")
    if not separator:
        return [value]
    if server == "lid":
        phone, state = _lookup_lid_mapping(user)
        aliases = [user, value]
        if phone and state == "RESOLVED":
            aliases.extend((phone, f"{phone}@s.whatsapp.net"))
        return list(dict.fromkeys(aliases))
    if server == "s.whatsapp.net":
        if not user.isdigit():
            return [value]
        aliases = [user, value]
        for lid in _lids_for_phone(user):
            aliases.extend((lid, f"{lid}@lid"))
        return list(dict.fromkeys(aliases))
    return [value]


def _identity_select_columns(cursor: sqlite3.Cursor, table_alias: str = "messages") -> str:
    available = {row[1] for row in cursor.execute("PRAGMA table_info(messages)").fetchall()}
    columns = (
        "original_sender_jid",
        "original_chat_jid",
        "group_participant_jid",
        "resolved_sender_jid",
        "resolved_chat_jid",
        "identity_state",
        "chat_identity_state",
    )
    return ", " + ", ".join(f"{table_alias}.{column}" if column in available else "NULL" for column in columns)


def _resolve_lid_to_phone(lid_or_jid: str) -> str | None:
    """Resolve a WhatsApp LID (linked device identifier) to a phone number.

    WhatsApp's newer protocol uses opaque LIDs (e.g. '35047067385985') as sender
    identifiers instead of phone numbers. The whatsmeow_lid_map table maps these
    back to real phone numbers.

    Returns the phone number if found, None otherwise.
    """
    if not os.path.exists(WHATSMEOW_DB_PATH):
        return None
    user, separator, server = lid_or_jid.partition("@")
    if not separator or server != "lid":
        return None
    phone, state = _lookup_lid_mapping(user)
    return phone if state == "RESOLVED" else None


def _resolve_name_from_whatsmeow(jid: str) -> str | None:
    """Look up a contact name from whatsmeow's contact store (whatsapp.db).

    Handles both standard JIDs (12345@s.whatsapp.net) and LIDs (opaque numeric
    identifiers used by WhatsApp's linked device protocol). LIDs are first
    resolved to phone numbers via whatsmeow_lid_map, then looked up in contacts.

    Falls back gracefully if the DB or table doesn't exist.
    """
    if not os.path.exists(WHATSMEOW_DB_PATH):
        return None

    lookup_jid = jid
    jid_suffix = jid.split("@")[1] if "@" in jid else ""

    # Only an explicitly typed LID can be resolved through the protocol map.
    if jid_suffix == "lid":
        phone = _resolve_lid_to_phone(jid)
        if phone:
            lookup_jid = phone + "@s.whatsapp.net"
        elif jid_suffix == "lid":
            # Definitely a LID but not in the map — can't resolve
            return None

    try:
        conn = sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()
        # whatsmeow_contacts columns: our_jid, their_jid, first_name, full_name, push_name, business_name
        cursor.execute(
            "SELECT full_name, push_name, first_name, business_name FROM whatsmeow_contacts WHERE their_jid = ? LIMIT 1",
            (lookup_jid,),
        )
        row = cursor.fetchone()
        if row:
            # Prefer full_name, then push_name, then first_name, then business_name
            return row[0] or row[1] or row[2] or row[3] or None
        return None
    except sqlite3.Error:
        return None
    finally:
        if "conn" in locals():
            conn.close()


def get_saved_contact_name(jid: str) -> str | None:
    """Return only locally saved contact-name fields, never WhatsApp push_name."""
    if not os.path.exists(WHATSMEOW_DB_PATH):
        return None

    lookup_jid = jid
    jid_suffix = jid.split("@")[1] if "@" in jid else ""
    if jid_suffix == "lid":
        phone = _resolve_lid_to_phone(jid)
        if not phone:
            return None
        lookup_jid = phone + "@s.whatsapp.net"

    try:
        conn = sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT full_name, first_name FROM whatsmeow_contacts WHERE their_jid = ? LIMIT 1",
            (lookup_jid,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return row[0] or row[1] or None
    except sqlite3.Error:
        return None
    finally:
        if "conn" in locals():
            conn.close()


def _resolve_push_name_from_whatsmeow(jid: str) -> str | None:
    """Return only the source push_name field for a phone JID or mapped LID."""
    if not os.path.exists(WHATSMEOW_DB_PATH):
        return None

    lookup_jid = jid
    jid_suffix = jid.split("@")[1] if "@" in jid else ""
    if jid_suffix == "lid":
        phone = _resolve_lid_to_phone(jid)
        if phone:
            lookup_jid = phone + "@s.whatsapp.net"
        elif jid_suffix == "lid":
            return None

    try:
        conn = sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT push_name FROM whatsmeow_contacts WHERE their_jid = ? LIMIT 1",
            (lookup_jid,),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error:
        return None
    finally:
        if "conn" in locals():
            conn.close()


def get_sender_name(sender_jid: str) -> str:
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        # First try matching by exact JID
        cursor.execute(
            """
            SELECT name
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """,
            (sender_jid,),
        )

        result = cursor.fetchone()

        # If no result, try looking for the number within JIDs
        if not result:
            # Extract the phone number part if it's a JID
            if "@" in sender_jid:
                phone_part = sender_jid.split("@")[0]
            else:
                phone_part = sender_jid

            cursor.execute(
                """
                SELECT name
                FROM chats
                WHERE jid LIKE ?
                LIMIT 1
            """,
                (f"%{phone_part}%",),
            )

            result = cursor.fetchone()

        if result and result[0] and not result[0].replace("+", "").isdigit():
            return result[0]

        # Fall back to whatsmeow contact store
        whatsmeow_name = _resolve_name_from_whatsmeow(sender_jid)
        if whatsmeow_name:
            return whatsmeow_name

        # Try with @s.whatsapp.net suffix if bare number
        if "@" not in sender_jid:
            whatsmeow_name = _resolve_name_from_whatsmeow(sender_jid + "@s.whatsapp.net")
            if whatsmeow_name:
                return whatsmeow_name

        return sender_jid

    except sqlite3.Error:
        print("Database error while getting sender name")
        return sender_jid
    finally:
        if "conn" in locals():
            conn.close()


def format_message(message: Message, show_chat_info: bool = True) -> None:
    """Print a single message with consistent formatting."""
    output = ""

    if show_chat_info and message.chat_name:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] Chat: {message.chat_name} "
    else:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] "

    content_prefix = ""
    if hasattr(message, "media_type") and message.media_type:
        content_prefix = f"[{message.media_type} - Message ID: {message.id} - Chat JID: {message.chat_jid}] "

    try:
        sender_name = get_sender_name(message.sender) if not message.is_from_me else "Me"
        output += f"From: {sender_name}: {content_prefix}{message.content}\n"
    except Exception:
        print("Error formatting message")
    return output


def format_messages_list(messages: list[Message], show_chat_info: bool = True) -> None:
    output = ""
    if not messages:
        output += "No messages to display."
        return output

    for message in messages:
        output += format_message(message, show_chat_info)
    return output


def list_messages(
    after: str | None = None,
    before: str | None = None,
    sender_phone_number: str | None = None,
    chat_jid: str | None = None,
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1,
    sort_by: str = "newest",
) -> list[dict[str, Any]]:
    """Get messages matching the specified criteria with optional context.

    Args:
        after: Optional ISO-8601 formatted string to only return messages after this date
        before: Optional ISO-8601 formatted string to only return messages before this date
        sender_phone_number: Optional phone number to filter messages by sender
        chat_jid: Optional chat JID to filter messages by chat
        query: Optional search term to filter messages by content
        limit: Maximum number of messages to return (default 20)
        page: Page number for pagination (default 0)
        include_context: Whether to include messages before and after matches (default True)
        context_before: Number of messages to include before each match (default 1)
        context_after: Number of messages to include after each match (default 1)
        sort_by: Sort order - "newest" (default) or "oldest" for chronological ordering

    Returns:
        List of message dictionaries with id, timestamp, sender, content, etc.
    """
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        # Build base query
        query_parts = [
            "SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.quoted_message_id, messages.filename"
            + _identity_select_columns(cursor)
            + " FROM messages"
        ]
        query_parts.append("JOIN chats ON messages.chat_jid = chats.jid")
        where_clauses = []
        params = []

        # Add filters
        if after:
            try:
                after = datetime.fromisoformat(after)
            except ValueError:
                raise ValueError(f"Invalid date format for 'after': {after}. Please use ISO-8601 format.")

            where_clauses.append("messages.timestamp > ?")
            params.append(after)

        if before:
            try:
                before = datetime.fromisoformat(before)
            except ValueError:
                raise ValueError(f"Invalid date format for 'before': {before}. Please use ISO-8601 format.")

            where_clauses.append("messages.timestamp < ?")
            params.append(before)

        if sender_phone_number:
            aliases = _sender_aliases(sender_phone_number)
            placeholders = ",".join("?" * len(aliases))
            where_clauses.append(f"messages.sender IN ({placeholders})")
            params.extend(aliases)

        if chat_jid:
            where_clauses.append("messages.chat_jid = ?")
            params.append(chat_jid)

        if query:
            # SQLite's LOWER() only handles ASCII, so LIKE LOWER(...) silently
            # excludes Unicode matches. instr() on the raw column preserves them.
            where_clauses.append("(instr(LOWER(messages.content), LOWER(?)) > 0 OR instr(messages.content, ?) > 0)")
            params.extend([query, query])

        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        # Add sorting and pagination
        offset = page * limit
        order = "DESC" if sort_by == "newest" else "ASC"
        query_parts.append(f"ORDER BY messages.timestamp {order}")
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])

        cursor.execute(" ".join(query_parts), tuple(params))
        messages = cursor.fetchall()

        result = []
        for msg in messages:
            message = Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7],
                quoted_message_id=msg[8] if len(msg) > 8 else None,
                filename=msg[9] if len(msg) > 9 else None,
                original_sender_jid=msg[10],
                original_chat_jid=msg[11],
                group_participant_jid=msg[12],
                resolved_sender_jid=msg[13],
                resolved_chat_jid=msg[14],
                identity_state=msg[15],
                chat_identity_state=msg[16],
            )
            result.append(message)

        if include_context and result:
            # Add context for each message, deduplicated by message ID
            seen_ids = set()
            messages_with_context = []
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after, chat_jid=msg.chat_jid)
                for ctx_msg in context.before:
                    if (ctx_msg.chat_jid, ctx_msg.id) not in seen_ids:
                        seen_ids.add((ctx_msg.chat_jid, ctx_msg.id))
                        messages_with_context.append(ctx_msg)
                if (context.message.chat_jid, context.message.id) not in seen_ids:
                    seen_ids.add((context.message.chat_jid, context.message.id))
                    messages_with_context.append(context.message)
                for ctx_msg in context.after:
                    if (ctx_msg.chat_jid, ctx_msg.id) not in seen_ids:
                        seen_ids.add((ctx_msg.chat_jid, ctx_msg.id))
                        messages_with_context.append(ctx_msg)

            return [msg_to_dict(msg) for msg in messages_with_context]

        # Return messages without context
        return [msg_to_dict(msg) for msg in result]

    except sqlite3.Error:
        print("Database error")
        return []
    finally:
        if "conn" in locals():
            conn.close()


def get_message_context(
    message_id: str, before: int = 5, after: int = 5, chat_jid: str | None = None
) -> MessageContext:
    """Get context around a specific message."""
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        # Get the target message first
        cursor.execute(
            f"""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.chat_jid, messages.media_type, messages.quoted_message_id, messages.filename
                {_identity_select_columns(cursor)}
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.id = ? AND (? IS NULL OR messages.chat_jid = ?)
        """,
            (message_id, chat_jid, chat_jid),
        )
        matched = cursor.fetchall()
        if len(matched) > 1:
            raise ValueError("Ambiguous message ID; supply chat_jid")
        msg_data = matched[0] if matched else None

        if not msg_data:
            raise ValueError(f"Message with ID {message_id} not found")

        target_message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[8],
            quoted_message_id=msg_data[9] if len(msg_data) > 9 else None,
            filename=msg_data[10] if len(msg_data) > 10 else None,
            original_sender_jid=msg_data[11],
            original_chat_jid=msg_data[12],
            group_participant_jid=msg_data[13],
            resolved_sender_jid=msg_data[14],
            resolved_chat_jid=msg_data[15],
            identity_state=msg_data[16],
            chat_identity_state=msg_data[17],
        )

        # Get messages before
        cursor.execute(
            f"""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.quoted_message_id, messages.filename
                {_identity_select_columns(cursor)}
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp < ?
            ORDER BY messages.timestamp DESC
            LIMIT ?
        """,
            (msg_data[7], msg_data[0], before),
        )

        before_messages = []
        for msg in cursor.fetchall():
            before_messages.append(
                Message(
                    timestamp=datetime.fromisoformat(msg[0]),
                    sender=msg[1],
                    chat_name=msg[2],
                    content=msg[3],
                    is_from_me=msg[4],
                    chat_jid=msg[5],
                    id=msg[6],
                    media_type=msg[7],
                    quoted_message_id=msg[8] if len(msg) > 8 else None,
                    filename=msg[9] if len(msg) > 9 else None,
                    original_sender_jid=msg[10],
                    original_chat_jid=msg[11],
                    group_participant_jid=msg[12],
                    resolved_sender_jid=msg[13],
                    resolved_chat_jid=msg[14],
                    identity_state=msg[15],
                    chat_identity_state=msg[16],
                )
            )

        # Get messages after
        cursor.execute(
            f"""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type, messages.quoted_message_id, messages.filename
                {_identity_select_columns(cursor)}
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp > ?
            ORDER BY messages.timestamp ASC
            LIMIT ?
        """,
            (msg_data[7], msg_data[0], after),
        )

        after_messages = []
        for msg in cursor.fetchall():
            after_messages.append(
                Message(
                    timestamp=datetime.fromisoformat(msg[0]),
                    sender=msg[1],
                    chat_name=msg[2],
                    content=msg[3],
                    is_from_me=msg[4],
                    chat_jid=msg[5],
                    id=msg[6],
                    media_type=msg[7],
                    quoted_message_id=msg[8] if len(msg) > 8 else None,
                    filename=msg[9] if len(msg) > 9 else None,
                    original_sender_jid=msg[10],
                    original_chat_jid=msg[11],
                    group_participant_jid=msg[12],
                    resolved_sender_jid=msg[13],
                    resolved_chat_jid=msg[14],
                    identity_state=msg[15],
                    chat_identity_state=msg[16],
                )
            )

        return MessageContext(message=target_message, before=before_messages, after=after_messages)

    except sqlite3.Error:
        print("Database error")
        raise
    finally:
        if "conn" in locals():
            conn.close()


def list_chats(
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active",
) -> list[dict[str, Any]]:
    """Get chats matching the specified criteria.

    Returns:
        List of chat dictionaries with jid, name, is_group, last_message, etc.
    """
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        # The last message is always joined — is_from_me feeds the unread
        # flag — but its content is only selected when asked for. The columns
        # are referenced by tuple index downstream, so the result shape stays
        # constant across the branch.
        if include_last_message:
            last_message_select = "messages.content as last_message, messages.sender as last_sender"
        else:
            last_message_select = "NULL as last_message, NULL as last_sender"

        query_parts = [
            f"""
            SELECT
                chats.jid,
                chats.name,
                chats.last_message_time,
                {last_message_select},
                messages.is_from_me as last_is_from_me,
                {_last_read_time_select(cursor, "chats")}
            FROM chats
            {_last_message_join("chats", "messages")}
        """
        ]

        where_clauses = []
        params = []

        if query:
            # instr() on the raw column matches Unicode; LOWER()+LIKE only covers ASCII.
            where_clauses.append(
                "(instr(LOWER(chats.name), LOWER(?)) > 0 OR instr(chats.name, ?) > 0 OR chats.jid LIKE ?)"
            )
            params.extend([query, query, f"%{query}%"])

        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        # Add sorting
        order_by = "chats.last_message_time DESC" if sort_by == "last_active" else "chats.name"
        query_parts.append(f"ORDER BY {order_by}")

        # Add pagination
        offset = (page) * limit
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])

        cursor.execute(" ".join(query_parts), tuple(params))
        chats = cursor.fetchall()

        result = []
        for chat_data in chats:
            chat = Chat(
                jid=chat_data[0],
                name=chat_data[1],
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5],
                last_read_time=datetime.fromisoformat(chat_data[6]) if chat_data[6] else None,
            )
            result.append(chat_to_dict(chat))

        return result

    except sqlite3.Error:
        print("Database error")
        return []
    finally:
        if "conn" in locals():
            conn.close()


def search_contacts(query: str) -> list[dict[str, Any]]:
    """Search contacts by name or phone number.

    Searches both the messages.db chats table and whatsmeow's contact store
    (whatsapp.db) to find contacts. Results are deduplicated by JID.
    """
    seen_jids: set[str] = set()
    result: list[dict[str, Any]] = []
    # JIDs are all ASCII so LIKE is safe; names use instr() because SQLite's
    # LOWER() only folds case for ASCII and would drop Unicode matches.
    jid_pattern = "%" + query + "%"

    # 1) Search messages.db chats table (existing behavior)
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT jid, name
            FROM chats
            WHERE
                (instr(LOWER(name), LOWER(?)) > 0 OR instr(name, ?) > 0 OR jid LIKE ?)
                AND jid NOT LIKE '%@g.us'
            ORDER BY name, jid
            LIMIT 50
        """,
            (query, query, jid_pattern),
        )
        for jid, name in cursor.fetchall():
            if jid not in seen_jids:
                seen_jids.add(jid)
                contact = Contact(phone_number=jid.split("@")[0], name=name, jid=jid)
                result.append(contact_to_dict(contact))
    except sqlite3.Error:
        print("Database error (messages.db)")
    finally:
        if "conn" in locals():
            conn.close()

    # 2) Search whatsmeow contact store (whatsapp.db)
    if os.path.exists(WHATSMEOW_DB_PATH):
        try:
            conn2 = sqlite3.connect(Path(WHATSMEOW_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
            cursor2 = conn2.cursor()
            cursor2.execute(
                """
                SELECT their_jid, full_name, push_name, first_name, business_name
                FROM whatsmeow_contacts
                WHERE
                    instr(LOWER(full_name), LOWER(?)) > 0 OR instr(full_name, ?) > 0
                    OR instr(LOWER(push_name), LOWER(?)) > 0 OR instr(push_name, ?) > 0
                    OR instr(LOWER(first_name), LOWER(?)) > 0 OR instr(first_name, ?) > 0
                    OR instr(LOWER(business_name), LOWER(?)) > 0 OR instr(business_name, ?) > 0
                    OR their_jid LIKE ?
                LIMIT 50
            """,
                (query, query, query, query, query, query, query, query, jid_pattern),
            )
            for their_jid, full_name, push_name, first_name, business_name in cursor2.fetchall():
                if their_jid not in seen_jids:
                    seen_jids.add(their_jid)
                    name = full_name or push_name or first_name or business_name or ""
                    contact = Contact(phone_number=their_jid.split("@")[0], name=name, jid=their_jid)
                    result.append(contact_to_dict(contact))
        except sqlite3.Error:
            print("Database error (whatsapp.db)")
        finally:
            if "conn2" in locals():
                conn2.close()

    return result


def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> list[dict[str, Any]]:
    """Get all chats involving the contact.

    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        aliases = _sender_aliases(jid)
        placeholders = ",".join("?" * len(aliases))
        cursor.execute(
            f"""
            SELECT DISTINCT
                c.jid,
                c.name,
                c.last_message_time,
                last_msg.content as last_message,
                last_msg.sender as last_sender,
                last_msg.is_from_me as last_is_from_me,
                {_last_read_time_select(cursor, "c")}
            FROM chats c
            {_last_message_join("c", "last_msg")}
            WHERE EXISTS (
                SELECT 1
                FROM messages contact_msg
                WHERE contact_msg.chat_jid = c.jid
                    AND contact_msg.sender IN ({placeholders})
            ) OR c.jid = ?
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """,
            (*aliases, jid, limit, page * limit),
        )

        chats = cursor.fetchall()

        result = []
        for chat_data in chats:
            chat = Chat(
                jid=chat_data[0],
                name=chat_data[1],
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5],
                last_read_time=datetime.fromisoformat(chat_data[6]) if chat_data[6] else None,
            )
            result.append(chat_to_dict(chat))

        return result

    except sqlite3.Error:
        print("Database error")
        return []
    finally:
        if "conn" in locals():
            conn.close()


def get_last_interaction(jid: str) -> dict[str, Any] | None:
    """Get most recent message involving the contact.

    Args:
        jid: The JID of the contact to search for

    Returns:
        Message dictionary or None if no messages found
    """
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        aliases = _sender_aliases(jid)
        placeholders = ",".join("?" * len(aliases))
        cursor.execute(
            f"""
            SELECT
                m.timestamp,
                m.sender,
                c.name,
                m.content,
                m.is_from_me,
                c.jid,
                m.id,
                m.media_type
                {_identity_select_columns(cursor, "m")}
            FROM messages m
            JOIN chats c ON m.chat_jid = c.jid
            WHERE m.sender IN ({placeholders}) OR c.jid = ?
            ORDER BY m.timestamp DESC
            LIMIT 1
        """,
            (*aliases, jid),
        )

        msg_data = cursor.fetchone()

        if not msg_data:
            return None

        message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[7],
            original_sender_jid=msg_data[8],
            original_chat_jid=msg_data[9],
            group_participant_jid=msg_data[10],
            resolved_sender_jid=msg_data[11],
            resolved_chat_jid=msg_data[12],
            identity_state=msg_data[13],
            chat_identity_state=msg_data[14],
        )

        return msg_to_dict(message)

    except sqlite3.Error:
        print("Database error")
        return None
    finally:
        if "conn" in locals():
            conn.close()


def get_chat(chat_jid: str, include_last_message: bool = True) -> dict[str, Any] | None:
    """Get chat metadata by JID.

    Returns:
        Chat dictionary or None if not found
    """
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        # See list_chats: the last message is always joined for is_from_me,
        # and the result tuple shape stays stable across the branch.
        if include_last_message:
            last_message_select = "m.content as last_message, m.sender as last_sender"
        else:
            last_message_select = "NULL as last_message, NULL as last_sender"

        query = f"""
            SELECT
                c.jid,
                c.name,
                c.last_message_time,
                {last_message_select},
                m.is_from_me as last_is_from_me,
                {_last_read_time_select(cursor, "c")}
            FROM chats c
            {_last_message_join("c", "m")}
            WHERE c.jid = ?
        """

        cursor.execute(query, (chat_jid,))
        chat_data = cursor.fetchone()

        if not chat_data:
            return None

        chat = Chat(
            jid=chat_data[0],
            name=chat_data[1],
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5],
            last_read_time=datetime.fromisoformat(chat_data[6]) if chat_data[6] else None,
        )
        return chat_to_dict(chat)

    except sqlite3.Error:
        print("Database error")
        return None
    finally:
        if "conn" in locals():
            conn.close()


def get_direct_chat_by_contact(sender_phone_number: str) -> dict[str, Any] | None:
    """Get chat metadata by sender phone number."""
    try:
        conn = sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me,
                {_last_read_time_select(cursor, "c")}
            FROM chats c
            {_last_message_join("c", "m")}
            WHERE c.jid LIKE ? AND c.jid NOT LIKE '%@g.us'
            LIMIT 1
        """,
            (f"%{sender_phone_number}%",),
        )

        chat_data = cursor.fetchone()

        if not chat_data:
            return None

        chat = Chat(
            jid=chat_data[0],
            name=chat_data[1],
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5],
            last_read_time=datetime.fromisoformat(chat_data[6]) if chat_data[6] else None,
        )
        return chat_to_dict(chat)

    except sqlite3.Error:
        print("Database error")
        return None
    finally:
        if "conn" in locals():
            conn.close()


def send_message(
    recipient: str,
    message: str,
    quoted_message_id: str = "",
    quoted_sender_jid: str = "",
    quoted_content: str = "",
    mentions: list[str] | None = None,
) -> tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload: dict[str, Any] = {
            "recipient": recipient,
            "message": message,
        }
        if quoted_message_id:
            payload["quoted_message_id"] = quoted_message_id
            payload["quoted_sender_jid"] = quoted_sender_jid
            payload["quoted_content"] = quoted_content
        if mentions:
            payload["mentions"] = mentions

        response = _bridge_post(url, json=payload, headers=_bridge_headers())

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def _outbound_path(media_path: str) -> str:
    if not os.getenv("WHATSAPP_AUTH_POLICY"):
        return media_path
    roots = [Path(root).resolve() for root in os.environ.get("WHATSAPP_MEDIA_ROOTS", "").split(os.pathsep) if root]
    source = Path(media_path)
    if not source.is_absolute():
        raise PermissionError("Outbound media path must be absolute")
    source = source.resolve(strict=True)
    if not source.is_file() or not any(source.is_relative_to(root) for root in roots):
        raise PermissionError("Outbound media path is outside approved roots")
    return str(source)


def send_file(recipient: str, media_path: str, caption: str = "") -> tuple[bool, str]:
    """Send a media file (image, video, document) with an optional caption.

    The bridge populates the WA media-message Caption field from `message`, so
    passing both in one /api/send call produces a single attachment-with-caption
    message instead of two separate messages.
    """
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path:
            return False, "Media path must be provided"

        media_path = _outbound_path(media_path)
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient, "media_path": media_path}
        if caption:
            payload["message"] = caption

        response = _bridge_post(url, json=payload, headers=_bridge_headers())

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_audio_message(recipient: str, media_path: str) -> tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        if not media_path:
            return False, "Media path must be provided"

        media_path = _outbound_path(media_path)
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        converted_path: str | None = None
        if not media_path.endswith(".ogg"):
            try:
                if os.getenv("WHATSAPP_AUTH_POLICY"):
                    # Stage derived audio beside approved input, so the bridge can validate it.
                    media_path = audio.convert_to_opus_ogg_temp(media_path, output_dir=str(Path(media_path).parent))
                else:
                    media_path = audio.convert_to_opus_ogg_temp(media_path)
                converted_path = media_path
            except Exception as e:
                return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"

        try:
            url = f"{WHATSAPP_API_BASE_URL}/send"
            payload = {"recipient": recipient, "media_path": media_path}

            response = _bridge_post(url, json=payload, headers=_bridge_headers())

            # Check if the request was successful
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False), result.get("message", "Unknown response")
            else:
                return False, f"Error: HTTP {response.status_code} - {response.text}"
        finally:
            # The converted file is a NamedTemporaryFile(delete=False); remove it
            # once the bridge has read it so every audio send doesn't leak an .ogg.
            if converted_path:
                try:
                    os.unlink(converted_path)
                except OSError:
                    pass

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def send_reaction(
    recipient: str,
    message_id: str,
    emoji: str,
    from_me: bool = False,
    sender_jid: str = "",
) -> tuple[bool, str]:
    """Send (or remove) a reaction to a WhatsApp message.

    Args:
        recipient: The chat JID the message belongs to (phone JID or group JID).
        message_id: The ID of the message to react to.
        emoji: The reaction emoji. Pass an empty string to remove an existing reaction.
        from_me: Whether the original message was sent by the current user.
        sender_jid: JID of the original message sender (required for group messages
                    when from_me is False so the bridge can build the correct key).

    Returns:
        Tuple of (success, status_message).
    """
    try:
        if not recipient:
            return False, "Recipient must be provided"
        if not message_id:
            return False, "Message ID must be provided"

        url = f"{WHATSAPP_API_BASE_URL}/react"
        payload: dict[str, Any] = {
            "recipient": recipient,
            "message_id": message_id,
            "emoji": emoji,
            "from_me": from_me,
            "sender_jid": sender_jid,
        }

        response = _bridge_post(url, json=payload, headers=_bridge_headers())

        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return True, "Reaction sent"
            return False, result.get("error", "Unknown error")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def mark_messages_read(
    message_ids: list[str],
    chat_jid: str,
    sender_jid: str = "",
    timestamp: str | None = None,
) -> tuple[bool, str]:
    """Mark selected messages as read through the WhatsApp bridge."""
    try:
        normalized_ids = [message_id.strip() for message_id in message_ids]
        if not normalized_ids or any(not message_id for message_id in normalized_ids):
            return False, "At least one non-empty message ID must be provided"
        if not chat_jid:
            return False, "Chat JID must be provided"
        if chat_jid.endswith("@g.us") and not sender_jid:
            return False, "Sender JID must be provided for group read receipts"

        payload: dict[str, Any] = {
            "message_ids": normalized_ids,
            "chat_jid": chat_jid,
        }
        if sender_jid:
            payload["sender_jid"] = sender_jid
        if timestamp:
            payload["timestamp"] = timestamp

        response = _bridge_post(
            f"{WHATSAPP_API_BASE_URL}/mark-read",
            json=payload,
            headers=_bridge_headers(),
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def download_media(message_id: str, chat_jid: str) -> str | None:
    """Download media from a message and return the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        The local file path if download was successful, None otherwise
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {"message_id": message_id, "chat_jid": chat_jid}

        response = _bridge_post(url, json=payload, headers=_bridge_headers())

        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                print("Media downloaded successfully")
                return path
            else:
                print("Media download failed")
                return None
        else:
            print(f"Media download HTTP error: {response.status_code}")
            return None

    except requests.RequestException:
        print("Media download request error")
        return None
    except json.JSONDecodeError:
        print("Media download response parse error")
        return None
    except Exception:
        print("Media download unexpected error")
        return None


def list_calls(chat_jid: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(Path(MESSAGES_DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM calls WHERE (? IS NULL OR chat_jid = ?) ORDER BY timestamp DESC LIMIT ?",
            (chat_jid, chat_jid, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(row) for row in rows]


def bridge_action(endpoint: str, payload: dict) -> dict:
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            f"{WHATSAPP_API_BASE_URL}/{endpoint}",
            json=payload,
            headers=_bridge_headers(),
            timeout=(5, 60),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            return {"success": False, "message": f"Bridge returned HTTP {response.status_code}"}
        return response.json()
