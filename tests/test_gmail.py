import base64
import email
from unittest.mock import MagicMock

import pytest

import gmail
from gmail import SCOPES, GmailDraft


def decode(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw))


# --- _raw --------------------------------------------------------------------

def test_raw_builds_html_message_with_recipients():
    msg = decode(GmailDraft._raw(["a@x.com", "b@x.com"], "Asunto", "<p>Hola ñ</p>",
                                 cc=["c@x.com"], bcc=["d@x.com"]))
    assert msg["To"] == "a@x.com, b@x.com"
    assert msg["Subject"] == "Asunto"
    assert msg["Cc"] == "c@x.com"
    assert msg["Bcc"] == "d@x.com"
    assert msg.get_content_type() == "multipart/alternative"
    part = msg.get_payload()[0]
    assert part.get_content_type() == "text/html"
    assert part.get_payload(decode=True).decode("utf-8") == "<p>Hola ñ</p>"


@pytest.mark.parametrize("empty", [None, []])
def test_raw_omits_empty_cc_and_bcc(empty):
    msg = decode(GmailDraft._raw(["a@x.com"], "s", "b", cc=empty, bcc=empty))
    assert msg["Cc"] is None
    assert msg["Bcc"] is None


# --- _authenticate -----------------------------------------------------------

@pytest.fixture
def google(monkeypatch):
    mocks = MagicMock()
    monkeypatch.setattr(gmail, "Credentials", mocks.Credentials)
    monkeypatch.setattr(gmail, "InstalledAppFlow", mocks.InstalledAppFlow)
    monkeypatch.setattr(gmail, "Request", mocks.Request)
    monkeypatch.setattr(gmail, "build", mocks.build)
    return mocks


def make(tmp_path):
    return GmailDraft(tmp_path / "credentials.json", tmp_path / "token.json")


def test_auth_uses_valid_existing_token(tmp_path, google):
    (tmp_path / "token.json").write_text("{}")
    creds = google.Credentials.from_authorized_user_file.return_value
    creds.valid = True
    draft = make(tmp_path)
    google.Credentials.from_authorized_user_file.assert_called_once_with(str(tmp_path / "token.json"), SCOPES)
    google.InstalledAppFlow.from_client_secrets_file.assert_not_called()
    creds.refresh.assert_not_called()
    google.build.assert_called_once_with("gmail", "v1", credentials=creds)
    assert draft.service is google.build.return_value
    assert (tmp_path / "token.json").read_text() == "{}"


def test_auth_refreshes_expired_token(tmp_path, google):
    (tmp_path / "token.json").write_text("{}")
    creds = google.Credentials.from_authorized_user_file.return_value
    creds.valid, creds.expired, creds.refresh_token = False, True, "r"
    creds.to_json.return_value = '{"new": true}'
    make(tmp_path)
    creds.refresh.assert_called_once_with(google.Request.return_value)
    google.InstalledAppFlow.from_client_secrets_file.assert_not_called()
    assert (tmp_path / "token.json").read_text() == '{"new": true}'


def test_auth_runs_flow_without_token(tmp_path, google):
    flow = google.InstalledAppFlow.from_client_secrets_file.return_value
    flow.run_local_server.return_value.to_json.return_value = '{"fresh": 1}'
    make(tmp_path)
    google.Credentials.from_authorized_user_file.assert_not_called()
    google.InstalledAppFlow.from_client_secrets_file.assert_called_once_with(
        str(tmp_path / "credentials.json"), SCOPES)
    flow.run_local_server.assert_called_once_with(port=0)
    assert (tmp_path / "token.json").read_text() == '{"fresh": 1}'


def test_auth_runs_flow_when_invalid_without_refresh_token(tmp_path, google):
    (tmp_path / "token.json").write_text("{}")
    creds = google.Credentials.from_authorized_user_file.return_value
    creds.valid, creds.expired, creds.refresh_token = False, True, None
    google.InstalledAppFlow.from_client_secrets_file.return_value \
        .run_local_server.return_value.to_json.return_value = "{}"
    make(tmp_path)
    creds.refresh.assert_not_called()
    google.InstalledAppFlow.from_client_secrets_file.assert_called_once()


# --- upsert ------------------------------------------------------------------

@pytest.fixture
def draft(monkeypatch):
    monkeypatch.setattr(GmailDraft, "_authenticate", lambda self: MagicMock())
    d = GmailDraft(None, None)
    d.drafts = d.service.users.return_value.drafts.return_value
    return d


def test_upsert_creates_without_draft_id(draft):
    draft.drafts.create.return_value.execute.return_value = {"id": "new"}
    result = draft.upsert(None, ["a@x.com"], "s", "<p>b</p>")
    assert result == ({"id": "new"}, "created")
    kwargs = draft.drafts.create.call_args.kwargs
    assert kwargs["userId"] == "me"
    assert decode(kwargs["body"]["message"]["raw"])["To"] == "a@x.com"
    draft.drafts.update.assert_not_called()


def test_upsert_updates_existing_draft(draft):
    draft.drafts.update.return_value.execute.return_value = {"id": "d1"}
    result = draft.upsert("d1", ["a@x.com"], "s", "b", cc=["c@x.com"])
    assert result == ({"id": "d1"}, "updated")
    kwargs = draft.drafts.update.call_args.kwargs
    assert kwargs["id"] == "d1"
    assert decode(kwargs["body"]["message"]["raw"])["Cc"] == "c@x.com"
    draft.drafts.create.assert_not_called()


def http_error(status):
    exc = Exception("http")
    exc.resp = MagicMock(status=status)
    return exc


def test_upsert_recreates_when_draft_not_found(draft):
    draft.drafts.update.return_value.execute.side_effect = http_error(404)
    draft.drafts.create.return_value.execute.return_value = {"id": "new"}
    assert draft.upsert("gone", ["a@x.com"], "s", "b") == ({"id": "new"}, "created")


@pytest.mark.parametrize("exc", [http_error(500), ValueError("no resp")])
def test_upsert_reraises_other_errors(draft, exc):
    draft.drafts.update.return_value.execute.side_effect = exc
    with pytest.raises(type(exc)):
        draft.upsert("d1", ["a@x.com"], "s", "b")
    draft.drafts.create.assert_not_called()
