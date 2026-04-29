"""Abstract market data provider interface."""

from abc import ABC, abstractmethod


class MarketDataProvider(ABC):
    """Abstract base for market data providers."""

    @abstractmethod
    async def start(self) -> None:
        """Start producing price updates."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop producing price updates."""

    async def add_ticker(self, ticker: str) -> None:
        """Ensure the provider is tracking this ticker. Default no-op."""

    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking this ticker. Default no-op."""
