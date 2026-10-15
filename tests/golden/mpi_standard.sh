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
echo "runops: start $(date -Is) on $(hostname)"
srun --ntasks=64 /opt/bin/mpiemses3D input/plasma.toml
status=$?
echo "runops: end $(date -Is) exit=${status}"
exit ${status}
