#!/bin/bash
#SBATCH -p gr20001a
#SBATCH --rsc p=1:t=112:c=112
#SBATCH -t 48:00:00
#SBATCH -o stdout.%J.log
#SBATCH -e stderr.%J.log
#SBATCH -J R20261015-0001

set -o pipefail
runops_exit_record=/work/proj/runs/case/R20261015-0001--x/submit/exit.${SLURM_JOB_ID:-local}
runops_record() {
    printf 'exit_code = %s\nstarted_at = "%s"\nfinished_at = "%s"\nhostname = "%s"\nstage = "%s"\n' "$1" "${runops_start}" "$(date -Is)" "$(hostname)" "$2" > "${runops_exit_record}"
}
runops_setup_failed() {
    local rc=$?
    echo "runops: setup failed exit=${rc}; program not started" >&2
    runops_record "${rc}" setup
}
runops_start=$(date -Is)
trap runops_setup_failed EXIT
set -e
module load intel/2023.2
cd /work/proj/runs/case/R20261015-0001--x
source /work/proj/.venv/bin/activate
export OMP_NUM_THREADS=${SLURM_DPC_CPUS:-112}
export OMP_PROC_BIND=spread
set +e
trap - EXIT
runops_start=$(date -Is)
echo "runops: start ${runops_start} on $(hostname)"
/proj/.runops/build/beach-abc/bin/beach input/beach.toml
status=$?
echo "runops: end $(date -Is) exit=${status}"
runops_record "${status}" run
exit ${status}
