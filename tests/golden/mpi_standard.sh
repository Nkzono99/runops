#!/bin/bash
#SBATCH -p gr20001a
#SBATCH --qos=high
#SBATCH --nodes=2
#SBATCH --ntasks=64
#SBATCH -t 12:00:00
#SBATCH -o /work/proj/runs/case/R20261015-0001--x/work/%j.out
#SBATCH -e /work/proj/runs/case/R20261015-0001--x/work/%j.err
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
module load intel/2023.2 intelmpi/2023.2 hdf5/1.12
export OMP_NUM_THREADS=1
cd /work/proj/runs/case/R20261015-0001--x
rm -f work/*_0000.h5
set +e
trap - EXIT
runops_start=$(date -Is)
echo "runops: start ${runops_start} on $(hostname)"
srun --ntasks=64 /opt/bin/mpiemses3D input/plasma.toml
status=$?
echo "runops: end $(date -Is) exit=${status}"
runops_record "${status}" run
exit ${status}
