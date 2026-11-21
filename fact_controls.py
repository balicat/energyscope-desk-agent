"""Control for the facts a cited reading already carries.

    python fact_controls.py        # exit 1 if any expectation below is not met

After a curve, a crack or a positioning reading the live model tends to list the reading's series again as
facts, typed from the reading. No fact tool returned them, so the validator sent the answer back: the most
common retry of every live run up to 20 Nov 2026. `repeats_of_readings` now names those facts and the validator
reads each one from the data itself, with the function the fact tools use, so the reader keeps the row and its
Excel sheet (dropping them was tried first and cost a reader five fact sheets on two questions). This control
says which facts may be treated so and, more to the point, which may not, and that a fact read from the data
carries nothing the model typed. No model, no lake, no cost.
"""
import datetime as dt
import sys

from es_agent import clock
from es_agent.agent import copy_observation, fact_from_data, newer_than_its_reading, read_fact, repeats_of_readings
from es_agent.models import Change, Observation, Reading, SeriesFact, SeriesHit

D = clock.today()   # the stand-in data moves with the clock, so the change's window always holds it


def fact(sid: str, lookback: int | None = None, value: float = 1.0) -> SeriesFact:
    return SeriesFact(series_id=sid, name=sid, units="u", latest_period=D, latest_value=value, lookback_days=lookback)


CURVE = Reading(key="curve:brent", title="Brent curve", period=D, units="u",
                series_ids=["ICE.BRENT.M1.D", "ICE.BRENT.M2.D", "ICE.BRENT.M12.D"], values={"M1": 90.0, "M2": 89.0, "M12": 80.0})
CRACK = Reading(key="crack:3-2-1", title="crack", period=D, units="u", series_ids=["PET.RWTC.D", "GAS.D", "HO.D"], values={"crack": 30.0})
WTI = Observation(series_id="PET.RWTC.D", name="WTI", units="u", period=D, value=89.5)

CASES = [
    # (what it shows, facts, cited readings, ledger, the series that must be named as repeats)
    ("a curve's months repeated as facts are named",
     [fact("ICE.BRENT.M1.D"), fact("ICE.BRENT.M12.D")], [CURVE], {}, ["ICE.BRENT.M1.D", "ICE.BRENT.M12.D"]),
    ("a fact with a lookback, repeated from a reading, is named too",
     [fact("ICE.BRENT.M1.D", 7)], [CURVE], {}, ["ICE.BRENT.M1.D"]),
    ("a fact a tool DID return is kept, even when a reading carries the series",
     [fact("PET.RWTC.D")], [CRACK], {("PET.RWTC.D", None): WTI}, []),
    ("the same series under a lookback no tool returned is named; the returned one stays",
     [fact("PET.RWTC.D"), fact("PET.RWTC.D", 30)], [CRACK], {("PET.RWTC.D", None): WTI}, ["PET.RWTC.D"]),
    ("a fact no tool returned and no cited reading carries is NOT named (the validator must still send it back)",
     [fact("PET.RBRTE.D")], [CURVE], {}, []),
    ("with no reading cited nothing is named, whatever the model typed",
     [fact("ICE.BRENT.M1.D")], [], {}, []),
    ("a reading the tools returned but the answer did not cite does not excuse a fact",
     [fact("GAS.D")], [CURVE], {}, []),
    ("an ID that differs only in case is another series: not named",
     [fact("ice.brent.m1.d")], [CURVE], {}, []),
]


class Days:
    """Three days of one series, in place of the lake."""
    def meta(self, series_id):
        return SeriesHit(series_id="X.D", name="Series X", units="dollars", frequency="D") if series_id == "X.D" else None

    def history(self, series_id, start=None):
        rows = [(D - dt.timedelta(days=2), 10.0), (D - dt.timedelta(days=1), 11.0), (D, 12.0)]
        return [r for r in rows if start is None or r[0] >= start] if series_id == "X.D" else []


def main() -> int:
    wrong = 0
    for what, facts, cited, ledger, expected in CASES:
        got = [f.series_id for f in repeats_of_readings(facts, cited, ledger)]
        ok = got == expected
        wrong += not ok
        print(("ok    " if ok else "WRONG ") + what + ("" if ok else f": named {got}, expected {expected}"))
    extra = []
    # the lookback case above must name the fact with lookback 30, not the one the tool returned
    named = repeats_of_readings([fact("PET.RWTC.D"), fact("PET.RWTC.D", 30)], [CRACK], {("PET.RWTC.D", None): WTI})
    extra.append(("the named fact is the one with lookback 30", [f.lookback_days for f in named] == [30]))
    # reading a fact from the data: the tool's figures, name and units, whatever the model typed
    src = Days()
    obs = read_fact(src, "X.D", None)
    extra.append(("a latest value is read from the data", isinstance(obs, Observation) and (obs.period, obs.value) == (D, 12.0)))
    typed = fact("X.D", None, value=999.0)
    shown = fact_from_data(obs)
    extra.append(("the fact shown carries the data's value, name and units, not the typed ones",
                  (shown.latest_value, shown.name, shown.units) == (12.0, "Series X", "dollars") and typed.latest_value == 999.0))
    ch = read_fact(src, "X.D", 2)
    extra.append(("a change is read from the data with its base", isinstance(ch, Change)
                  and (ch.base_period, ch.base_value, ch.change_abs) == (D - dt.timedelta(days=2), 10.0, 2.0)))
    extra.append(("a series the data does not have gives nothing to show", read_fact(src, "NOPE.D", None) is None))
    extra.append(("a change with too little history gives nothing to show", read_fact(src, "X.D", 4000) is None))
    # a reading dated before the series' latest: the fact would show a newer price beside the reading's
    def reading(day):
        return Reading(key="curve:x", title="x", period=day, units="u", series_ids=["X.D"], values={"M1": 11.0})
    yesterday = D - dt.timedelta(days=1)
    extra.append(("a series with a value newer than its reading's date is not added as a fact",
                  newer_than_its_reading(obs, "X.D", [reading(yesterday)]) == yesterday))
    extra.append(("a series whose latest is the reading's date is added", newer_than_its_reading(obs, "X.D", [reading(D)]) is None))
    extra.append(("a series older than the reading's date is added (the reading used that value)",
                  newer_than_its_reading(obs, "X.D", [reading(D + dt.timedelta(days=2))]) is None))
    extra.append(("with two readings carrying the series, the earlier date decides",
                  newer_than_its_reading(obs, "X.D", [reading(D), reading(yesterday)]) == yesterday))
    extra.append(("a change is judged by its latest date", newer_than_its_reading(ch, "X.D", [reading(yesterday)]) == yesterday))
    # a change typed onto a latest-value fact (21 Nov 2026, live): the observation keeps nothing the model added
    typed = SeriesFact(series_id="X.D", name="typed", units="typed", latest_period=D, latest_value=12.0,
                       base_period=D - dt.timedelta(days=2), base_value=10.0, change_abs=2.0, change_pct=20.0)
    shown = copy_observation(typed, obs)
    extra.append(("a change typed onto a latest value is removed; the value, name and units are the data's",
                  (shown.base_period, shown.base_value, shown.change_abs, shown.change_pct) == (None, None, None, None)
                  and (shown.latest_value, shown.name, shown.units) == (12.0, "Series X", "dollars")))
    for what, ok in extra:
        wrong += not ok
        print(("ok    " if ok else "WRONG ") + what)
    total = len(CASES) + len(extra)
    print(f"{total - wrong} of {total} as expected")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
