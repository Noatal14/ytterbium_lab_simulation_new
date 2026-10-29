# AI assistant prompts

This directory contains reusable starting prompts for future researchers who
use an AI assistant to operate established project workflows.

For individual simulations and plots, describe the requested task directly to
the assistant. For a Zeus connection or a complete optimization, use the
corresponding prompt below to operate the existing workflow. These prompts do
not ask the assistant to design a new optimization.

## How to use a prompt

1. Open the relevant Markdown file.
2. Copy the complete prompt into a new AI conversation.
3. Supply the requested experiment-specific values.
4. Follow the assistant one stage at a time and paste the actual Zeus output
   back into the conversation.

Repository code and documentation are always authoritative if they differ from
a saved prompt. Before acting, the assistant must inspect the current checkout.

Never add passwords, private keys, access tokens, or other credentials to these
files.

## Available prompts

- [`connect_to_zeus.md`](connect_to_zeus.md) — guides a new user through a safe
  first connection, repository setup, Python environment verification, and the
  minimum PBS concepts needed to begin working on Zeus.
- [`run_2d_mot_s0_campaign.md`](run_2d_mot_s0_campaign.md) — guides an operator
  through the automated fixed-intensity 2D-MOT optimization campaign on Zeus.
- [`run_3d_mot_campaign.md`](run_3d_mot_campaign.md) — guides an operator
  through the implemented 3D-MOT campaign manager, from the completed 2D-MOT
  survivor handoff through both geometries and sealed final validation.
