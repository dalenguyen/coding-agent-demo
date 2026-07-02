# coding-agent-demo

Test bed for [[Areas/YouTube/Scripts/01 - Build an Online Coding Agent, Part 1]] — same
agentic loop as the script (read_file / write_file / run_command, guardrails,
round budget + nudge, self-check on failing tests), with two backends so
recording doesn't depend on an Anthropic API key/cost:

- `--backend ollama` — fully offline, local model (default `gemma4`)
- `--backend nvidia` — NVIDIA NIM free tier, OpenAI-compatible (default `z-ai/glm-5.1`)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull gemma4   # or any model with "tools" capability — check with `ollama show <model>`
cp .env.example .env  # then paste in a free key from https://build.nvidia.com/settings/api-keys
```

`.env` holds `NVIDIA_API_KEY` for the NVIDIA NIM backend (free tier, OpenAI-compatible,
no credit card — see [[Areas/YouTube/PROJECT_CONTEXT]] for model picks). Gitignored;
only `.env.example` is safe to commit.

## Run

**Start here:** `basics.py` — no loop, no guardrails, just three single
requests (no tools / one unused tool / one triggered tool) that print the
raw response each time. Dropping straight into `agent.py`'s three tools at
once, with no prior look at what a tool-call response even looks like, is
the overwhelming way to learn this — run `basics.py` first.

```bash
.venv/bin/python basics.py
```

Then the full loop. `demo_repo/` is a scratch git repo for the agent to
work in. Reset it fully between takes with
`git -C demo_repo clean -fdxq && git -C demo_repo checkout -q -- .`
(the `-x` matters — the agent sometimes creates its own gitignored `.venv/`
inside the repo, see note below).

```bash
# local, offline
.venv/bin/python agent.py demo_repo "Add a fibonacci(n) function in math_utils.py with a pytest test file" --backend ollama

# NVIDIA NIM free tier (default model: z-ai/glm-5.1)
.venv/bin/python agent.py demo_repo "Add a fibonacci(n) function in math_utils.py with a pytest test file" --backend nvidia
```

## Model notes (verified 2026-07-01)

- Ollama: model must have the `tools` capability (`ollama show <model>` lists
  Capabilities). Plain chat models will silently ignore the `tools` param.
  `gemma4` is 8B/Q4 — noticeably slower and less reliable at multi-step tool
  use than Claude. Good enough to prove the loop mechanics on camera; don't
  expect production-quality code out of it.
- NVIDIA NIM: not every model in the catalog actually returns structured
  `tool_calls` — `meta/llama-3.2-3b-instruct` and `mistralai/mistral-nemotron`
  just echoed/ignored the tool schema. `meta/llama-3.1-70b-instruct` and
  `meta/llama-3.3-70b-instruct` had their hosted backend hang indefinitely
  (confirmed via raw curl, not a client bug) as of 2026-07-01 — may recover
  later, worth retesting before relying on them. Confirmed working with clean
  structured tool calls: `z-ai/glm-5.1` (default), `moonshotai/kimi-k2.6`,
  `openai/gpt-oss-20b`. `qwen2.5-coder-32b-instruct` is no longer in the live
  catalog despite older blog posts mentioning it.
- Real bug caught in testing: a model that can't find `pytest` on the
  `run_command` shell's PATH may build its own `.venv` inside the repo. pip
  vendors packages (e.g. colorama) that ship their own `*_test.py` files —
  without filtering, the self-check sweeps those in and runs pytest against
  unrelated, often-broken dependency test suites. Fixed in `agent.py`'s
  `changed_test_files` by skipping `.venv`/`venv`/`node_modules`/
  `site-packages`/`__pycache__`/`.git` path components. Great on-camera
  moment for the self-check section of the script.
