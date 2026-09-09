# Start here

Hi!

This file was written by a human for the next human who works on this project.
Its purpose is to help you get started without getting lost in all the code and
documentation. Most of the technical work can be guided by an AI assistant.

## 1. Get access to Zeus

For long simulations, use the Technion Zeus cluster instead of your personal
computer.

1. Ask Amir to create a Zeus account for you.
2. You will receive an email from the HPC team. Your Zeus credentials should be
   the same as your Technion email credentials, and the email will contain the
   current connection instructions.
3. Open [`prompts/connect_to_zeus.md`](prompts/connect_to_zeus.md), copy the
   complete prompt into a new AI conversation, and follow the instructions.
4. Never send your password, private key, or access token to an AI assistant.

Once you can connect to Zeus and the AI has verified that the repository and
Python environment work, you are ready to run simulations.

## 2. Optimize the 2D MOT for fixed `s0` values

Open [`prompts/run_2d_mot_s0_campaign.md`](prompts/run_2d_mot_s0_campaign.md), copy
the complete prompt into a new AI conversation, and answer the AI's questions.

The AI will give you commands to copy into Zeus. Paste the real output back into
the conversation after every command or completed job. Do not summarize the
output from memory—the exact text helps the AI detect errors.

Do not delete result files or restart an entire campaign unless the AI has first
checked what failed. Completed work is usually saved and can be resumed.

## 3. If you want to understand the project more deeply

You do not need to read everything before starting. When needed, use:

- [`README.md`](README.md) for the project overview;
- [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md) for the current scientific status;
- [`prompts/README.md`](prompts/README.md) for the available AI prompts.

That is enough to begin. Work one step at a time and always paste the real Zeus
output back to the AI assistant.
