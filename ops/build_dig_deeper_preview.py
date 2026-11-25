"""Build the Dig deeper preview page from the saved Brent-WTI answer (no deploy; for the owner to look at).

    python ops/build_dig_deeper_preview.py OUT.html
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from es_agent.leads import deeper  # noqa: E402

q = "Why do the two Brent-WTI spreads disagree?"
a = json.loads((root / "fixtures/brent_wti_answer.json").read_text(encoding="utf8"))
d = deeper(a, q)
A = {"question": q, "summary": a["summary"], "caveats": a["caveats"]}


def j(x):
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


t = (root / "ops/dig_deeper_preview_template.html").read_text(encoding="utf8")
Path(sys.argv[1]).write_text(t.replace("__ANSWER__", j(A)).replace("__DEEPER__", j(d)), encoding="utf8")
