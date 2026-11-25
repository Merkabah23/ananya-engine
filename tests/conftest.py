import pytest


@pytest.fixture(autouse=True)
def _no_real_call_budget(monkeypatch):
    """The monthly call cap reads the repo's real ledger; a busy month must not fail unrelated tests (25 Nov 2026)."""
    from engine import llm
    monkeypatch.setattr(llm, "month_calls", lambda *a, **k: 0)
