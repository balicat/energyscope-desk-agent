#!/usr/bin/env bash
# Release gate for the public service. A change to the code, the prompt or the model reaches
# visitors only if the candidate passes, in order:
#   1. the suite on frozen data, answers equal to the golden file      (free)
#   2. the control run: validator off, exactly two assertions fail     (free)
#   3. the suite on today's lake with the scripted model               (free)
#   4. the suite on today's lake with the live model                   (a few cents; LIVE=0 skips it)
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

echo "1/4 frozen data + golden answers";      $PY run_evals.py --source fixture --gate --golden check | tail -2
echo "2/4 control run";                       $PY run_evals.py --source fixture --no-guard --expect-failures 2 | tail -1
echo "3/4 today's lake, scripted model";      $PY run_evals.py --gate | tail -1
if [ "${LIVE:-1}" = "1" ]; then
  export ANTHROPIC_API_KEY=$(tr -d '\r\n' < /opt/energyscope/.anthropic_api_key)
  echo "4/4 today's lake, $MODEL";            $PY run_evals.py --model "$MODEL" --gate | tail -1
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
  curl -fsS "http://10.100.0.2:8790/health" && echo && echo "released $SHA" && exit 0
done
echo "service did not come up" >&2
exit 1
