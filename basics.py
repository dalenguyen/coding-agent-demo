"""Basics — see one raw model response before the full 3-tool agentic loop.

Run this FIRST, before agent.py. agent.py hands the model 3 tools at once
and loops silently until it's done — if you haven't seen a raw response
shape before that, it's a black box. This file has no loop, no guardrails,
no self-check — just three single requests, each printing exactly what
came back, so the tool_calls structure is familiar before it matters.

  1. No tools at all              -> baseline: what does a plain reply look like?
  2. One tool, but not needed     -> tools being *available* doesn't force their use
  3. One tool, and it's needed    -> this is what a real tool call looks like
"""

import ollama

MODEL = "gemma4"

# Only ONE tool here on purpose — agent.py's TOOLS list has three
# (read_file / write_file / run_command) and seeing all three at once
# before you've seen any of them fire is the overwhelming part.
READ_FILE_TOOL = [
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
]


def show(label: str, response) -> None:
    print(f"\n=== {label} ===")
    print("content:   ", repr(response.message.content))
    print("tool_calls:", response.message.tool_calls)
    for call in response.message.tool_calls or []:
        print(f"  -> model wants to call {call.function.name}({call.function.arguments})")


def basic_no_tools():
    # No `tools=` argument at all. This is just a normal chat call — the
    # baseline every "agent" is built on top of.
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "Say hello in one short sentence."}],
    )
    show("1. No tools — plain chat", response)


def basic_one_tool_not_triggered():
    # The tool is available, but the question has nothing to do with files.
    # Point: handing the model tools doesn't force it to use them — it
    # still replies in tool_calls == [] here, same shape as example 1.
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "What is 2 + 2? Just answer the number."}],
        tools=READ_FILE_TOOL,
    )
    show("2. One tool available, not needed", response)


def basic_one_tool_triggered():
    # Now the prompt actually asks for the tool. This is the response shape
    # the whole rest of the loop (agent.py) is built to handle: content is
    # usually empty/None, and tool_calls has one entry with a name + args.
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "Read the file called notes.txt using the read_file tool."}],
        tools=READ_FILE_TOOL,
    )
    show("3. One tool available, needed", response)


if __name__ == "__main__":
    basic_no_tools()
    basic_one_tool_not_triggered()
    basic_one_tool_triggered()
