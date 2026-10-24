from chat_result_html import markdown_answer_to_html, render_chat_result_html, render_chat_result_plain_text


def test_markdown_answer_renders_headings_lists_and_bold():
    result = markdown_answer_to_html("## Findings\n\n- **Refunds** need attention\n- Review delays")
    assert "<h3" in result
    assert "<strong>Refunds</strong>" in result
    assert "<ul" in result


def test_markdown_table_renders_as_html_table():
    result = markdown_answer_to_html("| Category | Count |\n|---|---:|\n| Refunds | 3 |")
    assert "<table" in result
    assert "Refunds" in result
    assert "3" in result


def test_html_result_escapes_untrusted_content_and_includes_date_range():
    result = render_chat_result_html("<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "2026-10-01", "2026-10-20")
    assert "2026-10-01 to 2026-10-20" in result
    assert "&lt;script&gt;" in result
    assert "<script>alert(1)</script>" not in result
    assert "&lt;img" in result


def test_plain_email_result_includes_question_answer_and_range():
    result = render_chat_result_plain_text("What changed?", "CSAT declined.", "2026-10-01", "2026-10-20")
    assert "What changed?" in result
    assert "CSAT declined." in result
    assert "2026-10-01 to 2026-10-20" in result
