import base64
from unittest.mock import MagicMock

from app.services.gmail_fetcher import GmailFetcher, BANK_SENDERS, _parse_sender


def test_bank_senders_defined():
    assert len(BANK_SENDERS) >= 5


def test_build_search_query():
    fetcher = GmailFetcher.__new__(GmailFetcher)
    query = fetcher._build_search_query(after_date="2026-04-01")
    assert "from:" in query
    assert "after:" in query
    assert "has:attachment" in query


def test_parse_sender_from_angle_bracket_form():
    assert _parse_sender('"Touch \'n Go" <ewallet@tngdigital.com.my>') == "ewallet@tngdigital.com.my"


def test_parse_sender_from_bare_email():
    assert _parse_sender("ewallet@tngdigital.com.my") == "ewallet@tngdigital.com.my"


def test_parse_sender_lowercases():
    assert _parse_sender("FOO@BAR.COM") == "foo@bar.com"


def test_extract_pdf_attachments_includes_sender():
    fetcher = GmailFetcher.__new__(GmailFetcher)

    fake_pdf_content = b"%PDF-1.4 fake content"
    encoded = base64.urlsafe_b64encode(fake_pdf_content).decode()

    mock_service = MagicMock()
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "payload": {
            "headers": [
                {"name": "From", "value": '"TNG eWallet" <ewallet@tngdigital.com.my>'},
                {"name": "To", "value": "user@gmail.com"},
            ],
            "parts": [
                {
                    "filename": "tng_ewallet_transactions.pdf",
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
    assert attachments[0]["filename"] == "tng_ewallet_transactions.pdf"
    assert attachments[0]["content"] == fake_pdf_content
    assert attachments[0]["sender"] == "ewallet@tngdigital.com.my"


def test_extract_pdf_attachments_accepts_octet_stream_with_pdf_filename():
    # Maybank (and other banks) send PDF attachments with mime type
    # application/octet-stream rather than application/pdf. The fetcher
    # must accept the attachment based on filename suffix.
    fetcher = GmailFetcher.__new__(GmailFetcher)
    fake_pdf_content = b"%PDF-1.4 maybank-shaped"
    encoded = base64.urlsafe_b64encode(fake_pdf_content).decode()

    mock_service = MagicMock()
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg2",
        "payload": {
            "headers": [
                {"name": "From", "value": "M2U Statements <m2u@stmts.maybank2u.com.my>"},
            ],
            "parts": [
                {
                    "filename": "847673614_20260331_7244.pdf",
                    "mimeType": "application/octet-stream",
                    "body": {"attachmentId": "att2"},
                }
            ]
        }
    }
    mock_service.users().messages().attachments().get().execute.return_value = {
        "data": encoded
    }

    fetcher.service = mock_service
    attachments = fetcher._get_pdf_attachments("msg2")

    assert len(attachments) == 1
    assert attachments[0]["filename"] == "847673614_20260331_7244.pdf"
    assert attachments[0]["content"] == fake_pdf_content
    assert attachments[0]["sender"] == "m2u@stmts.maybank2u.com.my"


def test_extract_pdf_attachments_skips_non_pdf_filenames():
    # A non-PDF attachment (e.g., signature.png, calendar.ics) must NOT be
    # picked up even if multipart structure includes it.
    fetcher = GmailFetcher.__new__(GmailFetcher)
    mock_service = MagicMock()
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg3",
        "payload": {
            "headers": [{"name": "From", "value": "x@example.com"}],
            "parts": [
                {
                    "filename": "signature.png",
                    "mimeType": "image/png",
                    "body": {"attachmentId": "img1"},
                },
            ],
        },
    }
    fetcher.service = mock_service
    attachments = fetcher._get_pdf_attachments("msg3")
    assert attachments == []
