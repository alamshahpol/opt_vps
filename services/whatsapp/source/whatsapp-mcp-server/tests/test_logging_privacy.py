"""Synthetic logging checks; no bridge calls or live stores."""

from unittest.mock import Mock

import pytest
import requests

import whatsapp


@pytest.mark.parametrize("case", ["success", "failure", "http", "json", "request"])
def test_download_logs_omit_private_fields(monkeypatch, capsys, case):
    private = "SYNTHETIC_PRIVATE_IDENTIFIER_PATH_TOKEN_BODY"
    response = Mock(status_code=200, text=private)
    response.json.return_value = {"success": True, "path": f"/private/{private}"}
    if case == "failure":
        response.json.return_value = {"success": False, "message": private}
    elif case == "http":
        response.status_code = 403
    elif case == "json":
        response.json.side_effect = whatsapp.json.JSONDecodeError("bad", private, 0)
    post = Mock(return_value=response)
    if case == "request":
        post.side_effect = requests.RequestException(private)
    monkeypatch.setattr(whatsapp, "_bridge_post", post)
    monkeypatch.setattr(whatsapp, "_bridge_headers", lambda: {})
    result = whatsapp.download_media(private, private)
    assert result == (f"/private/{private}" if case == "success" else None)
    logs = capsys.readouterr()
    assert private not in logs.err + logs.out
    assert logs.err
    assert not logs.out


def test_database_error_log_omits_exception_details(monkeypatch, capsys):
    private = "SYNTHETIC_PRIVATE_DATABASE_PATH"
    monkeypatch.setattr(
        whatsapp.sqlite3,
        "connect",
        Mock(side_effect=whatsapp.sqlite3.OperationalError(private)),
    )
    assert whatsapp.list_messages(query="synthetic", include_context=False) == []
    logs = capsys.readouterr()
    assert private not in logs.err
    assert "Database error" in logs.err
