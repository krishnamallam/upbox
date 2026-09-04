#!/usr/bin/env bash
# Smoke test for a built upbox binary.
#
#   packaging/smoke.sh dist/upbox        # or dist/upbox.exe on Windows
#
# Runs every entry point against a throwaway HOME so the real ~/.upbox is never
# touched, and exits non-zero on the first failure. Local mode (`upbox start`)
# is not exercised: it needs root and, on macOS, a system-extension approval
# that no CI runner can grant. The explicit-proxy mode it builds on is.
set -euo pipefail

bin="${1:?usage: smoke.sh <path-to-upbox-binary>}"
tmp="$(mktemp -d)"
export HOME="$tmp"
export USERPROFILE="$tmp"
cleanup() {
  # shellcheck disable=SC2046
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT

check() {
  local name="$1" expected="$2"
  shift 2
  local out
  out="$("$@" 2>&1)" || true
  if [[ "$out" == *"$expected"* ]]; then
    echo "ok   $name"
  else
    echo "FAIL $name (expected to see: $expected)"
    printf '%s\n' "$out" | head -30
    exit 1
  fi
}

check "help lists erase" "erase" "$bin" --help
check "help lists report" "report" "$bin" --help
check "verify reports an empty chain" "Chain is empty" "$bin" verify
check "report renders" "What upbox holds" "$bin" report
check "doctor runs" "Database:" "$bin" doctor

wait_http() {
  local url="$1" tries="$2" i
  for ((i = 0; i < tries; i++)); do
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

"$bin" dashboard --port 18800 >"$tmp/dashboard.log" 2>&1 &
dash=$!
if wait_http http://127.0.0.1:18800/ 40 && wait_http http://127.0.0.1:18800/transparency 10; then
  echo "ok   dashboard answers / and /transparency"
else
  echo "FAIL dashboard did not answer"
  cat "$tmp/dashboard.log"
  exit 1
fi
kill "$dash" 2>/dev/null || true

"$bin" proxy --port 18888 >"$tmp/proxy.log" 2>&1 &
proxy=$!
# mitmproxy buffers its own log output until more arrives, so the "listening"
# line is not a reliable readiness signal; a connection is. mitmproxy answers a
# bare GET on the proxy port with 502 or 400, and any status at all means the
# proxy is up and serving.
code="000"
for ((i = 0; i < 60; i++)); do
  code="$(curl -s -o /dev/null --max-time 2 -w '%{http_code}' http://127.0.0.1:18888/ 2>/dev/null || true)"
  if [[ -n "$code" && "$code" != "000" ]]; then
    break
  fi
  sleep 0.5
done
kill "$proxy" 2>/dev/null || true
if [[ -n "$code" && "$code" != "000" ]]; then
  echo "ok   proxy accepts connections in explicit-proxy mode (HTTP $code)"
else
  echo "FAIL proxy never accepted a connection on 127.0.0.1:18888"
  cat "$tmp/proxy.log"
  exit 1
fi

echo "all smoke checks passed"
