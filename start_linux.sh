#!/usr/bin/env bash

# Self-contained installer + launcher for Orb.
# Downloads Miniforge into ./installer_files, creates an isolated conda env,
# installs requirements.txt, then runs uvicorn.

# environment isolation
export PYTHONNOUSERSITE=1
unset PYTHONPATH
unset PYTHONHOME

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if [[ "$(pwd)" =~ " " ]]; then
    echo "This script relies on Miniforge which cannot be silently installed under a path with spaces."
    exit 1
fi

# deactivate any existing conda envs to avoid conflicts
{ conda deactivate && conda deactivate && conda deactivate; } 2> /dev/null

OS_ARCH=$(uname -m)
case "${OS_ARCH}" in
    x86_64*)  OS_ARCH="x86_64";;
    arm64*)   OS_ARCH="aarch64";;
    aarch64*) OS_ARCH="aarch64";;
    *)        echo "Unknown system architecture: $OS_ARCH -- this script runs only on x86_64 or arm64." && exit 1;;
esac

# config
INSTALL_DIR="$(pwd)/installer_files"
CONDA_ROOT_PREFIX="$INSTALL_DIR/conda"
INSTALL_ENV_DIR="$INSTALL_DIR/env"
MINIFORGE_DOWNLOAD_URL="https://github.com/conda-forge/miniforge/releases/download/26.1.0-0/Miniforge3-26.1.0-0-Linux-${OS_ARCH}.sh"
PYTHON_VERSION="3.12"
HOST="${ORB_HOST:-127.0.0.1}"
PORT="${ORB_PORT:-8899}"

conda_exists="F"
if "$CONDA_ROOT_PREFIX/bin/conda" --version &>/dev/null; then conda_exists="T"; fi

# install Miniforge into a contained directory
if [ "$conda_exists" == "F" ]; then
    echo "Downloading Miniforge from $MINIFORGE_DOWNLOAD_URL to $INSTALL_DIR/miniforge_installer.sh"

    mkdir -p "$INSTALL_DIR"
    curl -L "$MINIFORGE_DOWNLOAD_URL" > "$INSTALL_DIR/miniforge_installer.sh"

    chmod u+x "$INSTALL_DIR/miniforge_installer.sh"
    bash "$INSTALL_DIR/miniforge_installer.sh" -b -p "$CONDA_ROOT_PREFIX"

    echo "Miniforge version:"
    "$CONDA_ROOT_PREFIX/bin/conda" --version

    rm "$INSTALL_DIR/miniforge_installer.sh"
fi

# create the env
if [ ! -e "$INSTALL_ENV_DIR" ]; then
    "$CONDA_ROOT_PREFIX/bin/conda" create -y -k --prefix "$INSTALL_ENV_DIR" python="$PYTHON_VERSION"
fi

if [ ! -e "$INSTALL_ENV_DIR/bin/python" ]; then
    echo "Conda environment is empty."
    exit 1
fi

# activate
source "$CONDA_ROOT_PREFIX/etc/profile.d/conda.sh"
conda activate "$INSTALL_ENV_DIR"

# install dependencies -- use a marker so we only re-install when requirements.txt changes
REQ_HASH_FILE="$INSTALL_ENV_DIR/.orb_requirements.sha256"
CURRENT_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
STORED_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
    STORED_HASH="$(cat "$REQ_HASH_FILE")"
fi

if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
    echo "Installing Python dependencies..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
fi

mkdir -p backend/data

echo ""
echo "==========================================="
echo "  Orb running on http://${HOST}:${PORT}"
echo "  Ctrl+C to stop"
echo "==========================================="
echo ""

exec uvicorn backend.main:app --host "$HOST" --port "$PORT" "$@"
