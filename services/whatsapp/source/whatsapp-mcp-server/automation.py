"""Offline-qualified policy primitives; no scheduler or automatic live activation.

Callbacks must be provided by a separately approved worker. Durable idempotency,
leases and audit storage are specified in the schema proposal, not created here.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyPolicy:
    typing: bool = True
    delay_seconds: float = 1.0
    max_delay_seconds: float = 5.0


def approved_reply(
    action: dict,
    policy: ReplyPolicy,
    authorize: Callable,
    typing: Callable,
    sleep: Callable,
    send: Callable,
    record: Callable,
) -> dict:
    """Exact-action authorization precedes presence and is rechecked before send.

    A transport exception produces unknown, never an automatic retry. Paused
    presence is attempted in finally, including failures/cancellation. This
    function does not equate a submitted send with delivery or read receipts.
    """
    if not 0 <= policy.delay_seconds <= policy.max_delay_seconds <= 10:
        raise ValueError("Reply delays must be bounded from 0 to 10 seconds")
    if not authorize(action, "messages.send"):
        result = {"outcome": "denied"}
        record(result)
        return result
    if policy.typing and not authorize(action, "typing.send"):
        result = {"outcome": "denied"}
        record(result)
        return result
    result = {"outcome": "unknown"}
    try:
        if policy.typing:
            typing(action["recipient"], True)
        sleep(policy.delay_seconds)
        if not authorize(action, "messages.send"):
            result = {"outcome": "denied"}
        else:
            reply = send(action)
            result = {"outcome": "submitted" if reply.get("success") else "failed", "result": reply}
    except Exception as exc:
        result = {"outcome": "unknown", "error_type": type(exc).__name__}
    finally:
        if policy.typing:
            try:
                typing(action["recipient"], False)
            except Exception as exc:
                result["presence_cleanup_error"] = type(exc).__name__
        record(result)
    return result


def eligible_call(event: dict, policy: dict, seen: set, last_response: dict, now: float) -> bool:
    """Pure eligibility check. State must be committed atomically by a future worker.

    Eligibility is not permission to reject a call or send a follow-up.
    No phone is inferred from LID or display name. Unknown callers default deny.
    """
    key = (event["account"], event["chat_jid"], event["call_id"])
    if key in seen or event.get("is_from_me"):
        return False
    category = "group" if event.get("is_group") else "known" if event.get("known_contact") else "unknown"
    if not policy.get("enabled") or not policy.get(category, False):
        return False
    caller = (event["account"], event["caller_jid"])
    return now - last_response.get(caller, float("-inf")) >= max(0, policy.get("cooldown_seconds", 3600))
