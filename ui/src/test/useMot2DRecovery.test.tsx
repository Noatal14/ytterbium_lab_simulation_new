import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useMot2DRecovery } from "../features/campaign/controllers/useMot2DRecovery";

it("ignores a late status callback from the previous connection while the new one is still checking", async () => {
  let finishA!: () => void, finishB!: () => void;
  const a = vi.fn(() => new Promise<void>(resolve => { finishA = resolve; }));
  const b = vi.fn(() => new Promise<void>(resolve => { finishB = resolve; }));
  const later = vi.fn(async () => {});
  const { result, rerender } = renderHook(({ identity, refresh }) => useMot2DRecovery(identity, [
    { ready: true, refresh }, { ready: false, refresh: later },
  ]), { initialProps: { identity: "campaign-A/profile-A", refresh: a } });
  await waitFor(() => expect(a).toHaveBeenCalledOnce());
  rerender({ identity: "campaign-B/profile-B", refresh: b });
  await waitFor(() => expect(b).toHaveBeenCalledOnce());
  await act(async () => { finishA(); });
  expect(result.current.checking).toBe(true);
  expect(later).not.toHaveBeenCalled();
  await act(async () => { finishB(); });
  expect(result.current.checking).toBe(false);
  expect(later).not.toHaveBeenCalled();
});


it("does not resume automatic checks after the operator starts and cancels a review", async () => {
  const refresh = vi.fn(async () => {});
  const { rerender } = renderHook(({ paused }) => useMot2DRecovery("same-campaign", [
    { ready: true, refresh },
  ], paused), { initialProps: { paused: true } });
  rerender({ paused: false });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(refresh).not.toHaveBeenCalled();
});
