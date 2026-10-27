import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ZeusJobs } from "../components/ZeusJobs";
import type { ZeusApi, ZeusSnapshot } from "../api/clients/zeus";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
};

const snapshot = (username: string): ZeusSnapshot => ({
  connection_status: "connected",
  profile: { host: "zeus.technion.ac.il", username, project_directory: `/home/${username}/ytterbium_lab_simulation_ui`, authentication: "ssh-key-or-agent" },
  remote: { project_directory: `/home/${username}/ytterbium_lab_simulation_ui`, git_commit: "a".repeat(40), branch: "main", dirty: false },
  scheduler: { status: "available", queried_at: new Date().toISOString(), jobs: [] },
});

describe("ZeusJobs request isolation", () => {
  it("ignores a snapshot that resolves after the username changes", async () => {
    const pending = deferred<ZeusSnapshot>();
    const api = { snapshot: vi.fn(() => pending.promise) } as unknown as ZeusApi;
    const onSnapshot = vi.fn();
    const user = userEvent.setup();
    render(<ZeusJobs campaigns={[]} api={api} loading={false} error={null} onInspect={vi.fn()} onSnapshot={onSnapshot} />);

    const username = screen.getByLabelText("Technion username");
    await user.type(username, "tal.noa");
    await user.click(screen.getByRole("button", { name: "Connect and check status" }));
    await user.clear(username);
    await user.type(username, "other.user");
    pending.resolve(snapshot("tal.noa"));

    await Promise.resolve();
    expect(screen.getByText("Not connected")).toBeVisible();
    expect(screen.queryByText("Connected — read-only snapshot received")).not.toBeInTheDocument();
    expect(onSnapshot).not.toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ username: "tal.noa" }) }));
  });
});
