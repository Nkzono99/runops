#!/bin/bash
#SBATCH -p gr20001a
#SBATCH --rsc p=1:t=112:c=112
#SBATCH -t 48:00:00
#SBATCH -o stdout.%J.log
#SBATCH -e stderr.%J.log
#SBATCH -J R20261015-0001

set -o pipefail
module load intel/2023.2
cd /work/proj/runs/case/R20261015-0001--x
source /work/proj/.venv/bin/activate
export OMP_NUM_THREADS=${SLURM_DPC_CPUS:-112}
export OMP_PROC_BIND=spread
echo "runops: start $(date -Is) on $(hostname)"
/proj/.runops/build/beach-abc/bin/beach input/beach.toml
status=$?
echo "runops: end $(date -Is) exit=${status}"
exit ${status}
