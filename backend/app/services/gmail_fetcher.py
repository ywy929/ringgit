import base64
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _parse_sender(from_header: str) -> str:
    # "Touch 'n Go eWallet" <ewallet@tngdigital.com.my>  -->  ewallet@tngdigital.com.my
    m = re.search(r"<([^>]+)>", from_header)
    if m:
        return m.group(1).strip().lower()
    return from_header.strip().lower()

BANK_SENDERS = [
    "m2u@stmts.maybank2u.com.my",
    "noreply@e-statement.cimb.com",
    "noreply-correspondence@hongleongbank.com.my",
    "estatement@aeonrewards.com.my",
    "no.reply@addcard.touchngo.com.my",
    "ewallet@tngdigital.com.my",
    # Public Bank sender unverified — keeping the original guess until a real
    # statement confirms or replaces it.
    "estatement@publicbank.com.my",
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

        headers = message.get("payload", {}).get("headers", [])
        from_header = next(
            (h.get("value", "") for h in headers if h.get("name", "").lower() == "from"),
            "",
        )
        sender = _parse_sender(from_header)

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
                        "sender": sender,
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
