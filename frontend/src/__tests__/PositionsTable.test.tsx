import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import PositionsTable from "@/components/PositionsTable";
import type { Position } from "@/lib/api";
import type { PriceMap } from "@/hooks/useMarketData";

describe("PositionsTable", () => {
  it("shows empty state when no positions", () => {
    render(<PositionsTable positions={[]} prices={{}} />);
    expect(screen.getByText("No positions")).toBeInTheDocument();
  });

  it("renders ticker, qty, avg cost, current price, P&L, and percent for each position", () => {
    const positions: Position[] = [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 100.0,
        current_price: 110.0,
        unrealized_pnl: 100.0,
        pnl_percent: 10.0,
      },
    ];
    const prices: PriceMap = {};

    render(<PositionsTable positions={positions} prices={prices} />);

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("$100.00")).toBeInTheDocument();
    expect(screen.getByText("$110.00")).toBeInTheDocument();
    expect(screen.getByText("+$100.00")).toBeInTheDocument();
    expect(screen.getByText("+10.0%")).toBeInTheDocument();
  });

  it("uses live SSE price over stored current_price when available", () => {
    const positions: Position[] = [
      {
        ticker: "AAPL",
        quantity: 5,
        avg_cost: 100.0,
        current_price: 100.0,
        unrealized_pnl: 0,
        pnl_percent: 0,
      },
    ];
    const prices: PriceMap = {
      AAPL: { price: 120.0, prevPrice: 100.0, time: "2026-01-01T00:00:00Z" },
    };

    render(<PositionsTable positions={positions} prices={prices} />);

    // P&L computed from live price 120: (120-100)*5 = $100
    expect(screen.getByText("$120.00")).toBeInTheDocument();
    expect(screen.getByText("+$100.00")).toBeInTheDocument();
    expect(screen.getByText("+20.0%")).toBeInTheDocument();
  });

  it("renders losses with red color and negative sign", () => {
    const positions: Position[] = [
      {
        ticker: "TSLA",
        quantity: 4,
        avg_cost: 200.0,
        current_price: 180.0,
        unrealized_pnl: -80.0,
        pnl_percent: -10.0,
      },
    ];

    render(<PositionsTable positions={positions} prices={{}} />);

    const pnlCell = screen.getByText("$-80.00");
    expect(pnlCell).toBeInTheDocument();
    expect(pnlCell.className).toContain("text-red");
    expect(screen.getByText("-10.0%")).toBeInTheDocument();
  });

  it("renders multiple positions as separate rows", () => {
    const positions: Position[] = [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 100.0,
        current_price: 110.0,
        unrealized_pnl: 100.0,
        pnl_percent: 10.0,
      },
      {
        ticker: "GOOGL",
        quantity: 2,
        avg_cost: 150.0,
        current_price: 175.0,
        unrealized_pnl: 50.0,
        pnl_percent: 16.7,
      },
    ];

    render(<PositionsTable positions={positions} prices={{}} />);

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    // Header row + two data rows
    expect(rows.length).toBe(3);
  });
});
