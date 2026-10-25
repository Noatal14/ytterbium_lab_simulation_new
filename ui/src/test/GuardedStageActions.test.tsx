import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GuardedStageActions } from "../features/campaign/shared/GuardedStageActions";

const labels = { refreshLabel: "Refresh status", reviewLabel: "Review exact plan", confirmLabel: "Confirm stage", resetLabel: "Back" };
const callbacks = () => ({ onRefresh: vi.fn(), onReview: vi.fn(), onConfirm: vi.fn(), onReset: vi.fn() });

describe("GuardedStageActions", () => {
  it("renders descriptor-driven ready actions", async () => { const actions = callbacks(); render(<GuardedStageActions phase="ready" labels={labels} {...actions} />); await userEvent.click(screen.getByRole("button", { name: labels.reviewLabel })); expect(actions.onReview).toHaveBeenCalledOnce(); });
  it("renders explicit review confirmation and back actions", () => { render(<GuardedStageActions phase="review" labels={labels} {...callbacks()} />); expect(screen.getByRole("button", { name: labels.confirmLabel })).toBeEnabled(); expect(screen.getByRole("button", { name: labels.resetLabel })).toBeEnabled(); });
  it("disables actions while an operation is in flight", () => { render(<GuardedStageActions phase="confirming" labels={labels} {...callbacks()} />); expect(screen.getByRole("button", { name: "Confirming…" })).toBeDisabled(); });
  it.each(["blocked", "success"] as const)("offers no unsafe action in %s", (phase) => { const { container } = render(<GuardedStageActions phase={phase} labels={labels} {...callbacks()} />); expect(container).toBeEmptyDOMElement(); });
});


it.each(["idle", "ready", "review", "blocked"] as const)("refreshOnly offers only read-only refresh in %s without changing the real phase", async phase => {
  const actions = callbacks();
  render(<GuardedStageActions phase={phase} refreshOnly labels={labels} {...actions} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: labels.refreshLabel }));
  expect(actions.onRefresh).toHaveBeenCalledOnce();
  expect(actions.onReview).not.toHaveBeenCalled();
  expect(actions.onConfirm).not.toHaveBeenCalled();
  expect(actions.onReset).not.toHaveBeenCalled();
});
