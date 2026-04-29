import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import PortfolioHeatmap from "@/components/PortfolioHeatmap";
import type { Position } from "@/lib/api";
import type { PriceMap } from "@/hooks/useMarketData";

describe("PortfolioHeatmap", () => {
  it("shows empty state when no positions", () => {
    render(<PortfolioHeatmap positions={[]} prices={{}} />);
    expect(screen.getByText("No positions")).toBeInTheDocument();
  });

  it("renders one rectangle per position with ticker and P&L %", () => {
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
        ticker: "TSLA",
        quantity: 5,
        avg_cost: 200.0,
        current_price: 180.0,
        unrealized_pnl: -100.0,
        pnl_percent: -10.0,
      },
    ];

    render(<PortfolioHeatmap positions={positions} prices={{}} />);

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("+10.0%")).toBeInTheDocument();
    expect(screen.getByText("-10.0%")).toBeInTheDocument();
  });

  it("colors profitable positions green and losing positions red", () => {
    const positions: Position[] = [
      {
        ticker: "WIN",
        quantity: 1,
        avg_cost: 100.0,
        current_price: 120.0,
        unrealized_pnl: 20.0,
        pnl_percent: 20.0,
      },
      {
        ticker: "LOSE",
        quantity: 1,
        avg_cost: 100.0,
        current_price: 80.0,
        unrealized_pnl: -20.0,
        pnl_percent: -20.0,
      },
    ];

    render(<PortfolioHeatmap positions={positions} prices={{}} />);

    const winTile = screen.getByText("WIN").parentElement;
    const loseTile = screen.getByText("LOSE").parentElement;

    expect(winTile?.style.backgroundColor).toContain("63, 185, 80"); // green rgb
    expect(loseTile?.style.backgroundColor).toContain("248, 81, 73"); // red rgb
  });

  it("sizes rectangles by portfolio weight (bigger value -> bigger flex-basis)", () => {
    const positions: Position[] = [
      {
        ticker: "BIG",
        quantity: 10,
        avg_cost: 100.0,
        current_price: 100.0,
        unrealized_pnl: 0,
        pnl_percent: 0,
      },
      {
        ticker: "SMALL",
        quantity: 1,
        avg_cost: 100.0,
        current_price: 100.0,
        unrealized_pnl: 0,
        pnl_percent: 0,
      },
    ];

    render(<PortfolioHeatmap positions={positions} prices={{}} />);

    const bigTile = screen.getByText("BIG").parentElement;
    const smallTile = screen.getByText("SMALL").parentElement;

    const bigBasis = parseFloat(bigTile?.style.flexBasis ?? "0");
    const smallBasis = parseFloat(smallTile?.style.flexBasis ?? "0");

    expect(bigBasis).toBeGreaterThan(smallBasis);
  });

  it("uses live SSE prices over stored current_price for value/P&L computation", () => {
    const positions: Position[] = [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 100.0,
        current_price: 100.0,
        unrealized_pnl: 0,
        pnl_percent: 0,
      },
    ];
    const prices: PriceMap = {
      AAPL: { price: 150.0, prevPrice: 100.0, time: "2026-01-01T00:00:00Z" },
    };

    render(<PortfolioHeatmap positions={positions} prices={prices} />);

    // (150-100)/100 = 50%
    expect(screen.getByText("+50.0%")).toBeInTheDocument();
    const tile = screen.getByText("AAPL").parentElement;
    expect(tile?.style.backgroundColor).toContain("63, 185, 80"); // green
  });
});
