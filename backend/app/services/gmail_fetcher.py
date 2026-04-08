import base64

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BANK_SENDERS = [
    "estatement@maybank.com.my",
    "estatement@cimb.com.my",
    "estatement@publicbank.com.my",
    "estatement@hongleong.com.my",
    "noreply@aeoncredit.com.my",
]


class GmailFetcher:
    def __init__(self, credentials: Credentials):
        self.service = build("gmail", "v1", credentials=credentials)

    def _build_search_query(self, after_date: str | None = None) -> str:
        sender_query = " OR ".join(f"from:{s}" for s in BANK_SENDERS)
        query = f"({sender_query}) has:attachment filename:pdf"
        if after_date:
            query += f" after:{after_date}"
        return query

    def _get_pdf_attachments(self, message_id: str) -> list[dict]:
        message = self.service.users().messages().get(
            userId="me", id=message_id
        ).execute()

        attachments = []
        parts = message.get("payload", {}).get("parts", [])

        for part in parts:
            if part.get("mimeType") == "application/pdf" and part.get("filename"):
                att_id = part["body"].get("attachmentId")
                if att_id:
                    att = self.service.users().messages().attachments().get(
                        userId="me", messageId=message_id, id=att_id
                    ).execute()
                    content = base64.urlsafe_b64decode(att["data"])
                    attachments.append({
                        "filename": part["filename"],
                        "content": content,
                    })

        return attachments

    def fetch_statements(self, after_date: str | None = None) -> list[dict]:
        query = self._build_search_query(after_date)
        results = self.service.users().messages().list(
            userId="me", q=query
        ).execute()

        messages = results.get("messages", [])
        all_attachments = []

        for msg in messages:
            attachments = self._get_pdf_attachments(msg["id"])
            all_attachments.extend(attachments)

        return all_attachments
