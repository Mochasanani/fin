"""Environment-driven market data provider selection."""

import os

from app.market.interface import MarketDataProvider

_active_provider: MarketDataProvider | None = None


def create_provider() -> MarketDataProvider:
    """Create the appropriate provider based on environment and register it."""
    global _active_provider
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        from app.market.massive import MassiveClient
        from app.database import DEFAULT_TICKERS

        _active_provider = MassiveClient(tickers=DEFAULT_TICKERS)
    else:
        from app.market.simulator import Simulator

        _active_provider = Simulator()
    return _active_provider


def get_provider() -> MarketDataProvider | None:
    """Return the currently active provider, if any."""
    return _active_provider


def set_provider(provider: MarketDataProvider | None) -> None:
    """Override the active provider (used by tests)."""
    global _active_provider
    _active_provider = provider
