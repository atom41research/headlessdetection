#!/usr/bin/env bash
set -euo pipefail

# Start Xvfb so headful Chrome has a display
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
export DISPLAY=:99

# Wait for Xvfb
for i in $(seq 1 30); do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done

MODE="${1:-server}"

case "$MODE" in
    server)
        # Just run the detection server
        exec uv run uvicorn headless_detector.server:app --host 0.0.0.0 --port 8099
        ;;
    test)
        # Start server in background, run tests, exit
        uv run uvicorn headless_detector.server:app --host 0.0.0.0 --port 8099 &
        SERVER_PID=$!

        # Wait for server
        for i in $(seq 1 30); do
            if curl -sf http://127.0.0.1:8099/api/session >/dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done

        shift
        uv run python -m headless_detector.test_detector "$@"
        EXIT_CODE=$?

        kill $SERVER_PID 2>/dev/null || true
        exit $EXIT_CODE
        ;;
    *)
        echo "Usage: docker run <image> [server|test] [--runs N]"
        echo "  server  — start the detection server on port 8099"
        echo "  test    — start the server, run headful+headless tests, exit"
        exit 1
        ;;
esac
