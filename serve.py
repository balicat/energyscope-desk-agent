"""HTTP front for the desk agent: one question in, one sourced answer out.

    python serve.py                         # offline: scripted model, knows only the eval questions
    LIBRARIAN_MODEL=anthropic:claude-haiku-5-5 python serve.py

POST /ask         {"question": "...", "session": "..."} -> the typed answer (summary, facts, spreads,
                  readings, caveats), the tool trail, and the result of the live check.
POST /ask/stream  the same, as server-sent events: one `tool` event as each tool starts, then `answer`.
GET  /stats       public counts: answers given, how many failed the live check, median seconds.
GET  /health      model, limits and today's count.

Standard library only for the server. Limits, because the page is public and each question costs
money: question length, questions per address per hour, questions per day, dollars per day, model
requests per question, one run at a time. The API key is read from a file, never from the request.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits

from es_agent.agent import Deps, agent
from es_agent.charts import charts_for
from es_agent.memory import Sessions, with_context
from es_agent.scripted import is_rejection, scripted
from es_agent.sources import FixtureSource, FlightSource, ParquetLakeSource
from es_agent.verify import verify

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
USD_PER_DAY = float(os.environ.get("LIBRARIAN_USD_PER_DAY", "2"))
MODEL_REQUESTS_PER_QUESTION = 8

_run_lock = threading.Lock()  # one question at a time: the lake reads and the spend stay predictable
_state_lock = threading.Lock()
_by_address: dict[str, deque[float]] = defaultdict(deque)
_day = {"date": dt.date.today(), "count": 0, "usd": 0.0}
_checks = {"answers": 0, "failed": 0, "since": dt.date.today().isoformat()}
_seconds: deque[float] = deque(maxlen=200)
_sessions = Sessions()
_source = None


def _load_counts() -> None:
    """Carry the public counts across restarts: they are rebuilt from the question log."""
    try:
        with open(LOG, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return
    # The day's limits survive a restart too: a release must not hand out a fresh daily budget.
    today = [r for r in rows if str(r.get("at", ""))[:10] == dt.date.today().isoformat() and r.get("status") != 429]
    _day.update(date=dt.date.today(), count=len(today),
                usd=sum(float(r["answer"].get("usd") or 0) for r in today if isinstance(r.get("answer"), dict)))
    answered = [r for r in rows if r.get("status") == 200 and isinstance(r.get("answer"), dict) and "checked" in r["answer"]]
    if answered:
        _checks.update(answers=len(answered), failed=sum(not r["answer"]["checked"] for r in answered), since=answered[0]["at"][:10])
        _seconds.extend(r["answer"].get("seconds", 0) for r in answered[-200:])


class Refused(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def _roll_day() -> None:
    if _day["date"] != dt.date.today():
        _day.update(date=dt.date.today(), count=0, usd=0.0)


def _admit(address: str) -> None:
    """Count the question against the limits, or refuse it."""
    now = time.time()
    with _state_lock:
        _roll_day()
        if _day["count"] >= PER_DAY or _day["usd"] >= USD_PER_DAY:
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


def answer(question: str, session: str | None = None, emit=lambda tool, args: None) -> dict:
    t0 = time.time()
    model = _model_for(question)
    with _state_lock:
        turns = _sessions.get(session)
    with _run_lock:
        result = agent.run_sync(
            with_context(question, turns),
            model=model,
            deps=Deps(source=_source, emit=emit),
            usage_limits=UsageLimits(request_limit=MODEL_REQUESTS_PER_QUESTION),
        )
    parts = [p for m in result.all_messages() for p in m.parts]
    trail = [
        {"tool": p.tool_name, "args": p.args if isinstance(p.args, dict) else json.loads(p.args or "{}")}
        for p in parts
        if isinstance(p, ToolCallPart) and p.tool_name != "final_result"
    ]
    out = result.output.model_dump(mode="json")
    # Live check: rebuild every number from the data, independently of the run, and record the result.
    try:
        problems = verify(result.output, _source)
    except Exception as e:
        problems = [f"check failed to run: {type(e).__name__}: {e}"[:300]]
    try:  # the history behind the numbers, for the page to draw; never from the model
        out["charts"] = charts_for(result.output, _source)
    except Exception:
        out["charts"] = []
    seconds = round(time.time() - t0, 2)
    usd = float(getattr(result.usage, "cost", None) or 0)
    with _state_lock:
        _roll_day()
        _day["usd"] += usd
        _checks["answers"] += 1
        _checks["failed"] += bool(problems)
        _seconds.append(seconds)
        _sessions.add(session, question, result.output.summary)
    out.update(
        checked=not problems,
        check_problems=problems,
        trail=trail,
        retries=sum(is_rejection(p) for p in parts),
        follow_up=bool(turns),
        model=MODEL,
        seconds=seconds,
        tokens=result.usage.total_tokens or 0,
        usd=round(usd, 5),
    )
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "librarian/0.2"

    def _address(self) -> str:
        if TRUST_PROXY:
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[-1].strip()  # the hop our proxy added, not what the client claimed
        return self.client_address[0]

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path == "/health":
            with _state_lock:
                _roll_day()
                self._send(200, {"ok": True, "model": MODEL, "source": SOURCE_KIND, "today": _day["count"],
                                 "usd_today": round(_day["usd"], 4), "usd_per_day": USD_PER_DAY, "per_day": PER_DAY,
                                 "per_address_per_hour": PER_ADDRESS_PER_HOUR, "checked_since_start": dict(_checks)})
        elif self.path == "/stats":
            with _state_lock:
                self._send(200, {"answers": _checks["answers"], "failed_check": _checks["failed"], "since": _checks["since"],
                                 "median_seconds": round(statistics.median(_seconds), 1) if _seconds else None})
        else:
            self._send(404, {"error": "not found"})

    def _read_question(self) -> tuple[str, str | None]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096:
            raise Refused(400, "Send a JSON body with a question.")
        try:
            doc = json.loads(self.rfile.read(length))
            question = str(doc.get("question", "")).strip()
            session = doc.get("session")
        except (ValueError, AttributeError):
            raise Refused(400, "Send a JSON body with a question.")
        if not question:
            raise Refused(400, "Ask a question.")
        if len(question) > MAX_CHARS:
            raise Refused(400, f"Keep the question under {MAX_CHARS} characters.")
        if not (isinstance(session, str) and 8 <= len(session) <= 64 and session.replace("-", "").isalnum()):
            session = None
        return question, session

    def _log(self, status: int, question: str, body: dict, detail: str | None) -> None:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                    "status": status, "question": question[:MAX_CHARS], "detail": detail,
                                    "answer": {k: v for k, v in body.items() if k != "charts"} if status == 200 else body.get("error")}) + "\n")
        except OSError:
            pass

    def do_POST(self):
        if self.path not in ("/ask", "/ask/stream"):
            return self._send(404, {"error": "not found"})
        stream = self.path == "/ask/stream"
        question, status, body, detail = "", 200, {}, None
        started = False
        write_lock = threading.Lock()

        def event(name: str, data: dict) -> None:
            with write_lock:
                try:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()
                except OSError:
                    pass  # the visitor left; the run finishes and is logged anyway

        try:
            question, session = self._read_question()
            _admit(self._address())
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self._cors()
                self.end_headers()
                started = True
                body = answer(question, session, emit=lambda tool, args: event("tool", {"tool": tool, "args": args}))
            else:
                body = answer(question, session)
        except Refused as r:
            status, body = r.status, {"error": r.message}
        except Exception as e:  # the visitor gets a plain message; the detail goes to the log
            status, body = 502, {"error": "The Librarian could not answer that just now."}
            detail = f"{type(e).__name__}: {e}"[:500]
        self._log(status, question, body, detail)
        if started:  # the event stream is open: errors travel as events too
            event("answer" if status == 200 else "error", body)
        else:
            self._send(status, body)

    def log_message(self, fmt, *args):  # the JSONL file is the log
        pass


def main() -> None:
    global _source
    if MODEL.startswith("anthropic:") and not os.environ.get("ANTHROPIC_API_KEY"):
        with open(KEY_FILE, encoding="utf-8") as f:
            os.environ["ANTHROPIC_API_KEY"] = f.read().strip()
    _source = {"lake": lambda: ParquetLakeSource(LAKE), "flight": FlightSource,
               "fixture": lambda: FixtureSource(os.environ.get("LIBRARIAN_FIXTURE", "fixtures/series.json"))}[SOURCE_KIND]()
    if SOURCE_KIND == "fixture":
        os.environ.setdefault("LIBRARIAN_TODAY", _source.as_of)
    _load_counts()
    print(f"librarian on http://{HOST}:{PORT}  model={MODEL}  source={SOURCE_KIND}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
