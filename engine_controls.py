"""Control for the server-backed readings (engine.py): what they must refuse, and what their check must catch.

    LIBRARIAN_TODAY=<as_of of fixtures/series.json> python engine_controls.py     # exit 1 if any expectation fails

From the adversary's review of 21 Nov 2026. No model, no server: the fixture replays the server's answers.
"""
import sys

from es_agent import engine
from es_agent.sources import FixtureSource, ServerError

source = FixtureSource("fixtures/series.json")
checks = []


def refused(what, fn):
    try:
        fn()
    except ServerError as e:
        checks.append((what, True, str(e)[:90]))
        return
    checks.append((what, False, "not refused"))


# 1. a spread's statistics obey the rule get_spread obeys: like units, like kinds, like rhythms
for a, b, why in (("NYMEX.WTI.M1.D", "NYMEX.RBOB.M1.D", "dollars a barrel minus dollars a gallon"),
                  ("ICE.BRENT.M1.D", "NYMEX.DUBAI.FRONT.D", "an average-price contract"),
                  ("ICE.BRENT.M1.D", "NYMEX.WTI.M1.D", "nearby months of two expiry calendars")):
    refused(f"get_spread_stats refuses {a} minus {b} ({why})", lambda a=a, b=b: engine._like_for_like(source, a, b))
try:
    note = engine._like_for_like(source, "PET.RBRTE.D", "PET.RWTC.D")
    checks.append(("two spot crudes of one unit and rhythm are allowed, with no note", note == "", note))
except ServerError as e:
    checks.append(("two spot crudes of one unit and rhythm are allowed", False, str(e)[:90]))

# 3. a signals reading is checked against the snapshot read again: a planted metric must not rebuild
live = engine.signals(source)
planted = live.model_copy(deep=True)
key = next(k for k in planted.values if k.startswith("metric."))
planted.values[key] += 0.5
planted.request["body"]["metrics"][key.removeprefix("metric.")] += 0.5
again = engine.rebuild(source, planted)
checks.append((f"a signals reading with {key} planted 0.5 off rebuilds with the snapshot's figure",
               again is not None and abs(again.values[key] - live.values[key]) < 1e-9 and again.values[key] != planted.values[key], key))
checks.append(("the true signals reading rebuilds unchanged", engine.rebuild(source, live).values == live.values, ""))

# 4. the seasonal reading is pinned to its day
s = engine.seasonal(source, "PET.WCESTUS1.W", 5)
checks.append(("the seasonal reading's request names its end date", "end" in s.request["body"], str(s.request["body"])))

# 16. a window reading whose data begin well inside the window says so (front months begin 2 Nov 2026)
try:
    short = engine.spread_stats(source, "NYMEX.HO.M1.D", "NYMEX.RBOB.M1.D", 3)
    checks.append(("a spread's statistics over 3 years of front months that began in November say 'Shorter history'",
                   short.counter.startswith("Shorter history:") or "Shorter history:" in short.counter, short.counter[:90]))
except Exception as e:
    checks.append(("a spread's statistics over a short history", False, f"{type(e).__name__}: {e}"[:120]))
full = engine.stats(source, "PET.RWTC.D", 3)
checks.append(("WTI spot over 3 years carries no 'Shorter history'", "Shorter history" not in full.counter, full.counter[:90]))

# Fair units (the adversary's p8, 21 Nov 2026): every value of the server readings that has a unit, quoted with
# that unit, must pass the prose rules. It is the offline control that would have caught the two true sentences
# the live gate refused ("3.65 percent", "14.27 percent").
from es_agent import metrics as _m, prose as _p
from es_agent.models import DeskAnswer as _A

fair_from = [("eia_weekly report", engine.report(source, "eia_weekly")), ("seasonal", s),
             ("percentile", engine.percentile(source, "NG.RNGWHHD.D", 3)), ("stats", full),
             ("spread", engine.spread_stats(source, "PET.RBRTE.D", "PET.RWTC.D", 3)),
             ("volatility", engine.volatility(source, "PET.RWTC.D", 3, window=20)),
             ("history", engine.history(source, "PET.RWTC.D", 5)),
             ("rolling correlation", engine.rolling_correlation(source, "PET.RWTC.D", "PET.RBRTE.D", 3, window=90)),
             ("signals", live)]
quoted, unfair = 0, []
for name, reading in fair_from:
    for key, value in reading.values.items():
        kind = _p._kind(key)
        unit = "percent" if kind == "percent" else reading.value_units.get(key)
        if unit is None or kind == "count":
            continue
        phrase = f"{abs(value):,.2f}" + ("" if unit == "1" else "%" if unit == "percent" else f" {unit}")
        a = _A(facts=[], readings=[reading], cites=[reading.key], summary=f"The figure for {key} is {phrase}.")
        quoted += 1
        found = _m.untraceable_numbers(a)
        if found:
            unfair.append(f"{name} {key} '{phrase}': {found[:1]}")
checks.append((f"every server value quoted with its own unit passes: {quoted - len(unfair)} of {quoted}", not unfair,
               "; ".join(unfair[:4])))
# a signal metric whose catalogue label names a unit takes no other (the adversary, round 8)
m1m12 = live.values.get("metric.m1_m12")
if m1m12 is not None:
    wrong_units = [f"{abs(m1m12):.2f} million barrels", f"{abs(m1m12):.2f} percent", f"{abs(m1m12):.2f} dollars a gallon"]
    passed = [w for w in wrong_units if not _m.untraceable_numbers(_A(facts=[], readings=[live], cites=[live.key],
                                                                         summary=f"The curve metric is {w}."))]
    checks.append(("the curve metric (labelled $/bbl) written in another unit is refused", not passed and
                   live.value_units.get("metric.m1_m12") is not None, f"passed: {passed}; unit {live.value_units.get('metric.m1_m12')}"))

# 9. fair quotes: the server's own sentences, quoted back word for word with their reading cited, must pass the
# prose rules (the instructions tell the model to quote them "with its numbers and dates unchanged")
import re as _re
from es_agent import metrics
from es_agent.models import DeskAnswer

for name, reading in (("eia_weekly report", engine.report(source, "eia_weekly")),
                      ("signals", live)):
    sentences = [x.strip() for x in _re.split(r"(?<=[.])\s+(?=[A-Z])", reading.context) if _re.search(r"\d", x)]
    refused = []
    for x in sentences:
        a = DeskAnswer(facts=[], readings=[reading], cites=[reading.key], summary=x)
        a.summary = metrics.tidy(a.summary)
        found = metrics.untraceable_numbers(a) + metrics.direction_problems(a)
        if found:
            refused.append(f"{x[:70]} -> {found[:2]}")
    checks.append((f"the {name}'s own sentences quoted back: {len(sentences) - len(refused)} of {len(sentences)} pass",
                   not refused, "; ".join(refused)[:600]))

# 10. a server restart forgets its bearer tokens: the next action logs in again instead of failing for the life
# of the service (21 Nov 2026: get_signals said "authentication error" after the Flight restart)
import json as _json
from types import SimpleNamespace as _NS

from pyarrow import flight as _flight
from es_agent.sources import Server as _Server


class _RestartedServer:
    """Accepts only the token of its latest handshake, as the real server does after a restart."""

    def __init__(self):
        self.token, self.handshakes, self.closed = "old-process-token", 0, 0

    def close(self):
        self.closed += 1

    def authenticate_basic_token(self, key, _password, options=None):
        self.login_timeout = getattr(options, "timeout", None)
        self.handshakes += 1
        self.token = f"token-{self.handshakes}"
        return (b"authorization", f"Bearer {self.token}".encode())

    def do_action(self, action, options):
        if options.headers and dict(options.headers).get(b"authorization") == f"Bearer {self.token}".encode():
            return [_NS(body=_NS(to_pybytes=lambda: _json.dumps({"ok": True}).encode()))]
        raise _flight.FlightUnauthenticatedError("Invalid bearer token")


fake = _RestartedServer()
srv = _Server(address="grpc://unused", key="demo")
srv._client, srv._headers = fake, [(b"authorization", b"Bearer stale-token")]  # a token from before the restart
_orig_connect = _flight.connect
_flight.connect = lambda address: fake
try:
    got = srv.action("healthcheck", {})
    checks.append(("after a server restart the next action logs in again and answers",
                   got == {"ok": True} and fake.handshakes == 1, f"{got}, handshakes {fake.handshakes}"))
    checks.append(("the refused client's channel is closed", fake.closed == 1, f"closed {fake.closed}"))
    # two questions at once: a thread whose token was refused must not drop the client another thread has
    # just logged in with (the adversary's note on 0ac9f63)
    fresh = object()
    srv._client, srv._headers = fresh, [(b"authorization", b"Bearer fresh")]
    srv._drop(fake)
    checks.append(("a thread drops only the client it used, not one another thread just logged in with",
                   srv._client is fresh, f"client now {srv._client!r}"))
    srv._client, srv._headers = fake, [(b"authorization", f"Bearer {fake.token}".encode())]
    fake.token = "another-restart"
    got = srv.action("healthcheck", {})
    checks.append(("and again after a second restart", got == {"ok": True} and fake.handshakes == 2,
                   f"{got}, handshakes {fake.handshakes}"))
    checks.append(("the login has a timeout", fake.login_timeout is not None,
                   f"timeout {fake.login_timeout}"))
    # a call in flight on a channel another thread drops comes back cancelled: one more try on the current channel
    class _Cancelled:
        def do_action(self, action, options):
            srv._client = fake  # meanwhile another thread logged in again on a new channel
            raise _flight.FlightCancelledError("Cancelled")

        def close(self):
            pass

    gone = _Cancelled()
    srv._client, srv._headers = gone, [(b"authorization", f"Bearer {fake.token}".encode())]
    got = srv.action("healthcheck", {})
    checks.append(("a call cancelled because its channel was replaced is tried once more on the new one", got == {"ok": True}, str(got)))

    class _Broken:
        def do_action(self, action, options):
            raise _flight.FlightInternalError("server fault")

        def close(self):
            pass

    srv._client, srv._headers = _Broken(), [(b"authorization", b"Bearer x")]
    try:
        srv.action("healthcheck", {})
        checks.append(("a server fault on the current channel is not retried", False, "answered"))
    except ServerError as e:
        checks.append(("a server fault on the current channel is not retried", "server fault" in str(e), str(e)[:90]))
    srv._client, srv._headers = fake, [(b"authorization", f"Bearer {fake.token}".encode())]
    fake.authenticate_basic_token = lambda k, p, o=None: (_ for _ in ()).throw(_flight.FlightUnauthenticatedError("Invalid API key"))
    fake.token = "third"
    try:
        srv.action("healthcheck", {})
        checks.append(("a refused key is a ServerError, not a loop", False, "answered"))
    except ServerError as e:
        checks.append(("a refused key is a ServerError, not a loop", srv._client is None, str(e)[:90]))
finally:
    _flight.connect = _orig_connect

# 11. the evidence scorecard and get_signals read one evaluation (David, 21 Nov 2026: "one definition, the server's").
# A public answer had said "US crude stocks neutral" beside the server's "crude stocks at a seasonal percentile of 0".
from es_agent import readings as _readings

ev = _readings.evidence(source, "crude_tightness")
sig = engine.signals(source)
_, doc, _ = engine.live_evaluation(source)
active = set(doc.get("active") or [])
mismatch = []
for name, _g, key, tight, loose, _w in _readings.SERVER_LINES:
    if f"{name}_verdict" not in ev.values:
        mismatch.append(f"{name} missing")
        continue
    want = 1 if tight in active else -1 if loose and loose in active else 0
    if ev.values[f"{name}_verdict"] != want or ev.values.get(f"metric.{key}") != sig.values.get(f"metric.{key}"):
        mismatch.append(f"{name}: verdict {ev.values[f'{name}_verdict']} against the server's {want}, "
                        f"metric {ev.values.get(f'metric.{key}')} against {sig.values.get(f'metric.{key}')}")
checks.append((f"every server-scored evidence line ({len(_readings.SERVER_LINES)}) has get_signals' metric and verdict",
               not mismatch, "; ".join(mismatch)))


class _Planted:
    """The fixture, with the server's evaluation saying crude stocks are oversupplied (the metric at 95)."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def snapshot(self):
        s = self.inner.snapshot()
        return dict(s, metrics=dict(s["metrics"], crude_seasonal_pctl=95.0))

    def action(self, name, request):
        if name == "derived_signals" and not request.get("schema"):
            body = dict(request, metrics=dict(request["metrics"], crude_seasonal_pctl=self.inner.snapshot()["metrics"]["crude_seasonal_pctl"]))
            d = dict(self.inner.action(name, body))
            d["active"] = [a for a in d.get("active") or [] if a != "crude_undersupplied"] + ["crude_oversupplied"]
            return d
        return self.inner.action(name, request)


planted = _readings.evidence(_Planted(source), "crude_tightness")
checks.append(("an evidence line follows the server's evaluation: crude stocks oversupplied there reads loose here",
               planted.values.get("us_stocks_verdict") == -1 and planted.values.get("metric.crude_seasonal_pctl") == 95.0,
               f"verdict {planted.values.get('us_stocks_verdict')}, metric {planted.values.get('metric.crude_seasonal_pctl')}"))
checks.append(("the evidence reading rebuilds unchanged from the same source",
               _readings.compute(source, ev.key).values == ev.values and _readings.compute(source, ev.key).table == ev.table, ""))

# 12. the group rule David chose (21 Nov 2026): a server signal firing inside a group decides it, two that disagree
# leave it neutral, none firing leaves it to its lines; the table carries each group's reason, written by code.
rows = {r[0]: r for r in ev.table[1:]}
n_groups = len([k for k in ev.values if k.endswith("_group_verdict")])
checks.append(("the scorecard's table: a header, a row for each group and the overall balance",
               ev.table[:1] == [["Group", "Verdict", "Why"]] and "Overall balance" in rows and len(ev.table) == n_groups + 2,
               str(ev.table)[:300]))
want = "tight" if "crude_undersupplied" in active else "loose" if "crude_oversupplied" in active else None
srow = rows.get("US crude stocks", [])
checks.append(("a group in which a server signal fired takes its verdict, and the reason names the signal",
               want is not None and srow[1:2] == [want] and "crude_" in srow[2], f"{want}: {srow}"))
trow = rows.get("Time structure", [])
checks.append(("a group's reason says whether a server signal decided it or its lines did",
               bool(trow) and ("fired" in trow[2] or "its lines" in trow[2]), str(trow)))


class _Disagree(_Planted):
    """crude_undersupplied and cushing_full both firing: two server signals in one group pointing apart."""

    def snapshot(self):
        return self.inner.snapshot()

    def action(self, name, request):
        if name == "derived_signals" and not request.get("schema"):
            d = dict(self.inner.action(name, request))
            d["active"] = ([a for a in d.get("active") or [] if a not in ("crude_oversupplied", "cushing_tight")]
                           + ["crude_undersupplied", "cushing_full"])
            return d
        return self.inner.action(name, request)


drow = {r[0]: r for r in _readings.evidence(_Disagree(source), "crude_tightness").table[1:]}.get("US crude stocks", [])
checks.append(("two server signals that disagree inside a group leave it neutral, and the reason names both",
               drow[1:2] == ["neutral"] and "crude_undersupplied" in drow[2] and "cushing_full" in drow[2], str(drow)))


class _NoSnapshot(_Planted):
    def snapshot(self):
        raise ServerError("the live metric snapshot could not be read: test")


checks.append(("with the server's signals unreadable the refusal says so, not 'not enough recent data'",
               _readings.evidence(_NoSnapshot(source), "crude_tightness") is None
               and "signals could not be read" in _readings.why_no_evidence(_NoSnapshot(source), "crude_tightness"), ""))

# 13. a hanging login does not queue the threads: four questions on one Server give up within one timeout
import threading as _threading
import time as _time

from es_agent import sources as _sources


class _Hang:
    def authenticate_basic_token(self, key, _password, options=None):
        _time.sleep(getattr(options, "timeout", None) or 0.3)
        raise _flight.FlightTimedOutError("Deadline Exceeded")

    def close(self):
        pass


_saved = _sources.LOGIN_TIMEOUT_S
_sources.LOGIN_TIMEOUT_S = 0.3
_flight.connect = lambda address: _Hang()
try:
    hung = _Server(address="grpc://unused", key="demo")
    errs = []

    def _ask():
        try:
            hung.action("healthcheck", {})
        except ServerError as e:
            errs.append(str(e))

    t0 = _time.time()
    ts = [_threading.Thread(target=_ask) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    took = _time.time() - t0
    checks.append(("four questions behind a hanging login give up together (one timeout), not one after another",
                   len(errs) == 4 and took < 2 * 0.3 + 0.5, f"{len(errs)} errors in {took:.2f} s"))
finally:
    _sources.LOGIN_TIMEOUT_S = _saved
    _flight.connect = _orig_connect

wrong = 0
for what, ok, detail in checks:
    wrong += not ok
    print(("ok    " if ok else "WRONG ") + what + ("" if ok else f": {detail}"))
print(f"{len(checks) - wrong} of {len(checks)} as expected")
sys.exit(1 if wrong else 0)
