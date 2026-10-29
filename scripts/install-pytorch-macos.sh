#!/bin/bash
# Install an isolated, native PyTorch environment without changing the app's venv.
set -Eeuo pipefail
trap 'printf "\nSetup stopped at line %s. Copy the error above for troubleshooting.\n" "$LINENO" >&2' ERR
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'Run this installer in Terminal on the MacBook.' >&2
  exit 1
fi
native_arch="$(uname -m)"
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" == 1 ]]; then
  native_arch=arm64
fi
if [[ "$native_arch" == arm64 ]]; then
  brew_bin=/opt/homebrew/bin/brew
  python_bin=/opt/homebrew/bin/python3.11
else
  brew_bin=/usr/local/bin/brew
  python_bin=/usr/local/bin/python3.11
fi
if [[ ! -x "$python_bin" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python_bin="$(command -v python3.11)"
  elif [[ -x "$brew_bin" ]]; then
    "$brew_bin" install python@3.11
    python_bin="$("$brew_bin" --prefix python@3.11)/bin/python3.11"
  else
    echo 'Python 3.11 is required. Install the macOS universal2 installer from https://www.python.org/downloads/macos/ and run this again.' >&2
    exit 1
  fi
fi
python_arch="$("$python_bin" -c 'import platform; print(platform.machine())')"
if [[ "$python_arch" != "$native_arch" ]]; then
  echo "Python architecture is $python_arch; this Mac needs native $native_arch Python. Open a native Terminal and use native Python 3.11." >&2
  exit 1
fi
lab_dir="$HOME/Applications/PyTorch-Lab"
venv_dir="$lab_dir/.venv"
mkdir -p "$lab_dir"
if [[ -e "$venv_dir" && ! -x "$venv_dir/bin/python" ]]; then
  echo "An incomplete environment exists at $venv_dir. Move it aside and run again." >&2
  exit 1
fi
if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$python_bin" -m venv "$venv_dir"
fi
"$venv_dir/bin/python" - "$native_arch" <<'PY'
import platform, sys
if sys.version_info[:2] != (3, 11) or platform.machine() != sys.argv[1]:
    raise SystemExit('The existing PyTorch-Lab environment must use native Python 3.11; move it aside and rerun.')
PY
"$venv_dir/bin/python" -m pip install --upgrade pip
if [[ "$native_arch" == x86_64 ]]; then
  echo 'Installing the legacy Intel Mac CPU wheel (PyTorch 2.2.2).'
  "$venv_dir/bin/python" -m pip install --only-binary=:all: 'numpy<2' 'torch==2.2.2'
else
  echo 'Installing the newest stable PyTorch wheel compatible with this Mac and Python.'
  "$venv_dir/bin/python" -m pip install --upgrade --only-binary=:all: torch
fi
"$venv_dir/bin/python" -m pip check
"$venv_dir/bin/python" - <<'PY'
import platform
import torch
print('macOS:', platform.mac_ver()[0], '| architecture:', platform.machine())
print('PyTorch:', torch.__version__)
for device in (['cpu', 'mps'] if torch.backends.mps.is_available() else ['cpu']):
    x = torch.tensor([[1., 2.], [3., 4.]], device=device, requires_grad=True)
    result = (x @ x).sum()
    result.backward()
    assert abs(result.item() - 54.) < 0.001
    assert x.grad is not None and bool(torch.isfinite(x.grad).all().item())
    print(device.upper(), 'matrix multiplication and gradients: PASS')
if not torch.backends.mps.is_available():
    print('Apple GPU acceleration unavailable; PyTorch works on CPU.')
PY
printf '\nPyTorch setup and checks passed. To use it:\nsource "%s/bin/activate"\npython\n' "$venv_dir"
