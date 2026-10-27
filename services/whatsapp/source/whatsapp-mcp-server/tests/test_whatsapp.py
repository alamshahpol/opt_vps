"""Tests for WhatsApp MCP server functions."""

import sqlite3
from datetime import datetime

import whatsapp
from whatsapp import Chat, Contact, Message, chat_to_dict, contact_to_dict, msg_to_dict


class TestMessageConversion:
    """Tests for message conversion functions."""

    def test_msg_to_dict_basic(self):
        """Test basic message to dict conversion."""
        msg = Message(
            id="msg123",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="Hello, world!",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            chat_name="John Doe",
            media_type=None,
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["id"] == "msg123"
        assert result["timestamp"] == "2024-01-15T10:30:00"
        assert result["sender_jid"] == "1234567890@s.whatsapp.net"
        assert result["sender_phone"] == "1234567890"
        assert result["content"] == "Hello, world!"
        assert result["is_from_me"] is False
        assert result["chat_jid"] == "1234567890@s.whatsapp.net"
        assert result["chat_name"] == "John Doe"
        assert result["media_type"] is None
        assert result["quoted_message_id"] is None
        assert result["reaction_to_message_id"] is None

    def test_msg_to_dict_from_me(self):
        """Test message from self shows 'Me' as sender."""
        msg = Message(
            id="msg456",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="me@s.whatsapp.net",
            content="My message",
            is_from_me=True,
            chat_jid="1234567890@s.whatsapp.net",
        )

        result = msg_to_dict(msg, include_sender_name=True)

        assert result["sender_name"] == "Me"
        assert result["sender_display"] == "Me"
        assert result["sender_push_name"] is None

    def test_msg_to_dict_exposes_source_push_name_separately(self, monkeypatch):
        msg = Message(
            id="msg-push-name",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="Hello",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
        )
        monkeypatch.setattr(whatsapp, "_resolve_push_name_from_whatsmeow", lambda jid: "Source push name")

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["sender_push_name"] == "Source push name"

    def test_msg_to_dict_preserves_original_lid_and_verified_phone(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
            connection.execute("INSERT INTO whatsmeow_lid_map VALUES (?, ?)", ("opaque-lid", "1234567890"))
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))
        message = Message(
            id="group-message",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="opaque-lid",
            content="Fixture",
            is_from_me=False,
            chat_jid="group@g.us",
            original_sender_jid="opaque-lid@lid",
            original_chat_jid="group@g.us",
            group_participant_jid="opaque-lid@lid",
            resolved_sender_jid="1234567890@s.whatsapp.net",
            resolved_chat_jid=None,
            identity_state="RESOLVED",
            chat_identity_state="UNRESOLVED",
        )

        result = msg_to_dict(message, include_sender_name=False)

        assert result["sender_jid"] == "opaque-lid@lid"
        assert result["sender_phone"] == "1234567890"
        assert result["sender_lid"] == "opaque-lid"
        assert result["resolved_sender_jid"] == "1234567890@s.whatsapp.net"
        assert result["identity_state"] == "RESOLVED"
        assert result["original_chat_jid"] == "group@g.us"
        assert result["group_participant_jid"] == "opaque-lid@lid"
        assert result["resolved_chat_jid"] is None
        assert result["chat_identity_state"] == "UNRESOLVED"

    def test_bare_numeric_sender_is_not_guessed_as_phone_or_lid(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
            connection.execute("INSERT INTO whatsmeow_lid_map VALUES (?, ?)", ("1234567890", "1234567890"))
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))

        result = msg_to_dict(
            Message(
                id="bare-id",
                timestamp=datetime(2024, 1, 15, 10, 30, 0),
                sender="1234567890",
                content="Fixture",
                is_from_me=False,
                chat_jid="1234567890",
            ),
            include_sender_name=False,
        )

        assert result["sender_jid"] == "1234567890"
        assert result["sender_phone"] is None
        assert result["sender_lid"] is None
        assert result["identity_state"] == "AMBIGUOUS"
        assert whatsapp._sender_aliases("1234567890") == ["1234567890"]

    def test_conflicting_lid_mapping_is_ambiguous(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
            connection.executemany(
                "INSERT INTO whatsmeow_lid_map VALUES (?, ?)",
                [("opaque-lid", "1234567890"), ("opaque-lid", "0987654321")],
            )
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))

        assert whatsapp._resolve_lid_to_phone("opaque-lid@lid") is None
        assert whatsapp._resolve_identity("opaque-lid@lid")["state"] == "AMBIGUOUS"

    def test_push_name_lookup_returns_only_the_whatsmeow_push_name(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE whatsmeow_contacts (
                    our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT,
                    push_name TEXT, business_name TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO whatsmeow_contacts (their_jid, full_name, push_name) VALUES (?, ?, ?)",
                ("1234567890@s.whatsapp.net", "Saved full name", "Source push name"),
            )
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))
        monkeypatch.setattr(whatsapp, "_resolve_lid_to_phone", lambda lid: "1234567890")

        assert whatsapp._resolve_push_name_from_whatsmeow("opaque-lid@lid") == "Source push name"

    def test_saved_contact_name_excludes_push_name(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE whatsmeow_contacts (
                    our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT,
                    push_name TEXT, business_name TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO whatsmeow_contacts
                    (their_jid, first_name, full_name, push_name)
                VALUES (?, ?, ?, ?)
                """,
                [
                    ("full@s.whatsapp.net", None, "Saved full name", "Source push name"),
                    ("first@s.whatsapp.net", "Saved first name", None, "Another push name"),
                    ("push@s.whatsapp.net", None, None, "Only source push name"),
                ],
            )
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))

        assert whatsapp.get_saved_contact_name("full@s.whatsapp.net") == "Saved full name"
        assert whatsapp.get_saved_contact_name("first@s.whatsapp.net") == "Saved first name"
        assert whatsapp.get_saved_contact_name("push@s.whatsapp.net") is None

    def test_saved_contact_name_resolves_only_unique_lid_mapping(self, tmp_path, monkeypatch):
        database = tmp_path / "whatsapp.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE whatsmeow_lid_map (lid TEXT, pn TEXT)")
            connection.executemany(
                "INSERT INTO whatsmeow_lid_map VALUES (?, ?)",
                [
                    ("saved-lid", "1234567890"),
                    ("ambiguous-lid", "1234567890"),
                    ("ambiguous-lid", "0987654321"),
                ],
            )
            connection.execute(
                """
                CREATE TABLE whatsmeow_contacts (
                    our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT,
                    push_name TEXT, business_name TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO whatsmeow_contacts (their_jid, full_name, push_name)
                VALUES (?, ?, ?)
                """,
                ("1234567890@s.whatsapp.net", "Saved contact", "Source push name"),
            )
        monkeypatch.setattr(whatsapp, "WHATSMEOW_DB_PATH", str(database))

        assert whatsapp.get_saved_contact_name("saved-lid@lid") == "Saved contact"
        assert whatsapp.get_saved_contact_name("unmapped-lid@lid") is None
        assert whatsapp.get_saved_contact_name("ambiguous-lid@lid") is None

    def test_msg_to_dict_with_media(self):
        """Test message with media type."""
        msg = Message(
            id="msg789",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            media_type="image",
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["media_type"] == "image"
        assert result["reaction_to_message_id"] is None

    def test_msg_to_dict_reaction_exposes_reaction_to_message_id(self):
        """Reaction messages expose the reacted-to message ID via reaction_to_message_id."""
        msg = Message(
            id="react-001",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="👍",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            media_type="reaction",
            filename="3AABCDEF01234567",  # reacted-to message ID stored in filename
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["reaction_to_message_id"] == "3AABCDEF01234567"
        assert result["quoted_message_id"] is None
        assert result["media_type"] == "reaction"

    def test_msg_to_dict_non_reaction_has_null_reaction_to_message_id(self):
        """Non-reaction messages always have reaction_to_message_id as None."""
        msg = Message(
            id="msg-img",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            media_type="image",
            filename="photo.jpg",
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["reaction_to_message_id"] is None

    def test_msg_to_dict_quoted_message_id_present(self):
        """Quoted-reply messages expose quoted_message_id."""
        msg = Message(
            id="reply-001",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="Great point!",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            quoted_message_id="3AORIGINAL0000001",
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["quoted_message_id"] == "3AORIGINAL0000001"
        assert result["reaction_to_message_id"] is None

    def test_msg_to_dict_quoted_message_id_absent(self):
        """Plain messages have quoted_message_id as None."""
        msg = Message(
            id="plain-001",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="Hello!",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["quoted_message_id"] is None
        assert result["reaction_to_message_id"] is None

    def test_msg_to_dict_reaction_preserves_quoted_message_id(self):
        """Reaction messages still include quoted_message_id if the row has one."""
        msg = Message(
            id="react-quote-001",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            sender="1234567890@s.whatsapp.net",
            content="👍",
            is_from_me=False,
            chat_jid="1234567890@s.whatsapp.net",
            media_type="reaction",
            filename="3AREACTED0000001",
            quoted_message_id="3AORIGINAL0000001",
        )

        result = msg_to_dict(msg, include_sender_name=False)

        assert result["reaction_to_message_id"] == "3AREACTED0000001"
        assert result["quoted_message_id"] == "3AORIGINAL0000001"


class TestChatConversion:
    """Tests for chat conversion functions."""

    def test_chat_to_dict_dm(self):
        """Test direct message chat conversion."""
        chat = Chat(
            jid="1234567890@s.whatsapp.net",
            name="John Doe",
            last_message_time=datetime(2024, 1, 15, 10, 30, 0),
            last_message="Hello!",
            last_sender="1234567890@s.whatsapp.net",
            last_is_from_me=False,
        )

        result = chat_to_dict(chat)

        assert result["jid"] == "1234567890@s.whatsapp.net"
        assert result["name"] == "John Doe"
        assert result["is_group"] is False
        assert result["last_message_time"] == "2024-01-15T10:30:00"
        assert result["last_message"] == "Hello!"

    def test_chat_to_dict_group(self):
        """Test group chat conversion."""
        chat = Chat(
            jid="123456789@g.us",
            name="Family Group",
            last_message_time=datetime(2024, 1, 15, 10, 30, 0),
        )

        result = chat_to_dict(chat)

        assert result["jid"] == "123456789@g.us"
        assert result["is_group"] is True

    def test_chat_to_dict_no_last_message(self):
        """Test chat without last message time."""
        chat = Chat(
            jid="1234567890@s.whatsapp.net",
            name="Jane Doe",
            last_message_time=None,
        )

        result = chat_to_dict(chat)

        assert result["last_message_time"] is None


class TestContactConversion:
    """Tests for contact conversion functions."""

    def test_contact_to_dict(self):
        """Test contact to dict conversion."""
        contact = Contact(
            phone_number="1234567890",
            name="John Doe",
            jid="1234567890@s.whatsapp.net",
        )

        result = contact_to_dict(contact)

        assert result["phone_number"] == "1234567890"
        assert result["name"] == "John Doe"
        assert result["jid"] == "1234567890@s.whatsapp.net"

    def test_contact_to_dict_no_name(self):
        """Test contact without name."""
        contact = Contact(
            phone_number="9876543210",
            name=None,
            jid="9876543210@s.whatsapp.net",
        )

        result = contact_to_dict(contact)

        assert result["name"] is None
