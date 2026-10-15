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
module load intel/2023.2 intelmpi/2023.2 hdf5/1.12
export OMP_NUM_THREADS=1
cd /work/proj/runs/case/R20261015-0001--x
rm -f work/*_0000.h5
runops_start=$(date -Is)
echo "runops: start ${runops_start} on $(hostname)"
srun --ntasks=64 /opt/bin/mpiemses3D input/plasma.toml
status=$?
echo "runops: end $(date -Is) exit=${status}"
printf 'exit_code = %s\nstarted_at = "%s"\nfinished_at = "%s"\nhostname = "%s"\n' "${status}" "${runops_start}" "$(date -Is)" "$(hostname)" > "submit/exit.${SLURM_JOB_ID:-local}"
exit ${status}
