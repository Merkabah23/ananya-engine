import pytest

from engine import config


@pytest.fixture(autouse=True)
def _not_paused(monkeypatch):
    """The workflow pauses the live engine with ENGINE_PAUSED; tests exercise the unpaused engine unless they set it."""
    monkeypatch.setattr(config, "PAUSED", False)
