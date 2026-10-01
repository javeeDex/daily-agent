import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

class GmailDraft:
    def __init__(self, credentials_file: Path, token_file: Path):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = self._authenticate()

    def _authenticate(self):
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds)

    @staticmethod
    def _raw(to, subject, html_body, cc=None, bcc=None):
        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc: msg["Cc"] = ", ".join(cc)
        if bcc: msg["Bcc"] = ", ".join(bcc)
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def upsert(self, draft_id, to, subject, html_body, cc=None, bcc=None):
        body = {"message": {"raw": self._raw(to, subject, html_body, cc, bcc)}}
        if draft_id:
            try:
                return self.service.users().drafts().update(userId="me", id=draft_id, body=body).execute(), "updated"
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status != 404:
                    raise
        return self.service.users().drafts().create(userId="me", body=body).execute(), "created"
