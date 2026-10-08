import type { Campaign, CampaignApi } from "../api/campaigns";

export const campaignFixture: Campaign = {
  id: "mot_2d-abc123", family: "mot_2d", kind: "mot_2d_s0_campaign", name: "fixed s0 1.3",
  path: "data/optimization/mot_2d/fixed_s0_1p3", stage: "confirmation",
  stage_semantics: "prepared-workflow-stage", scheduler_status: "unchecked", trust: "trusted-current",
  scientific_role: "candidate-selection", s0_values: [1.3], families: [], git_commit: "abc123",
  remote_preparation: { status: "ready", reason_code: null },
  progress: [
    { stage: "smoke", completed: 1, expected: 1, status: "complete" },
    { stage: "screen", completed: 51, expected: 51, status: "complete" },
    { stage: "confirmation", completed: 2, expected: 5, status: "in-progress" },
  ],
  warnings: [{ severity: "info", message: "Scheduler state is not checked." }],
  next_plan: { label: "Submit confirmation job", command: ["qsub", "data/example.pbs"], display_command: "qsub data/example.pbs", mode: "copy-only", scheduler_status: "unchecked", operation_scope: "remote-submission", executes_automatically: false },
};

export const fixtureApi: CampaignApi = {
  async list() { return { campaigns: [campaignFixture], invalid_count: 0, total: 1 }; },
  async get() { return campaignFixture; },
};
