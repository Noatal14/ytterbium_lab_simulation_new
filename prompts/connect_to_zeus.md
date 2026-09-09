# Prompt: connect to Zeus and prepare the project

Copy everything below this line into a new AI conversation.

---

I need you to guide me through connecting to the Technion Zeus HPC cluster and
preparing the `ytterbium_lab_simulation_new` project for use.

Assume that I am new to HPC systems. I know how to follow instructions and copy
commands, but I do not know SSH, Git, Python environments, PBS, or the Zeus file
system. Guide me patiently, one step at a time, and briefly explain what each
command does.

## Safety rules

- Never ask me to paste my password, private SSH key, access token, or other
  credentials into this conversation.
- Never place credentials inside a command, file, Git repository, or script.
- Tell me to enter a password only into the terminal's own password prompt.
- Do not invent my Zeus username, hostname, repository access method, or local
  operating system.
- Do not use destructive commands such as `rm -rf`, `git reset --hard`, or
  overwriting an existing environment.
- Inspect existing files before creating, replacing, or deleting anything.
- Provide complete, copy-ready commands in separate code blocks.
- Give me only the commands needed for the current step. Wait for me to paste
  the output before continuing when the result determines the next action.

## Authoritative information

The account email from the Technion HPC team and the current official HPC
documentation are authoritative for the Zeus hostname, connection procedure,
VPN requirements, username format, and support process.

If I have not supplied the relevant connection details, ask me to open that
email or documentation and provide only the non-secret information you need.
Never ask me to share the password itself.

The project repository is:

```text
https://github.com/Noatal14/ytterbium_lab_simulation_new
```

The expected repository location on Zeus is:

```text
~/ytterbium_lab_simulation_new
```

The expected Python environment is:

```text
~/venvs/atomsmltr
```

These are expected locations, not permission to overwrite anything already
present there.

## Step 1: establish the connection

First ask me these two short questions:

1. Which operating system am I connecting from: Windows, macOS, or Linux?
2. Do I already have my Zeus username and the official hostname from the HPC
   account email?

Based on my answer, give me the appropriate SSH connection command using the
real username and hostname I provide. Do not leave placeholders in the command.
If the official instructions require a Technion network connection or VPN,
remind me to establish it first.

Ask me to paste the terminal output after attempting the connection. Help me
distinguish normal first-connection host verification, a password prompt,
authentication failure, DNS or network failure, and a successful shell prompt.

Do not continue until the terminal output demonstrates that I am logged in to
Zeus.

## Step 2: inspect the existing Zeus setup

After login, provide safe read-only commands that show:

- the current hostname and username;
- the home-directory path;
- whether `git`, `python`, and `python3` are available;
- whether the expected repository directory exists;
- whether the expected virtual environment exists; and
- the user's current PBS jobs.

Do not create a new clone or environment until these checks are complete.

## Step 3: obtain or update the repository

If `~/ytterbium_lab_simulation_new` already exists:

1. enter it;
2. show `git status --short`;
3. show the current branch and latest commit;
4. inspect configured remotes; and
5. fetch safely before deciding whether a fast-forward pull is possible.

Never pull, switch branches, rebase, stash, discard, or overwrite local changes
without showing me what exists and explaining the consequence. If the checkout
is clean and on `main`, use:

```bash
git pull --ff-only origin main
```

If the repository does not exist, guide me through cloning it into the expected
path. Determine whether HTTPS or SSH authentication is actually available
instead of guessing. Do not request or expose a GitHub token.

## Step 4: inspect or prepare Python

If `~/venvs/atomsmltr` exists, activate it and verify:

- the selected Python executable and version;
- that the repository imports successfully; and
- that the main required packages are available.

Read the repository's current `README.md`, `requirements.txt`, and any relevant
setup documentation before suggesting installation commands.

If the environment is missing or broken, first inspect the current Zeus module
system and the versions used by the repository's existing PBS examples. Then
give me commands to create or repair the environment under `~/venvs/atomsmltr`.
Do not install into the system Python and do not replace an existing environment
without my explicit approval.

## Step 5: verify the project safely

Once the environment is active, run inexpensive checks only:

- Python syntax or import checks;
- a small relevant test subset if documented; and
- confirmation that the expected data and project directories are visible.

Do not submit an expensive simulation merely to test the connection.

## Step 6: teach the minimum PBS basics

Once the setup works, briefly explain:

- a PBS file describes a scheduled Zeus job;
- `qsub` submits it;
- `qstat` shows active jobs;
- a Job ID identifies the submitted job;
- `.out` and `.err` files contain program output and errors; and
- disappearance from `qstat` does not prove success, so historical status and
  `Exit_status` must be checked.

Give me safe commands for viewing my own jobs, but do not submit or delete any
job unless I explicitly ask.

## Completion condition

Consider the setup complete only when all of the following are true:

- I can log in to Zeus;
- `~/ytterbium_lab_simulation_new` is present and its Git state is understood;
- `~/venvs/atomsmltr` activates successfully;
- Python can import the project; and
- I know how to reconnect and inspect my own PBS jobs.

At the end, give me a short copyable checklist containing the exact connection,
repository-entry, environment-activation, Git-update, and job-status commands
that were verified during our conversation.

Begin now by asking only which operating system I use and whether I have the
official Zeus username and hostname from my account email.

