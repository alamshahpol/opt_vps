"""Explicit startup admission for existing scoped reader. Default disabled."""

import json
import os
import re
from pathlib import Path

from capabilities import grants
from native_reader import DisposableNativeReader, NativePrincipal, NativeReadError, install_disposable_reader

JID_PATTERN = re.compile(r"[A-Za-z0-9_.:+-]{1,160}@(s\.whatsapp\.net|lid|g\.us)")


def configure_native_profile(path=None):
    path = os.environ.get("WHATSAPP_NATIVE_READER_PROFILE") if path is None else path
    if not path:
        return
    # Legacy authenticated readers do not acquire native authority.
    scope = grants()
    identity_only = scope is not None and "native.identity.read" in scope and "native.events.read" not in scope
    if scope is not None and "native.events.read" not in scope and not identity_only:
        return
    simulated = os.environ.get("B01_B03_NATIVE_PROFILE_MODE") == "simulated-live"
    account = os.environ.get("WHATSAPP_ACCOUNT_ALIAS")
    expected = (
        "/qualification/disposable/native-reader-profile-" + str(account) + ".json"
        if simulated
        else "/runtime/control/native-reader-profile.json"
    )
    if path != expected:
        raise NativeReadError("NATIVE_PROFILE_PATH_DENIED")
    mode = "simulated-live" if simulated else "live"
    target = Path(path)
    if identity_only and not target.exists():
        return
    info = target.lstat()
    if target.is_symlink() or not target.is_file() or info.st_size > 32000 or info.st_mode & 0o022:
        raise NativeReadError("NATIVE_PROFILE_DENIED")
    p = json.loads(target.read_text())
    if p.get("mode") != mode or p.get("account") != account:
        raise NativeReadError("NATIVE_PROFILE_DENIED")
    consumers = p.get("consumers")
    consumer = os.environ.get("WHATSAPP_CONSUMER_ID")
    entry = consumers.get(consumer) if isinstance(consumers, dict) else None
    chats = entry.get("chats") if isinstance(entry, dict) else None
    if (
        not isinstance(chats, list)
        or (identity_only and chats)
        or (not identity_only and not 0 < len(chats) <= 200)
        or len(chats) > 200
        or any(not isinstance(c, str) or not JID_PATTERN.fullmatch(c) for c in chats)
    ):
        raise NativeReadError("NATIVE_PROFILE_DENIED")

    def principal():
        current = json.loads(target.read_text())
        if current.get("binding") != p["binding"] or current.get("account") != account or current.get("mode") != mode:
            raise NativeReadError("NATIVE_ACCESS_DENIED")
        scope = current.get("consumers", {}).get(consumer, {})
        if scope.get("chats") != chats or not isinstance(scope.get("epoch"), int) or scope["epoch"] < 1:
            raise NativeReadError("NATIVE_ACCESS_REVOKED")
        g = grants()
        if (
            g is None
            or identity_only
            and ("native.identity.read" not in g or "native.events.read" in g)
            or not identity_only
            and "native.events.read" not in g
        ):
            raise NativeReadError("NATIVE_ACCESS_DENIED")
        participants = scope.get("participants", {})
        if (
            not isinstance(participants, dict)
            or any(not isinstance(chat, str) or chat not in chats for chat in participants)
            or any(
                not isinstance(members, list)
                or len(members) > 1000
                or any(not isinstance(member, str) or not JID_PATTERN.fullmatch(member) for member in members)
                or len(set(members)) != len(members)
                for members in participants.values()
            )
            or any(chat.endswith("@g.us") and not participants.get(chat) for chat in chats)
        ):
            raise NativeReadError("NATIVE_PARTICIPANT_SCOPE_DENIED")
        return NativePrincipal(
            consumer,
            scope["epoch"],
            account,
            frozenset(chats),
            not identity_only and "native.content.read" in g,
            tuple(sorted((c, frozenset(v)) for c, v in participants.items())),
        )

    reader = DisposableNativeReader(p["path"], account, p["binding"], principal, profile_mode=mode)
    install_disposable_reader(reader)
