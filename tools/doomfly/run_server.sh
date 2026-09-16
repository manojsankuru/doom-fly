#!/bin/bash
set -euo pipefail
cd /mnt/c/Projects/8710/doomfly
export PATH="$HOME/.local/bin:/mnt/c/Projects/8710/tools/doomfly/bin:$PATH"
source .venv-neural/bin/activate
exec python -m doom.server --port "${PORT:-8766}" "$@"
