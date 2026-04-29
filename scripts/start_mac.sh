#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="finally"
IMAGE_NAME="finally"
PORT=8000

cd "$(dirname "$0")/.."

BUILD=0
OPEN_BROWSER=1
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --no-open) OPEN_BROWSER=0 ;;
    esac
done

if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        echo ".env not found — copying from .env.example. Edit it to add API keys."
        cp .env.example .env
    else
        echo "Error: .env file is required (see .env.example)." >&2
        exit 1
    fi
fi

if [[ "$BUILD" == "1" ]] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Building image..."
    docker build -t "$IMAGE_NAME" .
fi

# Stop existing container if running (idempotent)
docker rm -f "$CONTAINER_NAME" &>/dev/null || true

docker run -d \
    --name "$CONTAINER_NAME" \
    -p "$PORT:8000" \
    -v finally-data:/app/db \
    --env-file .env \
    "$IMAGE_NAME" >/dev/null

echo "FinAlly running at http://localhost:$PORT"

if [[ "$OPEN_BROWSER" == "1" ]] && command -v open &>/dev/null; then
    open "http://localhost:$PORT"
fi
