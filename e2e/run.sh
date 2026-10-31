#!/usr/bin/env bash
# Check both apps together, always: backend tests, the Apple app's rules and
# its store against a fresh local Planner OS API, and every Android test
# (unit, touch, and the same end-to-end flows against the same API).
#
#   e2e/run.sh                      # on a Mac with Xcode and the Android SDK
#   SWIFTC=/path/to/swiftc GRADLE_ARGS="-I mirror.gradle" e2e/run.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-8765}
SWIFTC=${SWIFTC:-swiftc}
URL="http://127.0.0.1:$PORT"
BUILD=$(mktemp -d)

python3 "$ROOT/e2e/server.py" "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true; rm -rf "$BUILD"' EXIT
for _ in $(seq 1 60); do curl -sf "$URL/api/health" >/dev/null && break; sleep 0.5; done
curl -sf "$URL/api/health" >/dev/null || { echo "The local API did not start"; exit 1; }

cd "$ROOT"
echo "== Backend tests"
python3 -m pytest -q

APPLE=apple/PlannerOS
echo "== Apple: Focus and timeline rules"
"$SWIFTC" -swift-version 5 $APPLE/Models.swift $APPLE/FocusPolicy.swift $APPLE/TimelinePolicy.swift $APPLE/PlannerAPI.swift \
    apple/PolicyTests/main.swift -o "$BUILD/policy"
"$BUILD/policy"

echo "== Apple: every action against the API"
"$SWIFTC" -swift-version 5 $APPLE/Models.swift $APPLE/FocusPolicy.swift $APPLE/TimelinePolicy.swift $APPLE/PlannerAPI.swift \
    $APPLE/PlannerStore.swift apple/EndToEnd/StandIns.swift apple/EndToEnd/main.swift -o "$BUILD/e2e"
"$BUILD/e2e" "$URL"

echo "== Android: unit, touch and end-to-end tests"
(cd android && PLANNER_E2E_URL="$URL" ./gradlew -q ${GRADLE_ARGS:-} testDebugUnitTest)

echo "All checks passed for both apps."
