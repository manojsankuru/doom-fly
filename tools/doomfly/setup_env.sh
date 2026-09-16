#!/bin/bash
set -euo pipefail
cd /mnt/c/Projects/8710/doomfly
export PATH="$HOME/.local/bin:/mnt/c/Projects/8710/tools/doomfly/bin:$PATH"
if ! command -v uv >/dev/null; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi
uv python install 3.11
if [ ! -x .venv-neural/bin/python ]; then uv venv --python 3.11 --seed .venv-neural; fi
source .venv-neural/bin/activate
python --version
python -m pip install --upgrade pip
PIP_CONSTRAINT= python -m pip install -r requirements-neural.txt -r doom/requirements.txt --build-constraint neural-build-constraints.txt
python -c "import brian2, vizdoom, numba, numpy; print('deps ok', brian2.__version__, vizdoom.__version__, numpy.__version__)"
