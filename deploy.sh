#!/usr/bin/env bash
# Release gate for the public service. A change to the code, the prompt or the model reaches
# visitors only if the candidate passes, in order:
#   1. the suite on frozen data, answers equal to the golden file;
#      and the control: wrong templates rejected, right ones accepted, tampered answers refused  (free)
#   2. the control run: validator off, exactly two assertions fail     (free)
#   3. the suite on today's lake with the scripted model               (free)
#   4. the suite on today's lake with the live model                   (a few cents; LIVE=0 skips it)
#      A live model does not make the same choices twice, so this step is split: every number check
#      must pass, and at most two behaviour checks (series choice, tool budget) may miss. No case may
#      run out of retries, and the suite has a budget of validator retries in total. A blocked commit
#      may be run a second time, once; every run is kept in ~/librarian-gate.
# Then the running checkout moves to the candidate and the service restarts.
#
#   ./deploy.sh                                  # gate origin/main with the model the service uses
#   LIBRARIAN_MODEL=anthropic:claude-sonnet-5-5 ./deploy.sh   # try a different model through the same gate
set -euo pipefail
cd "$(dirname "$0")"
UNIT=$HOME/.config/systemd/user/librarian.service
CURRENT=$(sed -n 's/^Environment=LIBRARIAN_MODEL=//p' "$UNIT")
MODEL=${LIBRARIAN_MODEL:-$CURRENT}
PY=$PWD/.venv/bin/python
CAND=$(mktemp -d /tmp/librarian-candidate.XXXXXX)
trap 'git worktree remove --force "$CAND" 2>/dev/null || true' EXIT

git fetch -q origin
SHA=$(git rev-parse origin/main)
git worktree add -q --detach "$CAND" "$SHA"
cd "$CAND"
echo "candidate $SHA, model $MODEL"

echo "1/4 frozen data + golden answers";      $PY run_evals.py --source fixture --gate --golden check | grep -E "^assertions|^golden|^gate"
LIBRARIAN_TODAY=$($PY -c "import json;print(json.load(open('fixtures/series.json'))['as_of'])") $PY prose_controls.py | tail -1
echo "2/4 control run";                       $PY run_evals.py --source fixture --no-guard --expect-failures 2 | grep -E "^assertions"
echo "3/4 today's lake, scripted model";      $PY run_evals.py --gate | grep -E "^assertions|^gate"
if [ "${LIVE:-1}" = "1" ]; then
  export ANTHROPIC_API_KEY=$(tr -d '\r\n' < /opt/energyscope/.anthropic_api_key)
  # A live model does not answer the same way twice, so a second run of a blocked commit is allowed once and
  # no more: both runs are written to $GATE with what the validator objected to, and the README reports them.
  GATE=$HOME/librarian-gate; mkdir -p "$GATE"
  RUNS=$(find "$GATE" -name "$SHA-*.json" | wc -l)
  if [ "$RUNS" -ge 2 ]; then
    echo "this commit has had its two live runs (see $GATE): change the code, do not run it again" >&2; exit 1
  fi
  echo "4/4 today's lake, $MODEL, live run $((RUNS + 1)) of at most 2 for this commit"
  echo "    numbers must all be right; at most 2 behaviour misses; no case may run out of retries; at most ${RETRY_BUDGET:-8} retries in total"
  $PY run_evals.py --model "$MODEL" --gate --allow-soft 2 --max-retries "${RETRY_BUDGET:-8}"       --report "$GATE/$SHA-$(date +%s).json" 2>/dev/null | grep -E "^FAILED|^RETRIED|^retries|^cost|^assertions|^gate"
else
  echo "4/4 live model skipped (LIVE=0)"
fi

cd - >/dev/null
git reset -q --hard "$SHA"
sed -i "s#^Environment=LIBRARIAN_MODEL=.*#Environment=LIBRARIAN_MODEL=$MODEL#" "$UNIT"
systemctl --user daemon-reload
systemctl --user restart librarian
for _ in 1 2 3 4 5 6 7 8 9 10; do   # the service reads the catalogue of 357,000 series before it listens
  sleep 2
  if curl -fsS "http://10.100.0.2:8790/health"; then
    echo; echo "released $SHA"
    # The service answering on the lab server is not the visitor's view. Ask through the public address too:
    # on 18 Nov 2026 the page's own server looped for half an hour while this script reported success.
    PUBLIC=${PUBLIC_URL:-https://thelibrarian.energy}
    if curl -fsS -m 20 -o /dev/null "$PUBLIC/" && curl -fsS -m 20 "$PUBLIC/api/stats" > /dev/null; then
      echo "public site answers: $PUBLIC"; exit 0
    fi
    echo "RELEASED, BUT THE PUBLIC SITE DOES NOT ANSWER: $PUBLIC" >&2; exit 1
  fi
done
echo "service did not come up" >&2
exit 1
