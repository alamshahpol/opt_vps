import sqlite3

import pytest

import native_reader
from native_reader import NativeReadError, WhatsmeowSessionIdentityReader


def make_session_db(path, devices):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE whatsmeow_device (jid TEXT, lid TEXT)")
        db.execute("CREATE TABLE messages (content TEXT)")
        db.execute("INSERT INTO messages VALUES (?)", ("must-not-be-exposed",))
        db.executemany("INSERT INTO whatsmeow_device VALUES (?,?)", devices)


def reader_for(path):
    reader = object.__new__(WhatsmeowSessionIdentityReader)
    reader.path = path
    reader.account = "wa-02"
    return reader


def test_session_identity_reads_only_verified_device_identity(tmp_path):
    path = tmp_path / "whatsapp.db"
    make_session_db(path, [("8801880446111:27@s.whatsapp.net", "93282931581172:27@lid")])

    result = reader_for(path).identity()

    assert result == {
        "version": "native-account-v1",
        "accountId": "wa-02",
        "nativeScope": {
            "accountId": "wa-02",
            "pairedJid": "8801880446111:27@s.whatsapp.net",
            "pairedLid": "93282931581172:27@lid",
        },
        "evidenceState": "PERSISTED_NATIVE",
        "operationalAuthority": "NONE",
    }
    assert "must-not-be-exposed" not in str(result)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


@pytest.mark.parametrize(
    "devices",
    [
        [],
        [
            ("8801880446111@s.whatsapp.net", "93282931581172@lid"),
            ("8801880446222@s.whatsapp.net", "93282931582222@lid"),
        ],
        [("not-a-jid", "93282931581172@lid")],
        [("8801880446111@s.whatsapp.net", "not-a-lid")],
    ],
)
def test_session_identity_rejects_missing_ambiguous_or_invalid_device_rows(tmp_path, devices):
    path = tmp_path / "whatsapp.db"
    make_session_db(path, devices)

    with pytest.raises(NativeReadError, match="NATIVE_ACCOUNT_MISMATCH"):
        reader_for(path).identity()


def test_session_identity_configuration_rejects_unapproved_database_path(monkeypatch, tmp_path):
    monkeypatch.setenv("WHATSMEOW_DB_PATH", str(tmp_path / "other.db"))
    monkeypatch.setenv("WHATSAPP_ACCOUNT_ALIAS", "wa-02")

    with pytest.raises(NativeReadError, match="NATIVE_IDENTITY_SOURCE_DENIED"):
        native_reader.configure_session_identity_reader()


def test_session_identity_configuration_ignores_other_account_aliases(monkeypatch, tmp_path):
    monkeypatch.setattr(native_reader, "_session_identity_reader", None)
    monkeypatch.setenv("WHATSMEOW_DB_PATH", str(tmp_path / "other.db"))
    monkeypatch.setenv("WHATSAPP_ACCOUNT_ALIAS", "synthetic")

    native_reader.configure_session_identity_reader()

    assert native_reader._session_identity_reader is None
