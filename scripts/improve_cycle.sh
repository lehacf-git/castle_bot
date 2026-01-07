#!/usr/bin/env bash
set -euo pipefail

MINUTES="${1:-10}"

echo "== Running ==" 
castle run --minutes "${MINUTES}"

RUN_ID="$(ls -1t runs | head -n1)"
echo "Latest RUN_ID: ${RUN_ID}"

echo "== Evaluating =="
castle eval "${RUN_ID}"

echo "== Proposing improvements =="
castle improve propose --run-id "${RUN_ID}"

echo
echo "Next steps:"
echo "1) Review the proposal under proposals/<proposal_id>/files/"
echo "2) Apply: castle improve apply --proposal-id <proposal_id>"
echo "3) Re-run cycle"
