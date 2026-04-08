import base64
from unittest.mock import MagicMock

from app.services.gmail_fetcher import GmailFetcher, BANK_SENDERS


def test_bank_senders_defined():
    assert len(BANK_SENDERS) >= 5


def test_build_search_query():
    fetcher = GmailFetcher.__new__(GmailFetcher)
    query = fetcher._build_search_query(after_date="2026-04-01")
    assert "from:" in query
    assert "after:" in query
    assert "has:attachment" in query


def test_extract_pdf_attachments():
    fetcher = GmailFetcher.__new__(GmailFetcher)

    fake_pdf_content = b"%PDF-1.4 fake content"
    encoded = base64.urlsafe_b64encode(fake_pdf_content).decode()

    mock_service = MagicMock()
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "payload": {
            "parts": [
                {
                    "filename": "maybank-apr.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att1"},
                }
            ]
        }
    }
    mock_service.users().messages().attachments().get().execute.return_value = {
        "data": encoded
    }

    fetcher.service = mock_service
    attachments = fetcher._get_pdf_attachments("msg1")

    assert len(attachments) == 1
    assert attachments[0]["filename"] == "maybank-apr.pdf"
    assert attachments[0]["content"] == fake_pdf_content
