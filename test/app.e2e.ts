import { test, expect, Page } from "@playwright/test";

const DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

// Reset DB between tests so each scenario sees the fresh-start state.
test.beforeEach(async ({ request }) => {
  const res = await request.post("/api/test/reset");
  expect(res.ok()).toBeTruthy();
});

async function waitForLiveApp(page: Page) {
  await page.goto("/");
  await expect(page.getByText("connected")).toBeVisible({ timeout: 15_000 });
  // Wait for at least one streamed price (cell shows a number, not "--")
  await expect(page.locator("td.tabular-nums").first()).not.toHaveText("--", {
    timeout: 15_000,
  });
}

test.describe("Fresh start", () => {
  test("default watchlist, $10k cash, prices streaming", async ({ page }) => {
    await waitForLiveApp(page);

    // Header shows starting cash of $10,000.00
    await expect(page.getByText(/\$10,000\.00/).first()).toBeVisible({ timeout: 10_000 });

    // App title renders
    await expect(page.getByRole("heading", { level: 1 })).toContainText("FinAlly");

    // All 10 default tickers visible in watchlist
    for (const t of DEFAULT_TICKERS) {
      await expect(page.locator("tr", { hasText: new RegExp(`^${t}`) }).first()).toBeVisible();
    }
  });
});

test.describe("Watchlist CRUD", () => {
  test("add and remove a ticker", async ({ page }) => {
    await waitForLiveApp(page);

    const input = page.getByPlaceholder("Add ticker");
    await input.fill("SNAP");
    await input.press("Enter");
    const snapRow = page.locator("tr", { hasText: "SNAP" });
    await expect(snapRow).toBeVisible({ timeout: 5_000 });

    await snapRow.getByTitle("Remove").click();
    await expect(page.locator("tr", { hasText: "SNAP" })).toHaveCount(0, { timeout: 5_000 });
  });
});

test.describe("Trading", () => {
  test("buy decreases cash and creates a position; sell clears it", async ({ page }) => {
    await waitForLiveApp(page);

    // Cash value sits in the second header item; capture before trade
    const cashValue = page.locator("header span.font-bold").nth(1);
    await expect(cashValue).toHaveText(/\$10,000\.00/, { timeout: 10_000 });

    // Both the heatmap and positions panel show "No positions" before any trade
    await expect(page.getByText("No positions")).toHaveCount(2);

    // Buy 1 AAPL via the trade bar
    await page.getByPlaceholder("Ticker", { exact: true }).fill("AAPL");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "BUY" }).click();

    // Status text confirms execution
    await expect(page.getByText(/^BUY 1 AAPL @ \$/)).toBeVisible({ timeout: 5_000 });

    // Cash decreased below $10,000 — the most reliable signal a trade landed
    await expect(cashValue).not.toHaveText(/\$10,000\.00/, { timeout: 10_000 });

    // Both panels have a populated position now — "No positions" gone
    await expect(page.getByText("No positions")).toHaveCount(0, { timeout: 10_000 });

    // Sell 1 AAPL — position cleared
    await page.getByPlaceholder("Ticker", { exact: true }).fill("AAPL");
    await page.getByPlaceholder("Qty").fill("1");
    await page.getByRole("button", { name: "SELL" }).click();
    await expect(page.getByText(/^SELL 1 AAPL @ \$/)).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Portfolio visualization", () => {
  test("heatmap and P&L panels render", async ({ page }) => {
    await waitForLiveApp(page);
    await expect(page.getByText("Portfolio Heatmap")).toBeVisible();
    await expect(page.getByText("P&L", { exact: true })).toBeVisible();
  });
});

test.describe("AI Chat", () => {
  test("send message and receive mocked response", async ({ page }) => {
    await waitForLiveApp(page);

    await expect(page.getByText("AI Chat")).toBeVisible();
    await expect(
      page.getByText("Ask about stocks, trade, or manage your watchlist.")
    ).toBeVisible();

    const chatInput = page.getByPlaceholder("Message...");
    await chatInput.fill("hello");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText("hello").first()).toBeVisible();
    await expect(page.getByText(/Hello! I'm FinAlly/)).toBeVisible({ timeout: 15_000 });
  });

  test("chat trade auto-executes and confirms inline", async ({ page }) => {
    await waitForLiveApp(page);

    const chatInput = page.getByPlaceholder("Message...");
    await chatInput.fill("buy NVDA");
    await page.getByRole("button", { name: "Send" }).click();

    // Mock returns "Buying 10 shares of NVDA for you." with a trade action badge
    await expect(page.getByText(/Buying 10 shares of NVDA/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Bought 10 NVDA")).toBeVisible({ timeout: 5_000 });
  });

  test("chat panel collapses and expands", async ({ page }) => {
    await waitForLiveApp(page);

    await page.getByLabel("Collapse chat").click();
    await expect(page.getByText("AI Chat")).not.toBeVisible();

    await page.getByLabel("Expand chat").click();
    await expect(page.getByText("AI Chat")).toBeVisible();
  });
});

test.describe("SSE resilience", () => {
  test("reconnects after disconnect", async ({ page }) => {
    await waitForLiveApp(page);

    // Block the SSE endpoint and reload so the EventSource has to reconnect.
    // The blocked request triggers onerror → "reconnecting".
    await page.route("**/api/stream/prices", (route) => route.abort());
    await page.reload();
    await expect(page.getByText("reconnecting")).toBeVisible({ timeout: 15_000 });

    // Restore the route — EventSource auto-retries and reconnects.
    await page.unroute("**/api/stream/prices");
    await expect(page.getByText("connected")).toBeVisible({ timeout: 20_000 });
  });
});
