"""Tests for the market data provider selector and interface conformance."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.market.cache import PriceCache
from app.market.interface import MarketDataProvider
from app.market.massive import MassiveClient
from app.market.provider import create_provider
from app.market.simulator import Simulator


def test_simulator_implements_interface():
    sim = Simulator()
    assert isinstance(sim, MarketDataProvider)


def test_massive_implements_interface(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    client = MassiveClient(tickers=["AAPL"])
    assert isinstance(client, MarketDataProvider)


def test_provider_selector_no_key_returns_simulator(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    provider = create_provider()
    assert isinstance(provider, Simulator)


def test_provider_selector_empty_key_returns_simulator(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    provider = create_provider()
    assert isinstance(provider, Simulator)


def test_provider_selector_whitespace_key_returns_simulator(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    provider = create_provider()
    assert isinstance(provider, Simulator)


def test_provider_selector_with_key_returns_massive(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "real-key")
    provider = create_provider()
    assert isinstance(provider, MassiveClient)


@pytest.mark.asyncio
async def test_massive_parses_snapshot_response(monkeypatch):
    """MassiveClient parses Polygon snapshot response and writes to cache."""
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")

    fake_response_data = {
        "tickers": [
            {"ticker": "AAPL", "lastTrade": {"p": 192.50}},
            {"ticker": "GOOGL", "lastTrade": {"p": 178.25}},
            {"ticker": "MSFT", "lastTrade": {}},  # missing price — should be skipped
            {"lastTrade": {"p": 100.0}},  # missing ticker — should be skipped
        ]
    }

    from app.market import massive as massive_module

    fresh_cache = PriceCache()
    monkeypatch.setattr(massive_module, "price_cache", fresh_cache)

    client = MassiveClient(tickers=["AAPL", "GOOGL", "MSFT"])

    fake_resp = AsyncMock()
    fake_resp.json = lambda: fake_response_data
    fake_resp.raise_for_status = lambda: None

    fake_http = AsyncMock()
    fake_http.get = AsyncMock(return_value=fake_resp)
    client._client = fake_http

    await client._poll()

    aapl = fresh_cache.get("AAPL")
    googl = fresh_cache.get("GOOGL")
    assert aapl is not None and aapl.price == 192.50
    assert googl is not None and googl.price == 178.25
    assert fresh_cache.get("MSFT") is None


@pytest.mark.asyncio
async def test_massive_handles_http_error_gracefully(monkeypatch):
    """A network error during poll should not crash the loop."""
    import httpx

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    client = MassiveClient(tickers=["AAPL"])

    fake_http = AsyncMock()
    fake_http.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    client._client = fake_http

    # Should not raise
    await client._poll()
