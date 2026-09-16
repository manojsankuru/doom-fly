git clone https://github.com/nftechie/doomfly && cd doomfly
python3.11 -m venv .venv-neural && source .venv-neural/bin/activate
pip install -r requirements-neural.txt -r doom/requirements.txt \
  --build-constraint neural-build-constraints.txt
# then the checksum-verified download block from the README
python -m doom.connectome malecns_v1
python -m doom.prepare
python -m doom.audit_data
python -m doom.build_kernel
python -m doom.server --port 8766
