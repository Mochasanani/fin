"""Tests for the POST /api/chat endpoint in mock mode."""

import os

os.environ["LLM_MOCK"] = "true"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.market.cache import price_cache


@pytest.fixture(autouse=True)
def seed_prices():
    """Seed price cache so chat-driven trades have a current price."""
    for ticker, price in [
        ("AAPL", 150.0),
        ("GOOGL", 175.0),
        ("MSFT", 400.0),
        ("AMZN", 180.0),
        ("TSLA", 250.0),
        ("NVDA", 900.0),
        ("META", 500.0),
        ("JPM", 200.0),
        ("V", 280.0),
        ("NFLX", 600.0),
        ("PYPL", 70.0),
    ]:
        price_cache.update(ticker, price)
    yield
    price_cache._prices.clear()


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async test client with a fresh per-test SQLite DB."""
    import app.database as database

    db_file = str(tmp_path / "test.db")
    database.DB_PATH = db_file
    await database.init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_chat_greeting(client):
    resp = await client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert "FinAlly" in data["message"]
    assert data["trades"] is None
    assert data["watchlist_changes"] is None


async def test_chat_buy_aapl(client):
    """Mock buy always buys 10 shares of the matched ticker at $150."""
    resp = await client.post("/api/chat", json={"message": "buy some AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] is not None
    assert len(data["trades"]) == 1
    trade = data["trades"][0]
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10
    # No errors appended
    assert "Errors" not in data["message"]


async def test_chat_sell_insufficient(client):
    """Selling without owning shares should report error in message."""
    resp = await client.post("/api/chat", json={"message": "sell some AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    # Upstream appends errors to message
    assert "Insufficient" in data["message"] or "Errors" in data["message"]


async def test_chat_buy_then_sell(client):
    """Buy then sell should succeed."""
    # Buy first (10 shares at $150 = $1500)
    resp = await client.post("/api/chat", json={"message": "buy some TSLA"})
    data = resp.json()
    assert data["trades"][0]["ticker"] == "TSLA"
    assert "Errors" not in data["message"]

    # Sell (10 shares at avg cost)
    resp = await client.post("/api/chat", json={"message": "sell some TSLA"})
    data = resp.json()
    assert "Insufficient" not in data["message"]


async def test_chat_buy_insufficient_cash(client):
    """Buying more than cash allows should fail. 10 * $150 = $1500, so
    need to exhaust cash first."""
    # Buy 7 times: 7 * 10 * $150 = $10,500 > $10,000
    # First 6 buys: 6 * $1500 = $9000 (leaving $1000)
    for _ in range(6):
        await client.post("/api/chat", json={"message": "buy some AAPL"})

    # 7th buy: $1500 > $1000 remaining
    resp = await client.post("/api/chat", json={"message": "buy some AAPL"})
    data = resp.json()
    assert "Insufficient" in data["message"]


async def test_chat_watchlist_add(client):
    resp = await client.post("/api/chat", json={"message": "add PYPL to watchlist"})
    data = resp.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "PYPL"
    assert data["watchlist_changes"][0]["action"] == "add"


async def test_chat_watchlist_remove(client):
    resp = await client.post("/api/chat", json={"message": "remove NFLX"})
    data = resp.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "NFLX"
    assert data["watchlist_changes"][0]["action"] == "remove"


async def test_chat_portfolio_query(client):
    resp = await client.post("/api/chat", json={"message": "show my portfolio"})
    data = resp.json()
    assert "portfolio" in data["message"].lower()
    assert data["trades"] is None


async def test_chat_fallback(client):
    resp = await client.post("/api/chat", json={"message": "random nonsense xyz"})
    data = resp.json()
    assert "trade" in data["message"].lower() or "portfolio" in data["message"].lower()


# ---------------------------------------------------------------------------
# Auto-execution reflects in /api/portfolio and /api/watchlist (acceptance
# criterion: trades and watchlist changes auto-execute and reflect downstream).
# ---------------------------------------------------------------------------


async def test_chat_buy_reflects_in_portfolio(client):
    await client.post("/api/chat", json={"message": "buy some AAPL"})
    resp = await client.get("/api/portfolio")
    data = resp.json()
    tickers = {p["ticker"] for p in data["positions"]}
    assert "AAPL" in tickers
    assert data["cash_balance"] == 10000.0 - (10 * 150.0)


async def test_chat_watchlist_add_reflects_in_watchlist(client):
    await client.post("/api/chat", json={"message": "add PYPL to watchlist"})
    resp = await client.get("/api/watchlist")
    tickers = [item["ticker"] for item in resp.json()]
    assert "PYPL" in tickers


async def test_chat_watchlist_remove_reflects_in_watchlist(client):
    await client.post("/api/chat", json={"message": "remove NFLX"})
    resp = await client.get("/api/watchlist")
    tickers = [item["ticker"] for item in resp.json()]
    assert "NFLX" not in tickers


async def test_chat_persists_messages_with_actions(client):
    """User and assistant messages persist to chat_messages with actions JSON."""
    import json
    import app.database as database

    await client.post("/api/chat", json={"message": "buy some MSFT"})

    db = await database.get_db()
    try:
        cur = await db.execute(
            "SELECT role, content, actions FROM chat_messages "
            "WHERE user_id = 'default' ORDER BY created_at, role"
        )
        rows = await cur.fetchall()
    finally:
        await db.close()

    roles = [r["role"] for r in rows]
    assert "user" in roles and "assistant" in roles

    assistant_row = next(r for r in rows if r["role"] == "assistant")
    user_row = next(r for r in rows if r["role"] == "user")
    assert user_row["actions"] is None
    actions = json.loads(assistant_row["actions"])
    assert actions["trades"][0]["ticker"] == "MSFT"


# ---------------------------------------------------------------------------
# Direct LLM call: schema parsing, malformed handling, validation failures.
# These tests exercise the non-mock path by stubbing litellm.acompletion.
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


@pytest_asyncio.fixture
async def llm_real_client(client, monkeypatch):
    """Client with LLM_MOCK disabled so _call_llm is exercised."""
    monkeypatch.setenv("LLM_MOCK", "false")
    yield client


async def test_chat_parses_valid_structured_response(llm_real_client, monkeypatch):
    """Schema parsing: valid JSON from the LLM is parsed into ChatResponse and
    actions auto-execute."""
    import json
    import app.chat as chat_mod

    payload = json.dumps(
        {
            "message": "Buying TSLA",
            "trades": [{"ticker": "TSLA", "side": "buy", "quantity": 5}],
            "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
        }
    )

    async def fake_acompletion(**kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    resp = await llm_real_client.post("/api/chat", json={"message": "buy 5 TSLA"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"].startswith("Buying TSLA")
    assert data["trades"][0]["ticker"] == "TSLA"
    assert data["watchlist_changes"][0]["ticker"] == "PYPL"

    # Reflects downstream
    pf = (await llm_real_client.get("/api/portfolio")).json()
    assert any(p["ticker"] == "TSLA" for p in pf["positions"])


async def test_chat_malformed_json_returns_502(llm_real_client, monkeypatch):
    """Malformed handling: non-JSON content surfaces as 502."""
    import app.chat as chat_mod

    async def fake_acompletion(**kwargs):
        return _FakeResponse("not json at all {{{")

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    resp = await llm_real_client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 502
    assert "Malformed" in resp.json()["detail"]


async def test_chat_schema_violation_returns_502(llm_real_client, monkeypatch):
    """Malformed handling: JSON missing required `message` field surfaces as 502."""
    import json
    import app.chat as chat_mod

    async def fake_acompletion(**kwargs):
        return _FakeResponse(json.dumps({"trades": []}))  # no "message"

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    resp = await llm_real_client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 502


async def test_chat_invalid_trade_validation_failure(llm_real_client, monkeypatch):
    """Validation failure: LLM-requested sell of unheld shares records the
    error in the user-facing message but the response still parses."""
    import json
    import app.chat as chat_mod

    payload = json.dumps(
        {
            "message": "Selling AAPL",
            "trades": [{"ticker": "AAPL", "side": "sell", "quantity": 100}],
        }
    )

    async def fake_acompletion(**kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    resp = await llm_real_client.post("/api/chat", json={"message": "sell 100 AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Insufficient shares" in data["message"]


async def test_chat_invokes_cerebras_provider(llm_real_client, monkeypatch):
    """The non-mock path routes through OpenRouter with Cerebras provider and
    requests a JSON schema response_format."""
    import json
    import app.chat as chat_mod

    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(json.dumps({"message": "ok"}))

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    resp = await llm_real_client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert captured["model"] == "openrouter/openai/gpt-oss-120b"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["extra_body"]["provider"]["order"] == ["cerebras"]


async def test_chat_loads_portfolio_context(llm_real_client, monkeypatch):
    """Portfolio context (cash, positions, watchlist+prices, total) is built
    into the LLM prompt."""
    import json
    import app.chat as chat_mod

    # Open a position so we get a P&L line in context.
    await llm_real_client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 5, "side": "buy"},
    )

    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(json.dumps({"message": "ok"}))

    monkeypatch.setattr(chat_mod, "acompletion", fake_acompletion)

    await llm_real_client.post("/api/chat", json={"message": "what's my portfolio?"})

    system_msgs = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    ctx = next(m for m in system_msgs if "Cash:" in m)
    assert "AAPL" in ctx
    assert "Watchlist:" in ctx
    assert "Total portfolio value" in ctx
