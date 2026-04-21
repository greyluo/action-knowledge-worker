import pytest


def test_mock_company_data_has_overlap():
    from mock_tools import COMPANY_DATA, EMAIL_THREADS
    # Alice Chen appears in both Acme Corp and an email thread by email
    acme_emails = {e["email"] for e in COMPANY_DATA["Acme Corp"]["employees"]}
    thread_emails = {
        p["email"]
        for t in EMAIL_THREADS.values()
        for p in t.get("participants", [])
    }
    assert acme_emails & thread_emails, "No email overlap between company data and threads"


def test_fetch_company_data_returns_json():
    from mock_tools import COMPANY_DATA
    acme = COMPANY_DATA.get("Acme Corp")
    assert acme is not None
    assert "employees" in acme
    assert len(acme["employees"]) >= 2


def test_fetch_email_thread_has_participants():
    from mock_tools import EMAIL_THREADS
    for tid, thread in EMAIL_THREADS.items():
        assert "participants" in thread, f"Thread {tid} missing participants"
        assert "messages" in thread, f"Thread {tid} missing messages"
