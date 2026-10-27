import pytest

from automation import ReplyPolicy, approved_reply, eligible_call


def test_reply_order_and_bounded_delay():
    trace = []
    action = {"recipient": "synthetic", "content": "approved", "approval_id": "fixture"}
    result = approved_reply(
        action,
        ReplyPolicy(delay_seconds=2),
        lambda a, scope: trace.append(("approve", scope)) or True,
        lambda recipient, composing: trace.append(("typing", composing)),
        lambda delay: trace.append(("delay", delay)),
        lambda a: trace.append(("send", a)) or {"success": True},
        lambda r: trace.append(("record", r["outcome"])),
    )
    assert result["outcome"] == "submitted"
    assert trace == [
        ("approve", "messages.send"),
        ("approve", "typing.send"),
        ("typing", True),
        ("delay", 2),
        ("approve", "messages.send"),
        ("send", action),
        ("typing", False),
        ("record", "submitted"),
    ]


def test_denied_reply_has_no_presence_or_send():
    calls = []
    result = approved_reply(
        {},
        ReplyPolicy(),
        lambda *_: False,
        lambda *_: calls.append("typing"),
        lambda *_: calls.append("delay"),
        lambda *_: calls.append("send"),
        lambda _: None,
    )
    assert result["outcome"] == "denied" and calls == []


def test_send_exception_stops_presence_without_retry():
    calls = []

    def send(_):
        calls.append("send")
        raise TimeoutError()

    result = approved_reply(
        {"recipient": "synthetic"},
        ReplyPolicy(),
        lambda *_: True,
        lambda _, state: calls.append(state),
        lambda _: None,
        send,
        lambda _: None,
    )
    assert result["outcome"] == "unknown" and calls == [True, "send", False]


def test_bad_delay_rejected():
    with pytest.raises(ValueError):
        approved_reply({}, ReplyPolicy(delay_seconds=11), None, None, None, None, None)


def test_call_duplicate_cooldown_and_category_scope():
    event = {
        "account": "fixture-a",
        "chat_jid": "chat",
        "call_id": "call",
        "caller_jid": "caller",
        "known_contact": True,
    }
    policy = {"enabled": True, "known": True, "cooldown_seconds": 60}
    assert eligible_call(event, policy, set(), {}, 100)
    assert not eligible_call(event, policy, {("fixture-a", "chat", "call")}, {}, 100)
    assert not eligible_call(event, policy, set(), {("fixture-a", "caller"): 70}, 100)
    assert not eligible_call(dict(event, is_group=True), policy, set(), {}, 100)
    assert not eligible_call(dict(event, known_contact=False), policy, set(), {}, 100)
    assert eligible_call(dict(event, account="fixture-b"), policy, set(), {("fixture-a", "caller"): 99}, 100)
