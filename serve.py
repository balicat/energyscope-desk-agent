"""HTTP front for the desk agent: one question in, one sourced answer out.

    python serve.py                         # offline: scripted model, knows only the eval questions
    LIBRARIAN_MODEL=anthropic:claude-sonnet-5-5 python serve.py

POST /ask {"question": "..."} returns the typed answer (summary, facts,
caveats) plus the tool trail, so a page can show where each number came from.
GET /health reports the model, the limits and today's count.

Standard library only for the server. Limits, because the page is public and
each question costs money: question length, questions per address per hour,
questions per day in total, model requests per question, one run at a time.
The API key is read from a file, never from the request.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits

from es_agent.agent import Deps, agent
from es_agent.scripted import is_rejection, scripted
from es_agent.sources import FlightSource, ParquetLakeSource

MODEL = os.environ.get("LIBRARIAN_MODEL", "scripted")
KEY_FILE = os.environ.get("LIBRARIAN_KEY_FILE", "/opt/energyscope/.anthropic_api_key")
LAKE = os.environ.get("LIBRARIAN_LAKE", "/opt/energyscope/data")
SOURCE_KIND = os.environ.get("LIBRARIAN_SOURCE", "lake")
HOST = os.environ.get("LIBRARIAN_HOST", "127.0.0.1")
PORT = int(os.environ.get("LIBRARIAN_PORT", "8790"))
ORIGINS = set(os.environ.get("LIBRARIAN_ORIGINS", "https://thelibrarian.energy").split(","))
LOG = os.environ.get("LIBRARIAN_LOG", "questions.jsonl")
TRUST_PROXY = os.environ.get("LIBRARIAN_TRUST_PROXY", "0") == "1"  # read X-Forwarded-For only behind our own proxy

MAX_CHARS = 300
PER_ADDRESS_PER_HOUR = int(os.environ.get("LIBRARIAN_PER_HOUR", "6"))
PER_DAY = int(os.environ.get("LIBRARIAN_PER_DAY", "200"))
MODEL_REQUESTS_PER_QUESTION = 8

_run_lock = threading.Lock()  # one question at a time: the lake reads and the spend stay predictable
_state_lock = threading.Lock()
_by_address: dict[str, deque[float]] = defaultdict(deque)
_day = {"date": dt.date.today(), "count": 0}
_source = None


class Refused(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def _admit(address: str) -> None:
    """Count the question against both limits, or refuse it."""
    now = time.time()
    with _state_lock:
        if _day["date"] != dt.date.today():
            _day.update(date=dt.date.today(), count=0)
        if _day["count"] >= PER_DAY:
            raise Refused(429, "The Librarian has answered its limit of questions for today. Come back tomorrow.")
        q = _by_address[address]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= PER_ADDRESS_PER_HOUR:
            raise Refused(429, f"Limit of {PER_ADDRESS_PER_HOUR} questions an hour reached. Try again later.")
        q.append(now)
        _day["count"] += 1


def _model_for(question: str):
    if MODEL != "scripted":
        return MODEL
    from run_evals import PLANS  # offline mode can only replay the eval questions

    if question not in PLANS:
        raise Refused(400, "Offline mode: only the evaluation questions can be answered.")
    return scripted(*PLANS[question])


def answer(question: str) -> dict:
    t0 = time.time()
    model = _model_for(question)
    with _run_lock:
        result = agent.run_sync(
            question,
            model=model,
            deps=Deps(source=_source),
            usage_limits=UsageLimits(request_limit=MODEL_REQUESTS_PER_QUESTION),
        )
    parts = [p for m in result.all_messages() for p in m.parts]
    trail = [
        {"tool": p.tool_name, "args": p.args if isinstance(p.args, dict) else json.loads(p.args or "{}")}
        for p in parts
        if isinstance(p, ToolCallPart) and p.tool_name != "final_result"
    ]
    out = result.output.model_dump(mode="json")
    out.update(
        trail=trail,
        retries=sum(is_rejection(p) for p in parts),
        model=MODEL,
        seconds=round(time.time() - t0, 2),
        tokens=result.usage.total_tokens or 0,
    )
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "librarian/0.1"

    def _address(self) -> str:
        if TRUST_PROXY:
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[-1].strip()  # the hop our proxy added, not what the client claimed
        return self.client_address[0]

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        origin = self.headers.get("Origin", "")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path == "/health":
            with _state_lock:
                today = _day["count"] if _day["date"] == dt.date.today() else 0
            self._send(200, {"ok": True, "model": MODEL, "source": SOURCE_KIND, "today": today,
                             "per_day": PER_DAY, "per_address_per_hour": PER_ADDRESS_PER_HOUR})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/ask":
            return self._send(404, {"error": "not found"})
        question, status, body = "", 200, {}
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise Refused(400, "Send a JSON body with a question.")
            try:
                question = str(json.loads(self.rfile.read(length)).get("question", "")).strip()
            except (ValueError, AttributeError):
                raise Refused(400, "Send a JSON body with a question.")
            if not question:
                raise Refused(400, "Ask a question.")
            if len(question) > MAX_CHARS:
                raise Refused(400, f"Keep the question under {MAX_CHARS} characters.")
            _admit(self._address())
            body = answer(question)
        except Refused as r:
            status, body = r.status, {"error": r.message}
        except Exception as e:  # the visitor gets a plain message; the detail goes to the log
            status, body = 502, {"error": "The Librarian could not answer that just now."}
            body["_detail"] = f"{type(e).__name__}: {e}"[:500]
        detail = body.pop("_detail", None)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                    "status": status, "question": question[:MAX_CHARS], "detail": detail,
                                    "answer": body if status == 200 else body.get("error")}) + "\n")
        except OSError:
            pass
        self._send(status, body)

    def log_message(self, fmt, *args):  # the JSONL file is the log
        pass


def main() -> None:
    global _source
    if MODEL.startswith("anthropic:") and not os.environ.get("ANTHROPIC_API_KEY"):
        with open(KEY_FILE, encoding="utf-8") as f:
            os.environ["ANTHROPIC_API_KEY"] = f.read().strip()
    _source = ParquetLakeSource(LAKE) if SOURCE_KIND == "lake" else FlightSource()
    print(f"librarian on http://{HOST}:{PORT}  model={MODEL}  source={SOURCE_KIND}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
