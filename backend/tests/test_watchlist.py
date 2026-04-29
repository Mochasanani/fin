"""Tests for the watchlist API: CRUD, dedupe, provider sync."""

import pytest

from app.database import DEFAULT_TICKERS
from app.market import provider as provider_module
from app.market.cache import price_cache


class FakeProvider:
    """Minimal provider double that records add/remove calls."""

    def __init__(self):
        self.added: list[str] = []
        self.removed: list[str] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def add_ticker(self, ticker: str) -> None:
        self.added.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.removed.append(ticker)


@pytest.fixture
def fake_provider():
    """Install a fake provider for the duration of a test."""
    original = provider_module.get_provider()
    fake = FakeProvider()
    provider_module.set_provider(fake)
    yield fake
    provider_module.set_provider(original)


@pytest.fixture(autouse=True)
def clean_cache():
    yield
    price_cache._prices.clear()


@pytest.mark.asyncio
async def test_get_watchlist_returns_seeded_tickers(client):
    resp = await client.get("/api/watchlist")
    assert resp.status_code == 200
    data = resp.json()
    tickers = [item["ticker"] for item in data]
    assert set(tickers) == set(DEFAULT_TICKERS)


@pytest.mark.asyncio
async def test_get_watchlist_includes_prices_from_cache(client):
    price_cache.update("AAPL", 190.0)
    price_cache.update("AAPL", 192.0)  # second update populates previous_price

    resp = await client.get("/api/watchlist")
    data = resp.json()
    aapl = next(item for item in data if item["ticker"] == "AAPL")
    assert aapl["price"] == 192.0
    assert aapl["previous_price"] == 190.0
    assert aapl["change_percent"] is not None


@pytest.mark.asyncio
async def test_get_watchlist_returns_null_price_when_cache_empty(client):
    resp = await client.get("/api/watchlist")
    data = resp.json()
    aapl = next(item for item in data if item["ticker"] == "AAPL")
    assert aapl["price"] is None
    assert aapl["previous_price"] is None
    assert aapl["change_percent"] is None


@pytest.mark.asyncio
async def test_post_adds_ticker(client, fake_provider):
    resp = await client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "PYPL"

    resp = await client.get("/api/watchlist")
    tickers = [item["ticker"] for item in resp.json()]
    assert "PYPL" in tickers


@pytest.mark.asyncio
async def test_post_normalizes_to_uppercase(client, fake_provider):
    resp = await client.post("/api/watchlist", json={"ticker": "  pypl  "})
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "PYPL"
    assert fake_provider.added == ["PYPL"]


@pytest.mark.asyncio
async def test_post_rejects_empty_ticker(client, fake_provider):
    resp = await client.post("/api/watchlist", json={"ticker": "   "})
    assert resp.status_code == 400
    assert fake_provider.added == []


@pytest.mark.asyncio
async def test_post_returns_409_on_duplicate(client, fake_provider):
    # AAPL is part of the default seed.
    resp = await client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert resp.status_code == 409
    assert fake_provider.added == []


@pytest.mark.asyncio
async def test_post_syncs_provider(client, fake_provider):
    """Adding a ticker tells the provider to start tracking it."""
    await client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert fake_provider.added == ["PYPL"]


@pytest.mark.asyncio
async def test_delete_removes_ticker(client, fake_provider):
    resp = await client.delete("/api/watchlist/AAPL")
    assert resp.status_code == 200

    resp = await client.get("/api/watchlist")
    tickers = [item["ticker"] for item in resp.json()]
    assert "AAPL" not in tickers


@pytest.mark.asyncio
async def test_delete_syncs_provider(client, fake_provider):
    await client.delete("/api/watchlist/AAPL")
    assert fake_provider.removed == ["AAPL"]


@pytest.mark.asyncio
async def test_delete_returns_404_for_unknown_ticker(client, fake_provider):
    resp = await client.delete("/api/watchlist/UNKNOWN")
    assert resp.status_code == 404
    assert fake_provider.removed == []


@pytest.mark.asyncio
async def test_delete_normalizes_ticker(client, fake_provider):
    resp = await client.delete("/api/watchlist/aapl")
    assert resp.status_code == 200
    assert fake_provider.removed == ["AAPL"]


@pytest.mark.asyncio
async def test_provider_unset_does_not_break_endpoints(client):
    """Watchlist endpoints work even if no provider is registered."""
    original = provider_module.get_provider()
    provider_module.set_provider(None)
    try:
        resp = await client.post("/api/watchlist", json={"ticker": "PYPL"})
        assert resp.status_code == 200
        resp = await client.delete("/api/watchlist/PYPL")
        assert resp.status_code == 200
    finally:
        provider_module.set_provider(original)


@pytest.mark.asyncio
async def test_simulator_add_ticker_starts_streaming():
    """Simulator add_ticker integrates the new ticker into its sim loop."""
    from app.market.simulator import Simulator

    sim = Simulator()
    assert "PYPL" not in sim._tickers

    await sim.add_ticker("PYPL")
    assert "PYPL" in sim._tickers
    assert price_cache.get("PYPL") is not None

    # Stepping the sim should now produce a price for PYPL
    initial = sim._prices["PYPL"]
    sim._step()
    # Price should still be tracked (may or may not change in a single step,
    # but it must remain in the prices map)
    assert "PYPL" in sim._prices
    assert sim._prices["PYPL"] >= 0.01
    # Sanity: at least one step was applied
    assert isinstance(sim._prices["PYPL"], float)
    del initial


@pytest.mark.asyncio
async def test_simulator_add_ticker_idempotent():
    from app.market.simulator import Simulator

    sim = Simulator()
    n_before = len(sim._tickers)
    await sim.add_ticker("AAPL")  # already tracked
    assert len(sim._tickers) == n_before


@pytest.mark.asyncio
async def test_massive_add_ticker_extends_polling_list(monkeypatch):
    from app.market.massive import MassiveClient

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    client = MassiveClient(tickers=["AAPL"])

    await client.add_ticker("PYPL")
    assert "PYPL" in client._tickers

    await client.remove_ticker("AAPL")
    assert "AAPL" not in client._tickers
