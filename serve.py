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
import secrets
import statistics
import threading
import time
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.usage import UsageLimits

from es_agent.agent import Deps, agent, tables_only
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
PER_ADDRESS_PER_DAY = int(os.environ.get("LIBRARIAN_PER_ADDRESS_PER_DAY", "20"))  # one address cannot spend the day
PER_DAY = int(os.environ.get("LIBRARIAN_PER_DAY", "200"))
NTFY = os.environ.get("LIBRARIAN_NTFY", "")  # where to say that half, then nine tenths, of the day is spent
ALERT_AT = (50, 90)
USD_PER_DAY = float(os.environ.get("LIBRARIAN_USD_PER_DAY", "2"))
MODEL_REQUESTS_PER_QUESTION = 8

_run_lock = threading.Lock()  # one question at a time: the lake reads and the spend stay predictable
_state_lock = threading.Lock()
_by_address: dict[str, deque[float]] = defaultdict(deque)
FEEDBACK_LOG = os.environ.get("LIBRARIAN_FEEDBACK_LOG", os.path.join(os.path.dirname(LOG) or ".", "feedback.jsonl"))
FEEDBACK_PER_HOUR = 20
_issued: deque[str] = deque(maxlen=5000)  # ids of answers given; feedback is accepted only against one of these
_feedback_by_address: dict[str, deque[float]] = defaultdict(deque)
_day = {"date": dt.date.today(), "count": 0, "usd": 0.0}
_by_address_day: dict[str, int] = defaultdict(int)
_alerted: set[int] = set()
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
    _alerted.update(m for m in ALERT_AT if _spent_pct() >= m)  # a restart does not repeat an alert already sent
    _issued.extend(r["answer"]["id"] for r in rows if isinstance(r.get("answer"), dict) and r["answer"].get("id"))
    answered = [r for r in rows if r.get("status") == 200 and isinstance(r.get("answer"), dict) and "checked" in r["answer"]]
    if answered:
        _checks.update(answers=len(answered), failed=sum(not r["answer"]["checked"] for r in answered), since=answered[0]["at"][:10])
        _seconds.extend(r["answer"].get("seconds", 0) for r in answered[-200:])


class Refused(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def _spent_pct() -> float:
    return max(_day["count"] / PER_DAY, _day["usd"] / USD_PER_DAY) * 100


def _roll_day() -> None:
    if _day["date"] != dt.date.today():
        _day.update(date=dt.date.today(), count=0, usd=0.0)
        _by_address_day.clear()
        _alerted.clear()


def _alert_if_due() -> None:
    """Tell the owner when the day's budget is half gone and again at nine tenths, once each."""
    for mark in ALERT_AT:
        if _spent_pct() >= mark and mark not in _alerted:
            _alerted.add(mark)
            text = (f"The Librarian: {mark}% of today's budget used "
                    f"({_day['count']} of {PER_DAY} questions, ${_day['usd']:.2f} of ${USD_PER_DAY:.2f}).")
            if NTFY:
                def send(body: str = text) -> None:
                    try:
                        urllib.request.urlopen(urllib.request.Request(NTFY, data=body.encode(), headers={"Title": "The Librarian"}), timeout=10)
                    except OSError:
                        pass
                threading.Thread(target=send, daemon=True).start()


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
        if _by_address_day[address] >= PER_ADDRESS_PER_DAY:
            raise Refused(429, f"Limit of {PER_ADDRESS_PER_DAY} questions a day from one address reached. Come back tomorrow.")
        q.append(now)
        _by_address_day[address] += 1
        _day["count"] += 1
        _alert_if_due()


def _model_for(question: str):
    if MODEL != "scripted":
        return MODEL
    from run_evals import PLANS  # offline mode can only replay the eval questions

    if question not in PLANS:
        raise Refused(400, "Offline mode: only the evaluation questions can be answered.")
    return scripted(*PLANS[question])


def _cost(usage, messages) -> float:
    """Dollars spent on a run. A finished run carries its cost; a run that failed does not, and it is
    the dearest kind (every retry is a model request), so it is summed from the responses received."""
    if usage is not None and getattr(usage, "cost", None):
        return float(usage.cost)
    total = 0.0
    for m in messages:
        try:
            total += float(m.cost().total_price)
        except Exception:
            pass  # a request, or a response the price table does not know
    return total


def answer(question: str, session: str | None = None, emit=lambda tool, args: None) -> dict:
    t0 = time.time()
    model = _model_for(question)
    with _state_lock:
        turns = _sessions.get(session)
    deps = Deps(source=_source, emit=emit)
    degraded = None
    with _run_lock, capture_run_messages() as messages:
        try:
            result = agent.run_sync(
                with_context(question, turns),
                model=model,
                deps=deps,
                usage_limits=UsageLimits(request_limit=MODEL_REQUESTS_PER_QUESTION),
            )
            output, usage = result.output, result.usage
            messages = result.all_messages()
        except (UnexpectedModelBehavior, UsageLimitExceeded) as e:
            # Every attempt at a summary failed a check, or the request budget ran out. The numbers the
            # tools returned were computed by code and can still be shown; the sentences cannot.
            if not (deps.ledger or deps.spreads or deps.readings):
                with _state_lock:  # nothing to show, but the requests were paid for: book them
                    _roll_day()
                    _day["usd"] += _cost(None, messages)
                    _alert_if_due()
                raise
            degraded = f"{type(e).__name__}: {e}"[:300]
            output, usage = tables_only(deps), None
    parts = [p for m in messages for p in m.parts]
    trail = [
        {"tool": p.tool_name, "args": p.args if isinstance(p.args, dict) else json.loads(p.args or "{}")}
        for p in parts
        if isinstance(p, ToolCallPart) and p.tool_name != "final_result"
    ]
    out = output.model_dump(mode="json")
    # Live check: rebuild every number from the data, independently of the run, and record the result.
    try:
        problems = verify(output, _source)
    except Exception as e:
        problems = [f"check failed to run: {type(e).__name__}: {e}"[:300]]
    try:  # the history behind the numbers, for the page to draw; never from the model
        out["charts"] = charts_for(output, _source)
    except Exception:
        out["charts"] = []
    seconds = round(time.time() - t0, 2)
    usd = _cost(usage, messages)
    with _state_lock:
        _roll_day()
        _day["usd"] += usd
        _alert_if_due()
        _checks["answers"] += 1
        _checks["failed"] += bool(problems)
        _seconds.append(seconds)
        if not degraded:  # a follow-up must not be handed a sentence that was never checked
            _sessions.add(session, question, output.summary)
    # An id for this answer: what a reader's "useful" or "wrong" is recorded against, and what ties it to the
    # logged trace. It is not a public link to the answer.
    out["id"] = secrets.token_hex(6)
    with _state_lock:
        _issued.append(out["id"])
    out.update(
        checked=not problems,
        check_problems=problems,
        trail=trail,
        retries=sum(is_rejection(p) for p in parts),
        follow_up=bool(turns),
        model=MODEL,
        seconds=seconds,
        tokens=(usage.total_tokens or 0) if usage else 0,
        degraded=bool(degraded),
        degraded_reason=degraded,
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
                                 "per_address_per_hour": PER_ADDRESS_PER_HOUR, "per_address_per_day": PER_ADDRESS_PER_DAY,
                                 "checked_since_start": dict(_checks)})
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

    def _feedback(self) -> None:
        """A reader's verdict on one answer, written beside the trace it refers to. Accepted only for an id this
        service issued; the note is plain text, capped, and never shown to anyone else."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise ValueError
            doc = json.loads(self.rfile.read(length))
            answer_id, verdict = str(doc.get("id", "")), str(doc.get("verdict", ""))
            note = "".join(ch for ch in str(doc.get("note") or "") if ch.isprintable())[:300]
        except (ValueError, AttributeError):
            return self._send(400, {"error": "Send a JSON body with id and verdict."})
        if verdict not in ("useful", "wrong"):
            return self._send(400, {"error": "verdict must be 'useful' or 'wrong'."})
        now, address = time.time(), self._address()
        with _state_lock:
            if answer_id not in _issued:
                return self._send(404, {"error": "No answer with that id."})
            q = _feedback_by_address[address]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= FEEDBACK_PER_HOUR:
                return self._send(429, {"error": "Feedback limit reached. Try again later."})
            q.append(now)
        try:
            with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                    "id": answer_id, "verdict": verdict, "note": note}) + "\n")
        except OSError:
            return self._send(500, {"error": "Could not record that."})
        self._send(200, {"ok": True})

    def do_POST(self):
        if self.path == "/feedback":
            return self._feedback()
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
        if status == 200:  # the log keeps the detail; the public gets a fixed phrase, never raw exception text
            if body.get("degraded"):
                body["degraded_reason"] = "No summary passed every check."
            body["check_problems"] = ["The check could not be run." if str(p).startswith("check failed to run") else p
                                      for p in body.get("check_problems", [])]
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
