#!/usr/bin/env bash
# Trigger the retail_pipeline DAG and block until the run finishes.
# Exit code reflects the DAG run state. Usage: scripts/run-dag.sh [timeout_seconds] [compose args...]
set -euo pipefail

timeout="${1:-900}"
shift || true
compose=(docker compose "$@")
dag=retail_pipeline
run_id="manual__$(date -u +%Y%m%dT%H%M%SZ)"

"${compose[@]}" exec -T airflow-scheduler airflow dags unpause "$dag" >/dev/null
"${compose[@]}" exec -T airflow-scheduler airflow dags trigger "$dag" --run-id "$run_id" >/dev/null
echo "Triggered $dag run $run_id - waiting (timeout ${timeout}s)..."

deadline=$(( $(date +%s) + timeout ))
while (( $(date +%s) < deadline )); do
    state="$("${compose[@]}" exec -T airflow-scheduler airflow dags state "$dag" "$run_id" 2>/dev/null \
        | tail -n1 | tr -d '\r' | awk '{print $1}')"
    case "$state" in
        success) echo "DAG run $run_id: success"; exit 0 ;;
        failed) echo "DAG run $run_id: FAILED - inspect it in the Airflow UI"; exit 1 ;;
        *) sleep 10 ;;
    esac
done
echo "Timed out waiting for $run_id (last state: ${state:-unknown})"
exit 1
