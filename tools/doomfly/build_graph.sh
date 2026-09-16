#!/bin/bash
set -euo pipefail
cd /mnt/c/Projects/8710/doomfly
export PATH="$HOME/.local/bin:/mnt/c/Projects/8710/tools/doomfly/bin:$PATH"
source .venv-neural/bin/activate
python -m doom.connectome malecns_v1
python -m doom.prepare
python -m doom.audit_data
python -m doom.build_kernel
