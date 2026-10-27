import hashlib
import json
import stat

import pytest

import native_profile
from native_reader import NativeReadError


def configure_identity_consumer(monkeypatch, tmp_path, chats=None, capabilities=None, participants=None):
    token = "synthetic-native-identity-token"
    token_path = tmp_path / "consumer-token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "consumers": [
                    {
                        "id": "wa-02-owner-reader",
                        "account": "wa-02",
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "capabilities": capabilities or ["native.identity.read"],
                    }
                ]
            }
        )
    )
    policy_path.chmod(0o600)
    monkeypatch.setenv("WHATSAPP_AUTH_POLICY", str(policy_path))
    monkeypatch.setenv("WHATSAPP_ACCOUNT_ALIAS", "wa-02")
    monkeypatch.setenv("WHATSAPP_CONSUMER_ID", "wa-02-owner-reader")
    monkeypatch.setenv("WHATSAPP_CONSUMER_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("WHATSAPP_NATIVE_READER_PROFILE", "/runtime/control/native-reader-profile.json")

    profile_path = tmp_path / "native-reader-profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "mode": "live",
                "account": "wa-02",
                "path": "/runtime/store/messages.db",
                "binding": {
                    "accountId": "wa-02",
                    "streamId": "12345678-1234-1234-1234-123456789abc",
                    "pairedJid": "10000000000:1@s.whatsapp.net",
                    "pairedLid": "10000000000000:1@lid",
                },
                "consumers": {
                    "wa-02-owner-reader": {
                        "epoch": 1,
                        "chats": [] if chats is None else chats,
                        "participants": {} if participants is None else participants,
                    }
                },
            }
        )
    )
    profile_path.chmod(stat.S_IRUSR | stat.S_IRGRP)

    real_path = native_profile.Path
    monkeypatch.setattr(
        native_profile,
        "Path",
        lambda value: profile_path if value == "/runtime/control/native-reader-profile.json" else real_path(value),
    )
    return profile_path, policy_path


def install_reader_spy(monkeypatch):
    installed = []

    class Reader:
        def __init__(self, path, account, binding, authorize, *, profile_mode):
            self.authorize = authorize

    monkeypatch.setattr(native_profile, "DisposableNativeReader", Reader)
    monkeypatch.setattr(native_profile, "install_disposable_reader", installed.append)
    return installed


def test_identity_only_profile_accepts_empty_chat_scope(monkeypatch, tmp_path):
    configure_identity_consumer(monkeypatch, tmp_path)
    installed = install_reader_spy(monkeypatch)

    native_profile.configure_native_profile()

    assert len(installed) == 1
    principal = installed[0].authorize()
    assert principal.subject == "wa-02-owner-reader"
    assert principal.account == "wa-02"
    assert principal.chats == frozenset()
    assert principal.content is False


def test_identity_only_profile_never_enables_content(monkeypatch, tmp_path):
    configure_identity_consumer(
        monkeypatch,
        tmp_path,
        capabilities=["native.identity.read", "native.content.read"],
    )
    installed = install_reader_spy(monkeypatch)

    native_profile.configure_native_profile()

    assert installed[0].authorize().content is False


def test_identity_only_profile_rejects_chat_scope(monkeypatch, tmp_path):
    configure_identity_consumer(monkeypatch, tmp_path, ["123456789@s.whatsapp.net"])
    install_reader_spy(monkeypatch)

    with pytest.raises(NativeReadError, match="NATIVE_PROFILE_DENIED"):
        native_profile.configure_native_profile()


def test_identity_only_profile_revocation_is_checked(monkeypatch, tmp_path):
    _, policy_path = configure_identity_consumer(monkeypatch, tmp_path)
    installed = install_reader_spy(monkeypatch)
    native_profile.configure_native_profile()

    policy_path.write_text('{"consumers": []}')
    with pytest.raises(PermissionError, match="Consumer authentication failed"):
        installed[0].authorize()


def test_native_profile_rejects_participants_outside_approved_chats(monkeypatch, tmp_path):
    configure_identity_consumer(
        monkeypatch,
        tmp_path,
        chats=["10000000000@s.whatsapp.net"],
        capabilities=["native.events.read", "native.contacts.read"],
        participants={"10000000000@g.us": ["20000000000@s.whatsapp.net"]},
    )
    installed = install_reader_spy(monkeypatch)
    native_profile.configure_native_profile()

    with pytest.raises(NativeReadError, match="NATIVE_PARTICIPANT_SCOPE_DENIED"):
        installed[0].authorize()
