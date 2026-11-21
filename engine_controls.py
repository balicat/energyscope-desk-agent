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

wrong = 0
for what, ok, detail in checks:
    wrong += not ok
    print(("ok    " if ok else "WRONG ") + what + ("" if ok else f": {detail}"))
print(f"{len(checks) - wrong} of {len(checks)} as expected")
sys.exit(1 if wrong else 0)
