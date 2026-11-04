// Rendering tests for pagination, badges, charts, metrics and formatting
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfidenceBadge, Pagination } from "@/components/ui";
import { BarList } from "@/features/charts/BarList";
import { MetricsGrid } from "@/features/evaluation/MetricsGrid";
import { formatPercent, humanize } from "@/lib/format";

describe("components", () => {
  it("paginates", () => {
    const onPage = vi.fn();
    render(<Pagination page={2} pageSize={10} total={35} onPage={onPage} />);
    expect(screen.getByText("11–20 of 35")).toBeInTheDocument();
    expect(screen.getByLabelText("current page")).toHaveTextContent("2 / 4");
    fireEvent.click(screen.getByText("Next"));
    expect(onPage).toHaveBeenCalledWith(3);
  });

  it("disables previous on the first page", () => {
    render(<Pagination page={1} pageSize={10} total={5} onPage={() => {}} />);
    expect(screen.getByText("Previous")).toBeDisabled();
    expect(screen.getByText("Next")).toBeDisabled();
  });

  it("shows confidence as a percentage", () => {
    render(<ConfidenceBadge confidence={0.876} />);
    expect(screen.getByText("88%")).toBeInTheDocument();
  });

  it("renders distributions sorted by value", () => {
    render(<BarList data={{ small: 3, large: 10 }} />);
    const labels = screen.getAllByTitle(/small|large/).map((el) => el.textContent);
    expect(labels).toEqual(["large", "small"]);
  });

  it("renders evaluation metrics", () => {
    render(
      <MetricsGrid
        metrics={{
          edge_precision: 0.9,
          edge_recall: 0.3,
          edge_f1: 0.45,
          coverage: 0.33,
          abstention_rate: 0.67,
          wrong_edge_rate: 0.1,
          penalized_score: 0.24,
          counts: { correct: 90, predicted: 100, true_edges: 300, wrong: 10, wrong_on_root: 0, departed_predicted: 1, departed_evaluated: 5, missing_predictions: 0 },
        }}
      />,
    );
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText("90 correct / 100 answered")).toBeInTheDocument();
  });

  it("formats values", () => {
    expect(formatPercent(null)).toBe("—");
    expect(humanize("senior_ic")).toBe("Senior Ic");
  });
});
