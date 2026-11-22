#!/usr/bin/env bash
# One Python environment for 5.1.1 and 5.1.2 on the NVIDIA DGX Spark (aarch64, Grace + Blackwell GB10).
#
#   bash scripts/dgx/setup_env.sh              # creates .venv-dgx in the repository root
#   bash scripts/dgx/setup_env.sh .venv511     # another folder name
#   TORCH_INDEX=https://download.pytorch.org/whl/cu129 bash scripts/dgx/setup_env.sh   # force a CUDA build
#
# PyTorch is installed first from the CUDA wheel index (cu130, then cu129, cu128), its exact version is
# pinned as a constraint, and only then are the project requirements installed, so pip never swaps
# the CUDA build for a CPU wheel. Ends with scripts/dgx/check_env.py.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="${1:-.venv-dgx}"
PY="${PYTHON:-python3}"

"$PY" - <<'EOF'
import sys
assert sys.version_info >= (3, 10), f"Python >= 3.10 needed, found {sys.version}"
print(f"python {sys.version.split()[0]}")
EOF

if [ ! -x "$VENV/bin/python" ]; then
  echo "== creating $VENV"
  if ! "$PY" -m venv "$VENV"; then
    echo "   venv module unavailable (no ensurepip); falling back to virtualenv"
    "$PY" -m pip install --user --quiet virtualenv
    "$PY" -m virtualenv "$VENV"
  fi
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip wheel

cuda_ok() { python -c 'import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; }

if python -c 'import torch' 2>/dev/null && cuda_ok; then
  echo "== torch already installed with CUDA: $(python -c 'import torch; print(torch.__version__)')"
else
  INDEXES="${TORCH_INDEX:-https://download.pytorch.org/whl/cu130 https://download.pytorch.org/whl/cu129 https://download.pytorch.org/whl/cu128}"
  for idx in $INDEXES; do
    echo "== installing torch from $idx"
    if pip install --quiet --upgrade --force-reinstall torch --index-url "$idx" && cuda_ok; then
      echo "   CUDA OK with $idx"
      break
    fi
    echo "   no working CUDA build from $idx"
  done
  if ! cuda_ok; then
    echo "!! torch has no CUDA here. Everything still runs on CPU (slower picking/training)."
    echo "!! Options: ask the lab which CUDA wheel index they use, or run inside the NGC PyTorch container."
    python -c 'import torch' 2>/dev/null || pip install --quiet torch
  fi
fi

python -c 'import torch; print(f"torch=={torch.__version__}")' > "$VENV/torch-constraint.txt"
echo "== project requirements (torch pinned to $(cat "$VENV/torch-constraint.txt"))"
pip install --quiet -r 511/requirements.txt -r 512/requirements.txt -c "$VENV/torch-constraint.txt"

echo "== environment check"
python scripts/dgx/check_env.py
echo
echo "activate with:  source $VENV/bin/activate"
