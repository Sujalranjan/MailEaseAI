from datetime import timezone

from app.services.email_normalizer import categorize_email, get_email_body, normalize_message


class TestCategorizeEmail:
    def test_high_priority_keyword_in_subject(self):
        assert categorize_email("URGENT: server down", "please look now") == "High"

    def test_medium_priority_keyword(self):
        assert categorize_email("Reminder", "don't forget the call tomorrow") == "Medium"

    def test_low_priority_default(self):
        assert categorize_email("Newsletter", "here's what's new this month") == "Low"

    def test_case_insensitive(self):
        assert categorize_email("Deadline Approaching", "") == "High"


class TestGetEmailBody:
    def test_plain_text_message(self):
        import email

        msg = email.message_from_string("Content-Type: text/plain\n\nHello world")
        assert get_email_body(msg) == "Hello world"

    def test_multipart_mixed_with_attachment_first(self):
        import email

        raw = (
            "Content-Type: multipart/mixed; boundary=BOUND\n\n"
            "--BOUND\n"
            "Content-Type: application/pdf\n"
            "Content-Disposition: attachment; filename=report.pdf\n\n"
            "%PDF-fake-binary\n"
            "--BOUND\n"
            "Content-Type: text/plain\n\n"
            "The actual message body\n"
            "--BOUND--"
        )
        msg = email.message_from_string(raw)
        assert get_email_body(msg) == "The actual message body"

    def test_falls_back_to_html_when_no_plain_text(self):
        import email

        raw = (
            "Content-Type: multipart/alternative; boundary=BOUND\n\n"
            "--BOUND\n"
            "Content-Type: text/html\n\n"
            "<p>Hello <b>HTML</b> world</p>\n"
            "--BOUND--"
        )
        msg = email.message_from_string(raw)
        assert "Hello" in get_email_body(msg)
        assert "HTML" in get_email_body(msg)

    def test_nested_multipart_alternative_inside_mixed(self):
        import email

        raw = (
            "Content-Type: multipart/mixed; boundary=OUTER\n\n"
            "--OUTER\n"
            "Content-Type: multipart/alternative; boundary=INNER\n\n"
            "--INNER\n"
            "Content-Type: text/plain\n\n"
            "Plain body inside nested alternative\n"
            "--INNER\n"
            "Content-Type: text/html\n\n"
            "<p>HTML body</p>\n"
            "--INNER--\n"
            "--OUTER\n"
            "Content-Type: application/pdf\n"
            "Content-Disposition: attachment; filename=x.pdf\n\n"
            "%PDF-fake\n"
            "--OUTER--"
        )
        msg = email.message_from_string(raw)
        assert get_email_body(msg) == "Plain body inside nested alternative"

    def test_empty_message_has_placeholder(self):
        import email

        msg = email.message_from_string("Content-Type: text/plain\n\n")
        assert get_email_body(msg) == "(no readable content)"


class TestNormalizeMessage:
    def test_parses_sender_name_and_email(self):
        raw = b"From: Jane Doe <jane@example.com>\nSubject: Hi\nContent-Type: text/plain\n\nHello"
        result = normalize_message(raw)
        assert result.sender_name == "Jane Doe"
        assert result.sender_email == "jane@example.com"

    def test_sender_without_display_name(self):
        raw = b"From: jane@example.com\nSubject: Hi\nContent-Type: text/plain\n\nHello"
        result = normalize_message(raw)
        assert result.sender_name is None
        assert result.sender_email == "jane@example.com"

    def test_recipients_combines_to_and_cc_as_addresses_only(self):
        raw = (
            b"From: a@example.com\n"
            b"To: Bob <bob@example.com>, carol@example.com\n"
            b"Cc: Dan <dan@example.com>\n"
            b"Subject: Hi\nContent-Type: text/plain\n\nHello"
        )
        result = normalize_message(raw)
        assert result.recipients == ["bob@example.com", "carol@example.com", "dan@example.com"]

    def test_threading_headers_captured(self):
        raw = (
            b"From: a@example.com\nSubject: Re: Hi\n"
            b"In-Reply-To: <orig@example.com>\n"
            b"References: <orig@example.com> <mid@example.com>\n"
            b"Content-Type: text/plain\n\nHello"
        )
        result = normalize_message(raw)
        assert result.in_reply_to == "<orig@example.com>"
        assert result.references_header == "<orig@example.com> <mid@example.com>"

    def test_received_at_normalized_to_utc(self):
        # +05:30 offset; should come back as a UTC-equivalent instant
        raw = (
            b"From: a@example.com\nSubject: Hi\n"
            b"Date: Tue, 15 Sep 2026 10:00:00 +0530\n"
            b"Content-Type: text/plain\n\nHello"
        )
        result = normalize_message(raw)
        assert result.received_at.tzinfo is not None
        assert result.received_at.astimezone(timezone.utc).hour == 4
        assert result.received_at.astimezone(timezone.utc).minute == 30

    def test_received_at_none_when_date_header_missing(self):
        raw = b"From: a@example.com\nSubject: Hi\nContent-Type: text/plain\n\nHello"
        result = normalize_message(raw)
        assert result.received_at is None

    def test_missing_message_id_is_none(self):
        raw = b"From: a@example.com\nSubject: Hi\nContent-Type: text/plain\n\nHello"
        result = normalize_message(raw)
        assert result.message_id is None

    def test_urgency_still_computed(self):
        raw = (
            b"From: a@example.com\nSubject: URGENT\n"
            b"Content-Type: text/plain\n\nSubmit by 15/09/2026"
        )
        result = normalize_message(raw)
        assert result.category == "High"
