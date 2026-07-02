"""Minimal online coding agent core — multi-backend edition (local testing for Part 1).

Same design as the Anthropic version in the script: three tools
(read_file / write_file / run_command), a bounded round budget with a
"stop exploring" nudge, and a self-check that reruns any test files the
model touched before trusting "I'm done". Two backends so the loop can be
tested without an Anthropic key:

- ollama   — fully offline, local model (default: gemma4)
- nvidia   — NVIDIA NIM free tier, OpenAI-compatible API (default:
             z-ai/glm-5.1); needs NVIDIA_API_KEY in .env

See README.md for which models were actually verified to return proper
structured tool_calls on NVIDIA's endpoint — several silently don't.
"""

import argparse
import json
import os
import subprocess as sp
import sys
from pathlib import Path

import ollama
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MAX_TOOL_ROUNDS = 20
MAX_SELFCHECK_ROUNDS = 2

DEFAULT_MODELS = {
    "ollama": "gemma4",
    # meta/llama-3.1-70b-instruct and meta/llama-3.3-70b-instruct hung
    # indefinitely on NVIDIA's free tier as of 2026-07-01 (backend
    # unresponsive, not a client bug — verified with raw curl). glm-5.1
    # responded fast with clean structured tool_calls.
    "nvidia": "z-ai/glm-5.1",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repo",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the repo directory",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are a senior engineer implementing a task in the repo at the given "
    "path. You MUST make real changes with write_file - never just describe "
    "them. Use read_file to inspect, write_file to create/modify, run_command "
    "to verify (e.g. run tests). run_command does not keep a working "
    "directory between calls, so use absolute paths. When finished, reply "
    "with a short summary of what changed and no further tool calls."
)


def run_tool(repo_root: Path, name: str, args: dict) -> str:
    """Actually execute one of the three tools the model can call.

    This is the only place in the whole program that touches the filesystem
    or spawns a shell on the model's behalf — every tool call, from every
    backend, funnels through here. Always returns a string (never raises):
    the model sees "Error: ..." as a normal tool_result and can react to it,
    instead of the whole program crashing on a bad path or command.
    """
    if name == "read_file":
        target = (repo_root / args["path"]).resolve()
        # Guardrail: resolve() collapses "..", then this check makes sure
        # the result is still inside repo_root. Without it the model could
        # ask to read_file("../../.ssh/id_rsa") and we'd hand it back.
        if not target.is_relative_to(repo_root):
            return f"Error: path escapes repo root: {args['path']!r}"
        try:
            return target.read_text()
        except Exception as e:
            return f"Error: {e}"

    if name == "write_file":
        target = (repo_root / args["path"]).resolve()
        # Same path-traversal guardrail as read_file — this time it stops
        # the model from writing outside the repo entirely.
        if not target.is_relative_to(repo_root):
            return f"Error: path escapes repo root: {args['path']!r}"
        target.parent.mkdir(parents=True, exist_ok=True)  # allow writing into new subfolders
        target.write_text(args["content"])
        return "OK"  # the loop checks for this exact string to count a successful write

    if name == "run_command":
        cmd = args["command"]
        # Guardrail: caps a runaway/malicious command string before it ever
        # reaches the shell (not a security fix for the shell run below —
        # just a sanity limit).
        if len(cmd) > 2000:
            return "Error: command too long"
        try:
            # /bin/sh -c so the model can use pipes, &&, redirects, etc.
            # cwd=repo_root only sets the *starting* directory — it does
            # NOT persist between calls, which is why the system prompt
            # tells the model to use absolute paths or chain `cd x && ...`.
            r = sp.run(
                ["/bin/sh", "-c", cmd],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=120,  # guardrail: a hung command can't block the loop forever
            )
            return r.stdout + r.stderr
        except sp.TimeoutExpired:
            return "Error: command timed out"

    return f"Error: unknown tool {name}"


# Directory components to skip when scanning for changed test files. Guards
# against a weaker model shelling out `python -m venv .venv && pip install ...`
# inside the repo when it can't find pytest on PATH — pip vendors packages
# (e.g. colorama) that ship their own *_test.py files, which would otherwise
# get swept into the self-check and run against unrelated, often-broken
# dependency test suites.
_IGNORED_DIR_COMPONENTS = {".venv", "venv", "env", "node_modules", "site-packages", "__pycache__", ".git"}


def changed_test_files(repo_root: Path) -> list[str]:
    """Find test files the model touched, so the self-check only reruns those.

    Two git commands cover both cases: `diff` catches test files the model
    *edited* (already tracked by git), `ls-files --others` catches test files
    it *created* (brand new, untracked). Both are needed — a create-style
    task's new test file only shows up in the second one.
    """
    diff = sp.run(
        ["git", "diff", "--name-only"], cwd=repo_root, capture_output=True, text=True
    ).stdout.split()
    untracked = sp.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    ).stdout.split()
    out = []
    for f in {*diff, *untracked}:
        parts = f.split("/")
        # Skip anything living inside a vendor/venv/dependency directory —
        # see _IGNORED_DIR_COMPONENTS above for why this exists.
        if any(p in _IGNORED_DIR_COMPONENTS for p in parts[:-1]):
            continue
        # Match by filename convention only (test_*.py or *_test.py), same
        # as pytest's own default discovery rules.
        if parts[-1].startswith("test_") or parts[-1].endswith("_test.py"):
            out.append(f)
    return out


def run_pytest(repo_root: Path, files: list[str]) -> tuple[bool, str]:
    """Actually run pytest on the given files and report pass/fail + output.

    Uses sys.executable (this script's own venv) rather than whatever
    `python`/`pytest` the model's run_command shell would find — so this
    self-check works even when the model's own `run_command pytest` calls
    fail for PATH reasons. Combined stdout+stderr is handed back to the
    model verbatim on failure so it can see the actual assertion error.
    """
    r = sp.run(
        [sys.executable, "-m", "pytest", "-q", *files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r.returncode == 0, r.stdout + r.stderr


class OllamaBackend:
    """Fully offline — talks to a local `ollama serve` instance.

    Both backend classes exist because Ollama and NVIDIA's OpenAI-compatible
    API speak slightly different wire formats for tool calls (see NvidiaBackend
    below for the differences). `run_agentic_loop` doesn't know or care which
    one it's talking to — it only calls `.step()` and `.append_tool_result()`.
    """

    def __init__(self, model: str):
        self.model = model

    def step(self, messages: list) -> tuple[list[dict], str]:
        """Send the conversation so far, get back the model's next move.

        Returns (tool_calls, text) — tool_calls is empty when the model
        replied with plain text instead of calling a tool (i.e. it thinks
        it's done).
        """
        response = ollama.chat(model=self.model, messages=messages, tools=TOOLS)
        # Ollama's response.message is already a well-formed message object,
        # so unlike the NVIDIA backend we can append it to history as-is.
        messages.append(response.message)
        # Ollama already parses tool arguments into a dict for us (no JSON
        # decoding needed here, unlike the OpenAI-style API below).
        tool_calls = [
            {"id": None, "name": c.function.name, "arguments": c.function.arguments}
            for c in (response.message.tool_calls or [])
        ]
        return tool_calls, response.message.content or ""

    def append_tool_result(self, messages: list, call: dict, result: str) -> None:
        # Ollama matches a tool result back to its call by name, not by id
        # (it doesn't require the id round-trip that OpenAI-style APIs do).
        messages.append({"role": "tool", "content": result, "name": call["name"]})


class NvidiaBackend:
    """NVIDIA NIM free tier — OpenAI-compatible, needs NVIDIA_API_KEY (see .env).

    Not every model in NVIDIA's catalog actually returns proper tool_calls —
    some just echo the tool-call JSON as plain text instead. Verified-working
    models are listed in README.md; don't assume a new model works without
    testing it the same way.
    """

    def __init__(self, model: str):
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key or "your-key-here" in api_key:
            raise RuntimeError("NVIDIA_API_KEY not set — add a real key to .env")
        self.client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
        self.model = model

    def step(self, messages: list) -> tuple[list[dict], str]:
        """Same contract as OllamaBackend.step() — see there for the return shape."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=TOOLS,
            max_tokens=4096,
            # Some NIM-hosted models (e.g. meta/llama-3.1-70b-instruct) reject a
            # follow-up request if a prior assistant turn had >1 tool_calls.
            parallel_tool_calls=False,
        )
        msg = response.choices[0].message
        raw_calls = msg.tool_calls or []

        # Unlike Ollama, the OpenAI-style API requires the assistant message
        # we send back to be reconstructed as a plain dict with an explicit
        # "tool_calls" list (each with an id) — the SDK's response object
        # can't just be re-appended as-is.
        assistant_message = {"role": "assistant", "content": msg.content}
        if raw_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in raw_calls
            ]
        messages.append(assistant_message)

        # Unlike Ollama, arguments come back as a JSON *string*, not a dict —
        # has to be parsed before run_tool() can use it.
        tool_calls = [
            {"id": tc.id, "name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
            for tc in raw_calls
        ]
        return tool_calls, msg.content or ""

    def append_tool_result(self, messages: list, call: dict, result: str) -> None:
        # OpenAI-style APIs require tool_call_id to match a result back to
        # its call (there can be several tool calls per turn in general,
        # even though we force single-calls-only via parallel_tool_calls above).
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})


def make_backend(name: str, model: str):
    """Factory: turn the --backend CLI string into the matching backend object."""
    if name == "ollama":
        return OllamaBackend(model)
    if name == "nvidia":
        return NvidiaBackend(model)
    raise ValueError(f"unknown backend {name!r}")


def run_agentic_loop(backend, repo_root: Path, task: str) -> str:
    """The actual agent: ask the model what to do, do it, repeat until it says it's done.

    This is the whole "brain" from the Part 1 script in one function. Every
    concept from the video shows up here as one specific piece of code:
      - the loop itself           = the agentic tool-use pattern
      - MAX_TOOL_ROUNDS            = the round budget guardrail
      - the "half your rounds" nudge = stops it burning the whole budget exploring
      - the self-check block       = don't trust "I'm done" if it wrote a failing test
    """
    # Conversation history sent to the model on every turn. Starts with the
    # system prompt (the rules) and the task (what to do); every tool call
    # and its result gets appended as the loop progresses, so each new
    # request includes everything the model has seen/done so far.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    write_count = 0       # how many successful write_file calls so far (0 = no-op risk)
    selfcheck_rounds = 0  # how many times we've bounced a failing test back to the model

    for turn in range(MAX_TOOL_ROUNDS):
        tool_calls, content = backend.step(messages)

        # --- The model produced plain text instead of a tool call: it thinks it's done. ---
        if not tool_calls:
            # Don't just trust it. If it wrote any files, and there are test
            # files it touched, actually run them before accepting "done" —
            # this is the self-check from Step 6 of the script. Capped at
            # MAX_SELFCHECK_ROUNDS so a persistently broken test can't loop forever.
            if write_count > 0 and selfcheck_rounds < MAX_SELFCHECK_ROUNDS:
                test_files = changed_test_files(repo_root)
                if test_files:
                    passed, output = run_pytest(repo_root, test_files)
                    if not passed:
                        selfcheck_rounds += 1
                        print(f"[self-check {selfcheck_rounds}] pytest FAILED, sending back")
                        # Feed the failure back as a new user turn and go
                        # straight to the next loop iteration (skips the
                        # "return content" below) so the model gets another
                        # chance to fix its own test.
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Self-check: the tests you wrote are FAILING. "
                                    f"Fix them before finishing.\n\n{output}"
                                ),
                            }
                        )
                        continue
            return content  # genuinely done (or no tests to check, or self-check exhausted)

        # --- The model wants to act: run every tool call it made this turn. ---
        for call in tool_calls:
            print(f"[turn {turn}] {call['name']}({call['arguments']})")
            result = run_tool(repo_root, call["name"], call["arguments"])
            if call["name"] == "write_file" and result == "OK":
                write_count += 1
            # Tell the backend to record the tool's result in `messages` in
            # whatever shape that backend's API expects (see the two
            # append_tool_result() implementations above).
            backend.append_tool_result(messages, call, result)

        # The "stop exploring" nudge (Step 5 of the script): if we're past
        # the halfway point of the round budget and still haven't written
        # anything, inject a warning so the model doesn't burn the entire
        # budget just reading/exploring and end up with nothing to show.
        remaining = MAX_TOOL_ROUNDS - turn - 1
        if write_count == 0 and remaining <= MAX_TOOL_ROUNDS // 2:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "[You've used half your rounds and written nothing. "
                        "Stop exploring and call write_file now.]"
                    ),
                }
            )

    # Fell out of the for-loop: used up every round without the model ever
    # signalling "done" via plain text. The round-budget guardrail in action.
    return "Ran out of rounds without finishing."


if __name__ == "__main__":
    # Usage: python agent.py <repo_path> "<task>" [--backend ollama|nvidia] [--model NAME]
    # e.g.:  python agent.py demo_repo "add a fibonacci function with tests" --backend nvidia
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path")
    parser.add_argument("task")
    parser.add_argument("--backend", choices=["ollama", "nvidia"], default="ollama")
    parser.add_argument("--model", default=None)  # falls back to DEFAULT_MODELS[backend] if omitted
    args = parser.parse_args()

    model = args.model or DEFAULT_MODELS[args.backend]
    backend = make_backend(args.backend, model)
    repo = Path(args.repo_path).resolve()  # resolve so run_tool's repo_root checks are absolute
    print(run_agentic_loop(backend, repo, args.task))
