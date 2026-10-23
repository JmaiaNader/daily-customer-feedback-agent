from pathlib import Path


APP_SOURCE = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")


def test_admin_uses_separate_navigation_pages_for_chat_and_settings():
    assert '"Chat assistant", "Settings"' in APP_SOURCE
    assert 'elif page == "Chat assistant":' in APP_SOURCE
    assert 'elif page == "Settings":' in APP_SOURCE
    assert 'st.tabs(' not in APP_SOURCE


def test_recipient_management_is_on_settings_page_not_chat_page():
    chat_page = APP_SOURCE.index('elif page == "Chat assistant":')
    settings_page = APP_SOURCE.index('elif page == "Settings":')
    recipient_ui = APP_SOURCE.index('st.subheader("Manage report recipient lists")')
    assert chat_page < settings_page < recipient_ui
    assert recipient_ui > APP_SOURCE.index('elif page == "Settings":')


def test_feedback_assistant_has_its_own_page_and_settings_saved_in_session():
    assert 'st.subheader("CSAT Data Assistant")' in APP_SOURCE
    assert 'st.session_state["app_settings"] = {' in APP_SOURCE
