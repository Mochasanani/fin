"""POST /api/chat — LLM chat with auto-execution of trades and watchlist changes."""

import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from litellm import acompletion

from app.database import get_db
from app.market.cache import price_cache
from app.market.provider import get_provider
from app.portfolio import TradeValidationError, perform_trade

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


class TradeAction(BaseModel):
    ticker: str
    side: str  # "buy" | "sell"
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: str  # "add" | "remove"


class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] | None = None
    watchlist_changes: list[WatchlistChange] | None = None


# ---------------------------------------------------------------------------
# Structured output schema (JSON Schema for OpenRouter structured outputs)
# ---------------------------------------------------------------------------

RESPONSE_JSON_SCHEMA = {
    "name": "FinAllyResponse",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message": {"type": "string"},
            "trades": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ticker": {"type": "string"},
                        "side": {"type": "string", "enum": ["buy", "sell"]},
                        "quantity": {"type": "number"},
                    },
                    "required": ["ticker", "side", "quantity"],
                },
            },
            "watchlist_changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ticker": {"type": "string"},
                        "action": {"type": "string", "enum": ["add", "remove"]},
                    },
                    "required": ["ticker", "action"],
                },
            },
        },
        "required": ["message"],
    },
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant inside a simulated trading workstation.

Your capabilities:
- Analyze the user's portfolio composition, risk concentration, and P&L
- Suggest trades with clear reasoning
- Execute trades when the user asks or agrees (by including them in your response)
- Manage the watchlist (add/remove tickers)
- Be concise and data-driven

You MUST respond with valid JSON matching this schema:
{
  "message": "Your conversational response to the user",
  "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
  "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]
}

Rules:
- "message" is always required.
- "trades" is optional — include only when executing trades.
- "watchlist_changes" is optional — include only when modifying the watchlist.
- side must be "buy" or "sell". action must be "add" or "remove".
- Only execute trades when the user explicitly asks or agrees.
- Keep responses concise."""


# ---------------------------------------------------------------------------
# Portfolio context
# ---------------------------------------------------------------------------


async def _load_portfolio_context(db) -> str:
    """Build a text summary of the user's portfolio (cash, positions+P&L,
    watchlist+prices, total) for the LLM."""
    cur = await db.execute(
        "SELECT cash_balance FROM users_profile WHERE id = 'default'"
    )
    row = await cur.fetchone()
    cash = row["cash_balance"] if row else 10000.0

    cur = await db.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = 'default'"
    )
    positions = await cur.fetchall()

    cur = await db.execute(
        "SELECT ticker FROM watchlist WHERE user_id = 'default'"
    )
    watchlist = [r["ticker"] for r in await cur.fetchall()]

    lines = [f"Cash: ${cash:,.2f}"]

    positions_value = 0.0
    if positions:
        lines.append("Positions:")
        for p in positions:
            entry = price_cache.get(p["ticker"])
            current = entry.price if entry else p["avg_cost"]
            pnl = (current - p["avg_cost"]) * p["quantity"]
            pnl_pct = ((current - p["avg_cost"]) / p["avg_cost"] * 100) if p["avg_cost"] else 0
            positions_value += current * p["quantity"]
            lines.append(
                f"  {p['ticker']}: {p['quantity']} @ avg ${p['avg_cost']:.2f}"
                f" (now ${current:.2f}, P&L ${pnl:+,.2f} {pnl_pct:+.2f}%)"
            )
    else:
        lines.append("Positions: none")

    if watchlist:
        prices = []
        for t in watchlist:
            entry = price_cache.get(t)
            prices.append(f"{t} ${entry.price:.2f}" if entry else t)
        lines.append("Watchlist: " + ", ".join(prices))
    else:
        lines.append("Watchlist: empty")

    lines.append(f"Total portfolio value: ${cash + positions_value:,.2f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------


async def _load_history(db, limit: int = 20) -> list[dict]:
    """Load recent chat messages for context (oldest first)."""
    cur = await db.execute(
        "SELECT role, content FROM chat_messages "
        "WHERE user_id = 'default' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------


_MOCK_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def _mock_pick_ticker(text: str) -> str:
    for t in _MOCK_TICKERS:
        if t.lower() in text:
            return t
    return "AAPL"


def _mock_response(message: str) -> ChatResponse:
    """Return deterministic mock responses for testing."""
    lower = message.lower()

    if any(w in lower for w in ["hi", "hello", "hey"]):
        return ChatResponse(
            message="Hello! I'm FinAlly, your AI trading assistant. "
            "I can analyze your portfolio, suggest trades, and manage your watchlist. "
            "How can I help you today?"
        )

    if "portfolio" in lower or "positions" in lower or "holdings" in lower:
        return ChatResponse(
            message="Your portfolio currently has $10,000.00 in cash with no open positions. "
            "You're watching AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. "
            "Would you like to make a trade?"
        )

    if "buy" in lower:
        ticker = _mock_pick_ticker(lower)
        return ChatResponse(
            message=f"Buying 10 shares of {ticker} for you.",
            trades=[TradeAction(ticker=ticker, side="buy", quantity=10)],
        )

    if "sell" in lower:
        ticker = _mock_pick_ticker(lower)
        return ChatResponse(
            message=f"Selling 10 shares of {ticker} for you.",
            trades=[TradeAction(ticker=ticker, side="sell", quantity=10)],
        )

    if "watch" in lower or "add" in lower:
        return ChatResponse(
            message="Adding PYPL to your watchlist.",
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )

    if "remove" in lower:
        return ChatResponse(
            message="Removing NFLX from your watchlist.",
            watchlist_changes=[WatchlistChange(ticker="NFLX", action="remove")],
        )

    return ChatResponse(
        message="I can help you trade, analyze your portfolio, or manage your watchlist. "
        "What would you like to do?"
    )


# ---------------------------------------------------------------------------
# Watchlist changes
# ---------------------------------------------------------------------------


async def _execute_watchlist_change(db, ticker: str, action: str) -> str | None:
    """Add/remove a ticker from watchlist. Returns error string on failure."""
    now = datetime.now(timezone.utc).isoformat()
    ticker = ticker.upper().strip()

    if action == "add":
        cur = await db.execute(
            "SELECT id FROM watchlist WHERE user_id = 'default' AND ticker = ?",
            (ticker,),
        )
        if await cur.fetchone():
            return f"{ticker} is already on the watchlist"
        await db.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, ?)",
            (str(uuid.uuid4()), ticker, now),
        )
        provider = get_provider()
        if provider is not None:
            await provider.add_ticker(ticker)
        return None

    if action == "remove":
        cur = await db.execute(
            "DELETE FROM watchlist WHERE user_id = 'default' AND ticker = ?",
            (ticker,),
        )
        if cur.rowcount == 0:
            return f"{ticker} is not on the watchlist"
        provider = get_provider()
        if provider is not None:
            await provider.remove_ticker(ticker)
        return None

    return f"Invalid watchlist action: {action}"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_llm(messages: list[dict]) -> ChatResponse:
    """Call LiteLLM via OpenRouter with Cerebras provider routing and parse
    the structured JSON response. Raises HTTPException(502) on
    parse/validation failure."""
    response = await acompletion(
        model="openrouter/openai/gpt-oss-120b",
        messages=messages,
        response_format={"type": "json_schema", "json_schema": RESPONSE_JSON_SCHEMA},
        extra_body={"provider": {"order": ["cerebras"], "allow_fallbacks": False}},
    )
    content = response.choices[0].message.content
    try:
        parsed = json.loads(content)
        return ChatResponse(**parsed)
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"Malformed LLM response: {e}",
        )


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message and receive a structured response with auto-executed actions."""
    db = await get_db()
    try:
        if os.environ.get("LLM_MOCK", "").lower() == "true":
            result = _mock_response(req.message)
        else:
            portfolio_ctx = await _load_portfolio_context(db)
            history = await _load_history(db)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": f"Current portfolio state:\n{portfolio_ctx}"},
                *history,
                {"role": "user", "content": req.message},
            ]
            result = await _call_llm(messages)

        errors: list[str] = []

        if result.trades:
            for trade in result.trades:
                try:
                    await perform_trade(db, trade.ticker, trade.quantity, trade.side)
                except TradeValidationError as e:
                    errors.append(str(e))

        if result.watchlist_changes:
            for change in result.watchlist_changes:
                err = await _execute_watchlist_change(db, change.ticker, change.action)
                if err:
                    errors.append(err)

        if errors:
            result.message += "\n\n(Errors: " + "; ".join(errors) + ")"

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, 'default', 'user', ?, NULL, ?)",
            (str(uuid.uuid4()), req.message, now),
        )

        actions_json = None
        if result.trades or result.watchlist_changes:
            actions_json = json.dumps(
                result.model_dump(exclude={"message"}, exclude_none=True)
            )

        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, 'default', 'assistant', ?, ?, ?)",
            (str(uuid.uuid4()), result.message, actions_json, now),
        )
        await db.commit()

        return result
    finally:
        await db.close()
