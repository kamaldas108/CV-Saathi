#!/usr/bin/env bash
# Run every persona twice (r4a, r4b), three at a time, against the server on port 8002.
cd "$(dirname "$0")/.."
OUT=eval/results/round4
ids=$(python -c "import json;print(' '.join(p['id'] for p in json.load(open('eval/personas.json',encoding='utf-8'))['personas']))")
jobs=""
for run in r4a r4b; do for id in $ids; do jobs="$jobs $id:$run"; done; done
printf '%s\n' $jobs | xargs -P 3 -I {} sh -c 'id=${1%%:*}; run=${1##*:}; PYTHONIOENCODING=utf-8 GOOGLE_CLOUD_PROJECT=cv-saathi .venv/Scripts/python eval/run_case.py "$id" "$run" eval/results/round4 8002 2>>eval/results/round4/errors.log | grep -v Warning' _ {}
echo "ROUND DONE"
