"""Tests for the SSE price stream endpoint."""

import json

import pytest

from app.market import stream as stream_module
from app.market.cache import PriceCache


@pytest.mark.asyncio
async def test_stream_emits_price_events_from_cache(monkeypatch):
    """The SSE generator yields one event per ticker in the cache."""
    fresh = PriceCache()
    fresh.update("AAPL", 192.50)
    fresh.update("GOOGL", 178.25)
    monkeypatch.setattr(stream_module, "price_cache", fresh)

    gen = stream_module._price_event_generator()
    events = []
    for _ in range(2):
        events.append(await gen.__anext__())

    tickers = {json.loads(e["data"])["ticker"] for e in events}
    assert tickers == {"AAPL", "GOOGL"}
    for e in events:
        assert e["event"] == "price"
        payload = json.loads(e["data"])
        assert "price" in payload
        assert "previous_price" in payload
        assert "timestamp" in payload
        assert "direction" in payload


@pytest.mark.asyncio
async def test_stream_event_payload_has_direction(monkeypatch):
    """Direction reflects price movement (up/down/flat)."""
    fresh = PriceCache()
    fresh.update("AAPL", 100.0)  # first update -> flat
    fresh.update("AAPL", 105.0)  # up
    monkeypatch.setattr(stream_module, "price_cache", fresh)

    gen = stream_module._price_event_generator()
    event = await gen.__anext__()
    payload = json.loads(event["data"])
    assert payload["direction"] == "up"
    assert payload["price"] == 105.0
    assert payload["previous_price"] == 100.0
