"""Participant-facing Streamlit feedback form.

Run separately from the admin dashboard with: streamlit run feedback_app.py
Only the participant's name, feedback, and CSAT score are entered by the user.
The backend generates all operational fields and writes to the configured Google Sheet.
"""
from __future__ import annotations

import streamlit as st

from feedback_service import submit_feedback, validate_submission


st.set_page_config(
    page_title="Customer Feedback",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def _process_submission() -> None:
    """Submit form values from session state before the next app render."""
    customer_name = st.session_state.get("customer_name", "")
    customer_comment = st.session_state.get("customer_comment", "")
    csat_score = st.session_state.get("csat_score", 5)

    try:
        # Validate before attempting authentication/network access. The service
        # repeats validation before writing, so callers cannot bypass it.
        validate_submission(customer_name, customer_comment, csat_score)
        result = submit_feedback(customer_name, customer_comment, csat_score)
    except ValueError as exc:
        st.session_state["_feedback_form_status"] = ("error", str(exc))
        return
    except Exception as exc:  # Do not expose credentials or API details to participants.
        print(f"CSAT feedback submission failed: {type(exc).__name__}: {exc}")
        st.session_state["_feedback_form_status"] = (
            "error",
            "We couldn't save your feedback. Please notify the workshop organizer and try again.",
        )
        return

    # Clear inputs only after Google Sheets confirms that a row was appended.
    st.session_state["customer_name"] = ""
    st.session_state["customer_comment"] = ""
    st.session_state["csat_score"] = 5
    st.session_state["_feedback_form_status"] = (
        "success",
        f"Thank you! Your feedback was saved. Reference: {result['survey_id']}",
    )


st.title("Share your feedback")
st.write(
    "Please tell us about your experience. Your feedback helps us understand "
    "what is working well and where we can improve."
)
st.caption("Please submit one response per workshop feedback exercise.")

# Display a status once after a form callback. Popping it avoids stale success or
# error messages remaining after a later unrelated rerun.
status = st.session_state.pop("_feedback_form_status", None)
if status:
    kind, message = status
    if kind == "success":
        st.success(message)
    else:
        st.error(message)

with st.form("participant_feedback_form", clear_on_submit=False):
    st.text_input(
        "Your name",
        key="customer_name",
        max_chars=100,
        placeholder="Enter your name",
        help="Enter the name you want associated with this workshop feedback.",
    )
    st.text_area(
        "Your feedback",
        key="customer_comment",
        max_chars=5000,
        height=150,
        placeholder="Tell us about your experience...",
    )
    st.markdown("**How satisfied are you?**")
    st.caption("1 = Very dissatisfied · 2 = Dissatisfied · 3 = Neutral · 4 = Satisfied · 5 = Very satisfied")
    st.radio(
        "CSAT score",
        options=[1, 2, 3, 4, 5],
        index=4,
        horizontal=True,
        key="csat_score",
        label_visibility="collapsed",
    )
    st.form_submit_button(
        "Submit feedback",
        type="primary",
        use_container_width=True,
        on_click=_process_submission,
    )

st.divider()
st.caption(
    "The form automatically records the survey ID and date, assigns a workshop staff member, "
    "and fills the demo flight and airport fields. You do not need to enter these details."
)
