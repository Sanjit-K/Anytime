#!/usr/bin/env bash
# Run on the Brev L40S VM. NGC credentials are read without terminal echo.
set -euo pipefail

IMAGE="nvcr.io/nim/nvidia/nemotron-3-nano:latest"
CACHE="${HOME}/shiftos-nemotron-cache"
NAME="shiftos-nemotron"

if ! command -v nvidia-smi >/dev/null || ! command -v docker >/dev/null; then
  echo "This script must run on the Brev NVIDIA GPU VM with Docker installed." >&2
  exit 1
fi
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "Container $NAME already exists. Inspect it with: docker ps -a --filter name=$NAME" >&2
  exit 1
fi

mkdir -p "$CACHE"
read -r -s -p "NGC API key (hidden; create at ngc.nvidia.com > profile > Setup): " NGC_API_KEY
printf '\n'
if [[ -z "$NGC_API_KEY" ]]; then
  echo "No key entered; stopping." >&2
  exit 1
fi

# Keep Docker's registry token in a temporary config directory, not ~/.docker.
export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d)"
trap 'unset NGC_API_KEY; rm -rf "$DOCKER_CONFIG"' EXIT
printf '%s' "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin >/dev/null
docker pull "$IMAGE"

# NIM downloads model artifacts at startup, so its container receives the key.
# Docker stores container environment in local inspect metadata on this VM.
docker run -d --name "$NAME" --restart unless-stopped --gpus all --shm-size=16GB \
  -e NGC_API_KEY -v "$CACHE:/opt/nim/.cache" -p 8000:8000 "$IMAGE"
unset NGC_API_KEY

echo "NIM container started. Waiting for /v1/health/ready (model download may take several minutes)."
for _ in $(seq 1 180); do
  if curl --silent --fail http://127.0.0.1:8000/v1/health/ready >/dev/null; then
    echo "Nemotron NIM is ready at http://127.0.0.1:8000/v1"
    exit 0
  fi
  sleep 5
done
echo "NIM did not become ready. Recent logs:" >&2
docker logs --tail 80 "$NAME" >&2
exit 1
