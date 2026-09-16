#!/bin/bash
set -euo pipefail
cd /mnt/c/Projects/8710/doomfly
exec /usr/bin/time -v .venv-neural/bin/python /mnt/c/Projects/8710/tools/doomfly/export_blueprint.py "$@"
