#!/usr/bin/env bash
# Run ONE hard task through --org. Usage: _run_one.sh <name> [per_beat_timeout]
# Lands a self-contained run home under standup-app/hard-task-report/runs/<name>/
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
NAME="$1"; TIMEOUT="${2:-180}"
HOME_DIR="standup-app/hard-task-report/runs/$NAME"
rm -rf "$HOME_DIR"; mkdir -p "$HOME_DIR/tmp"
BRIEF="$(uv run python -c "import json,sys; g=[x for x in json.load(open('standup-app/hard-task-report/_manifest.json')) if x['name']=='$NAME'][0]; print(g['brief'])")"
echo "── running $NAME (per-beat ${TIMEOUT}s) ──"
echo "$BRIEF" > "$HOME_DIR/brief.txt"
# key the env from .env (never printed)
set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
# TMPDIR → run home so mkdtemp(prefix=chorus-standup-) is locatable
export TMPDIR="$(cd "$HOME_DIR/tmp" && pwd)"
START=$(date +%s)
set +e
uv run python standup-app/run.py --org --no-color --timeout "$TIMEOUT" --task "$BRIEF" \
  > "$HOME_DIR/run.log" 2>&1
RC=$?
set -e
END=$(date +%s)
WS="$(ls -d "$TMPDIR"/chorus-standup-* 2>/dev/null | head -1 || true)"
{
  echo "name=$NAME"
  echo "rc=$RC"
  echo "elapsed_s=$((END-START))"
  echo "workspace=$WS"
  echo "db=$WS/company.db"
  echo "report=$WS/report.md"
} > "$HOME_DIR/meta.env"
echo "DONE $NAME rc=$RC elapsed=$((END-START))s ws=$WS"
