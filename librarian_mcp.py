"""MCP server for The Librarian: lets Claude, ChatGPT or any MCP client ask the public service.

    pip install mcp
    python librarian_mcp.py                      # stdio

Claude Desktop or Claude Code, in the MCP configuration:

    {"mcpServers": {"the-librarian": {"command": "python", "args": ["/path/to/librarian_mcp.py"]}}}

It is a thin client of the public HTTP API, so the same checks and the same limits apply (30
questions an hour and 100 a day from one address). Nothing here computes or rewrites: the tool
returns the service's typed answer unchanged, including `checked`, the caveats code wrote, and the
trail of tool calls.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

try:  # mcp 2.x; the class was called FastMCP in 1.x
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

URL = os.environ.get("LIBRARIAN_URL", "https://thelibrarian.energy").rstrip("/")

mcp = MCPServer(
    "the-librarian",
    instructions=(
        "The Librarian answers oil and gas market questions from EnergyScope data (EIA, futures curves, positioning, "
        "storage, tanker transits). TAKE NUMBERS FROM `facts`, `spreads` AND `readings`: every value there was placed by "
        "code, with its series, date and unit, and recomputed from the data before the answer was returned (`checked` says "
        "whether that recomputation matched). Treat `summary` as prose about those values: its sentences were written by a "
        "model and are held by rules, not proved. Pass on the caveats, and do not add figures of your own. It has no news, "
        "no route freight rates and no physical differentials, and it does not forecast."
    ),
)


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:  # a refusal or a limit: the service says why in its body
        try:
            return {"error": json.loads(e.read()).get("error", str(e)), "status": e.code}
        except ValueError:
            return {"error": str(e), "status": e.code}
    except (urllib.error.URLError, TimeoutError, OSError) as e:  # no answer at all: say so in the same shape
        return {"error": f"The Librarian could not be reached: {e}", "status": 0}


@mcp.tool()
def ask(question: str) -> dict:
    """Ask The Librarian one oil or gas market question in plain English (under 300 characters).

    Take numbers from `facts`, `spreads` and `readings`, never from `summary`: those values were placed by
    code with their series, date and units; the summary is a model's prose about them.

    Returns the typed answer: `summary` (the sentences), `facts`, `spreads` and `readings` (the numbers,
    each with its series, date and units), `caveats` (some written by code: stale inputs, evidence
    against, pairings that are not like for like), `checked` (True when every number was recomputed
    from the data and matched), `trail` (the tool calls made), `id` (for feedback), `seconds`, `usd`.
    If `degraded` is true no summary passed the checks and only the numbers are returned.
    """
    answer = _post("/api/ask", {"question": question})
    answer.pop("charts", None)  # chart points are for the page
    return answer


@mcp.tool()
def feedback(answer_id: str, verdict: str, note: str = "") -> dict:
    """Record that an answer was 'useful' or 'wrong', against the `id` that `ask` returned.
    `note` is optional plain text, up to 300 characters, saying what was wrong."""
    return _post("/api/feedback", {"id": answer_id, "verdict": verdict, "note": note})


if __name__ == "__main__":
    mcp.run()
