# coding-agent-demo

A tiny Node/Express HTTP service used as a **demo target** for the
[**codemagpieai**](https://github.com/apps/codemagpieai) GitHub App.

The point of this repo is to demonstrate the full **create → review** PR
lifecycle of the codemagpie agents that live in
[`techcater/agents`](https://github.com/techcater/agents):

| Phase | Agent | Trigger |
| --- | --- | --- |
| **Create** | `codemagpie-create` (`apps/agents/create/handler.py`) | `@codemagpieai create` (or `implement`) on a GitHub issue |
| **Review** | `codemagpie-review` (`apps/agents/review/handler.py`) | `@codemagpieai review` on the PR (or auto on PR-open if `repoSettings.autoReview` is enabled) |

Both agents are LLM-driven (MiniMax M3) and run as standalone Cloud Run
services behind a single GitHub App. Their implementations, deploy targets,
and the shared agentic loop live in `techcater/agents`.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Service info |
| `GET` | `/healthz` | `{ "status": "ok" }` |
| `GET` | `/hello/:name` | `{ "message": "Hello, <name>!" }` |
| `POST` | `/echo` | `{ "received": <body>, "at": <iso ts> }` |

## Run locally

```bash
npm install
npm test          # node --test
npm start         # listens on :3000
curl http://localhost:3000/healthz
# -> {"status":"ok"}
```

## What the demo does

1. **Open an issue** in this repo describing a small new endpoint.
2. **Mention `@codemagpieai create`** in a comment on that issue. The
   `codemagpie-create` agent:
   - Reads the issue
   - Runs an agentic loop (`py_shared.agents_loop.run_agentic_loop`)
   - Clones this repo, writes code + tests
   - Runs `npm test` to self-verify
   - Opens a PR back to `main`
3. **Mention `@codemagpieai review`** in a comment on the resulting PR. The
   `codemagpie-review` agent:
   - Reads the PR diff
   - Posts inline review comments and a verdict
   - The verdict is `Approved (with N suggestions)` for clean PRs

See [`DEMO.md`](./DEMO.md) for the captured run with PR URLs, commit SHAs,
and the review output.