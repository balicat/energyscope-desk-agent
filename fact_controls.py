"""Control for the facts a cited reading already carries.

    python fact_controls.py        # exit 1 if any expectation below is not met

After a curve, a crack or a positioning reading the live model tends to list the reading's series again as
facts, typed from the reading. No fact tool returned them, so the validator sent the answer back: the most
common retry of every live run up to 20 Nov 2026. `repeats_of_readings` now names those facts and the validator
drops them. This control says what may be dropped and, more to the point, what may not. No model, no data, no cost.
"""
import datetime as dt
import sys

from es_agent.agent import repeats_of_readings
from es_agent.models import Observation, Reading, SeriesFact

D = dt.date(2026, 11, 18)


def fact(sid: str, lookback: int | None = None, value: float = 1.0) -> SeriesFact:
    return SeriesFact(series_id=sid, name=sid, units="u", latest_period=D, latest_value=value, lookback_days=lookback)


CURVE = Reading(key="curve:brent", title="Brent curve", period=D, units="u",
                series_ids=["ICE.BRENT.M1.D", "ICE.BRENT.M2.D", "ICE.BRENT.M12.D"], values={"M1": 90.0, "M2": 89.0, "M12": 80.0})
CRACK = Reading(key="crack:3-2-1", title="crack", period=D, units="u", series_ids=["PET.RWTC.D", "GAS.D", "HO.D"], values={"crack": 30.0})
WTI = Observation(series_id="PET.RWTC.D", name="WTI", units="u", period=D, value=89.5)

CASES = [
    # (what it shows, facts, cited readings, ledger, the series that must be dropped)
    ("a curve's months repeated as facts are dropped",
     [fact("ICE.BRENT.M1.D"), fact("ICE.BRENT.M12.D")], [CURVE], {}, ["ICE.BRENT.M1.D", "ICE.BRENT.M12.D"]),
    ("a fact with a lookback, repeated from a reading, is dropped too",
     [fact("ICE.BRENT.M1.D", 7)], [CURVE], {}, ["ICE.BRENT.M1.D"]),
    ("a fact a tool DID return is kept, even when a reading carries the series",
     [fact("PET.RWTC.D")], [CRACK], {("PET.RWTC.D", None): WTI}, []),
    ("the same series under a lookback no tool returned is dropped; the returned one stays",
     [fact("PET.RWTC.D"), fact("PET.RWTC.D", 30)], [CRACK], {("PET.RWTC.D", None): WTI}, ["PET.RWTC.D"]),
    ("a fact no tool returned and no cited reading carries is NOT dropped (the validator must still send it back)",
     [fact("PET.RBRTE.D")], [CURVE], {}, []),
    ("with no reading cited nothing is dropped, whatever the model typed",
     [fact("ICE.BRENT.M1.D")], [], {}, []),
    ("a reading the tools returned but the answer did not cite does not excuse a fact",
     [fact("GAS.D")], [CURVE], {}, []),
    ("an ID that differs only in case is another series: not dropped",
     [fact("ice.brent.m1.d")], [CURVE], {}, []),
]


def main() -> int:
    wrong = 0
    for what, facts, cited, ledger, expected in CASES:
        got = [f.series_id for f in repeats_of_readings(facts, cited, ledger)]
        ok = got == expected
        wrong += not ok
        print(("ok    " if ok else "WRONG ") + what + ("" if ok else f": dropped {got}, expected {expected}"))
    # the lookback case above must drop the fact with lookback 30, not the one the tool returned
    kept = repeats_of_readings([fact("PET.RWTC.D"), fact("PET.RWTC.D", 30)], [CRACK], {("PET.RWTC.D", None): WTI})
    if [f.lookback_days for f in kept] != [30]:
        wrong += 1
        print(f"WRONG the dropped fact is the one with lookback 30: got {[f.lookback_days for f in kept]}")
    print(f"{len(CASES) + 1 - wrong} of {len(CASES) + 1} as expected")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
