export const homeFixture = {
  environment: {
    branchLabel: "Branch",
    branchValue: "Unavailable in sample data",
    zeusLabel: "Zeus connection",
    zeusValue: "Not configured in sample data",
  },
  activeCampaignCount: 0,
  campaigns: [
    {
      id: "mot-2d",
      title: "2D-MOT campaign",
      badge: "Recommended first",
      description: "Optimize detuning and magnet radius for one or more fixed laser intensities, then produce survivor ensembles for the 3D MOT.",
      points: ["Requires validated Zeeman survivor ensembles", "You will choose one or more fixed s₀ values"],
      readiness: "later-milestone",
    },
    {
      id: "mot-3d",
      title: "3D-MOT campaign",
      badge: "Unavailable",
      description: "Compare and optimize the donut and single-pass geometries using survivor ensembles from a completed canonical 2D campaign.",
      points: ["A completed canonical 2D-MOT campaign has not been selected", "3D setup unlocks after the upstream handoff validates"],
      readiness: "blocked",
    },
  ],
  steps: [
    { number: "1", title: "Configure", description: "Choose inputs and laboratory settings." },
    { number: "2", title: "Review", description: "Review the campaign plan before anything is created." },
    { number: "3", title: "Run on Zeus", description: "Submit one approved stage at a time." },
    { number: "4", title: "Inspect results", description: "Follow progress and review validated results." },
  ],
} as const;
