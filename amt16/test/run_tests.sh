#!/bin/bash
# Offline test suite for ./amt16 against test/mock_amt.py (no AMT hardware).
set -u
cd "$(dirname "$0")/.." || exit 1
AMT=${AMT_CMD:-./amt16}
T=$(mktemp -d)
export AMT_PASSWORD=correcthorse
trap 'kill $PIDS 2>/dev/null; rm -rf "$T"' EXIT

pass=0 fail=0
ok()  { pass=$((pass+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
check() { # name expected-substring actual
  case "$3" in *"$2"*) ok "$1" ;; *) bad "$1" "expected [$2] in: $(printf '%s' "$3" | tr '\n' '|' | cut -c1-300)" ;; esac
}
checkrc() { # name expected-rc actual-rc
  [ "$2" = "$3" ] && ok "$1" || bad "$1" "expected rc=$2 got rc=$3"
}

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/k.pem" -out "$T/c.pem" \
  -days 2 -subj "/CN=127.0.0.1" >/dev/null 2>&1 || { echo "openssl failed"; exit 1; }
chmod 644 "$T/k.pem" "$T/c.pem"   # mock drops to nobody? no: same user, keep permissive

PIDS=""
start_mock() { # $1 port, rest: env assignments
  local port=$1; shift
  env "$@" python3 test/mock_amt.py "$port" "$T/c.pem" "$T/k.pem" >"$T/mock.$port.log" 2>&1 &
  local pid=$!; PIDS="$PIDS $pid"
  for _ in $(seq 40); do
    if curl -sk --max-time 1 "https://127.0.0.1:$port/wsman" -o /dev/null 2>/dev/null; then return 0; fi
    kill -0 "$pid" 2>/dev/null || { echo "mock died:"; cat "$T/mock.$port.log"; return 1; }
    sleep 0.1
  done
  echo "mock $port did not come up"; cat "$T/mock.$port.log"; return 1
}

echo "== 1. protocol basics (Enumerate -> Pull) =="
REQS="$T/r1"
start_mock 16993 MOCK_STATE=2 MOCK_REQS="$REQS" || exit 1
out=$($AMT -P 16993 info 127.0.0.1 2>&1); rc=$?
checkrc "info rc" 0 $rc
check "info shows power on (2)" "power=on (2)" "$out"
check "info shows available states" "available=2" "$out"
check "request carries wsa:To https URL" '<wsa:To s:mustUnderstand="true">https://127.0.0.1:16993/wsman</wsa:To>' "$(cat "$REQS")"
check "enumerate action used" "enumeration/Enumerate" "$(cat "$REQS")"
check "pull used with context" "<wsen:EnumerationContext>CTX-MOCK-1<" "$(cat "$REQS")"
check "no legacy 16992/RemoteControlService" "" ""
if grep -q "RemoteControlService\|16992\|192.168.0.100" "$REQS"; then
  bad "no legacy endpoint leftovers" "$(grep -o 'RemoteControlService\|16992\|192.168.0.100' "$REQS" | sort -u | tr '\n' ' ')"
else ok "no legacy endpoint leftovers (no 16992 / 192.168.0.100 / RemoteControlService)"; fi
if grep -q 'Content-Type: text/xml' "$REQS" "$T"/*.log 2>/dev/null; then bad "content-type is soap+xml"; else ok "content-type application/soap+xml (mock rejects text/xml with 415)"; fi

echo "== 2. power actions map to the right PowerState =="
for pair in on:2 off:8 softoff:12 cycle:5 reset:10 resetg:14; do
  cmd=${pair%%:*}; want=${pair##*:}
  : >"$REQS.power"
  $AMT -P 16993 "$cmd" 127.0.0.1 >/dev/null 2>&1
  got=$(tail -n1 "$REQS.power" 2>/dev/null)
  [ "$got" = "$want" ] && ok "$cmd -> PowerState $want" || bad "$cmd" "wanted $want got ${got:-none}"
done
: >"$REQS.power"
$AMT -P 16993 power 6 127.0.0.1 >/dev/null 2>&1
[ "$(tail -n1 "$REQS.power")" = 6 ] && ok "power 6 -> PowerState 6" || bad "power 6"
out=$($AMT -P 16993 power abc 127.0.0.1 2>&1); rc=$?
checkrc "power abc rejected" 1 $rc
check "power abc message" "numeric" "$out"

echo "== 3. boot order =="
: >"$REQS.boot"
$AMT -P 16993 pxe 127.0.0.1 >/dev/null 2>&1
check "pxe sets Force PXE Boot" "Intel(r) AMT: Force PXE Boot" "$(cat "$REQS.boot")"
$AMT -P 16993 hdd 127.0.0.1 >/dev/null 2>&1
check "hdd sets Force Hard-drive Boot" "Intel(r) AMT: Force Hard-drive Boot" "$(cat "$REQS.boot")"
check "boot order targets Boot Configuration 0" "Boot Configuration 0" "$(cat "$REQS")"

echo "== 4. inline enumeration (no Pull needed) =="
start_mock 16994 MOCK_DIRECT=1 MOCK_STATE=8 MOCK_REQS="$T/r2" || exit 1
out=$($AMT -P 16994 info 127.0.0.1 2>&1)
check "info handles inline items" "power=off-soft (8)" "$out"

echo "== 5. fault handling =="
start_mock 16995 MOCK_FAULT=1 MOCK_REQS="$T/r3" || exit 1
out=$($AMT -P 16995 info 127.0.0.1 2>&1); rc=$?
checkrc "SOAP fault -> rc 1" 1 $rc
check "fault reason surfaced" "does not exist" "$out"

echo "== 6. HTTP error handling =="
start_mock 16996 MOCK_REJECT=1 MOCK_REQS="$T/r4" || exit 1
out=$($AMT -P 16996 off 127.0.0.1 2>&1); rc=$?
checkrc "401 -> rc 1" 1 $rc
check "401 message" "authentication failed" "$out"

start_mock 16997 MOCK_404=1 MOCK_REQS="$T/r5" || exit 1
out=$($AMT -P 16997 info 127.0.0.1 2>&1)
check "404 message" "HTTP 404" "$out"

out=$($AMT -P 16998 info 127.0.0.1 2>&1); rc=$?
checkrc "closed port -> rc 1" 1 $rc
check "closed port message" "connection failed" "$out"

echo "== 7. multi-host, raw, verbose, cert pinning =="
out=$($AMT -P 16993 off 127.0.0.1 127.0.0.1 2>&1); rc=$?
checkrc "multi-host rc 0" 0 $rc
check "multi-host runs twice" "ok" "$out"
[ "$(printf '%s' "$out" | grep -c 'ok$')" = 2 ] && ok "multi-host: 2 ok lines" || bad "multi-host count"

$AMT -P 16993 -v info 127.0.0.1 >"$T/verbose.out" 2>"$T/verbose.err"
check "verbose dumps request" "--- request" "$(cat "$T/verbose.err")"
check "verbose dumps envelope" "s:Envelope" "$(cat "$T/verbose.err")"

out=$($AMT -P 16993 -c "$T/c.pem" info 127.0.0.1 2>&1)
check "cert pinning with -c works" "power=on (2)" "$out"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$T/wk.pem" -out "$T/wrong.pem" \
  -days 2 -subj "/CN=wrong" >/dev/null 2>&1
out=$($AMT -P 16993 -c "$T/wrong.pem" info 127.0.0.1 2>&1); rc=$?
checkrc "wrong-CA verification rejected" 1 $rc
check "wrong-CA message" "TLS handshake failed" "$out"

python3 - "$T" <<'PY'
import glob, sys, xml.dom.minidom
bad = []
for f in glob.glob(sys.argv[1] + "/r*"):
    if f.endswith((".power", ".boot")):
        continue
    for chunk in open(f).read().split("\n=====\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            xml.dom.minidom.parseString(chunk)
        except Exception as e:
            bad.append(f + ": " + str(e))
print("  \033[32mPASS\033[0m every captured request is well-formed XML" if not bad
      else "  \033[31mFAIL\033[0m malformed XML: " + "; ".join(bad[:3]))
sys.exit(1 if bad else 0)
PY
[ $? -eq 0 ] && pass=$((pass+1)) || fail=$((fail+1))

echo
printf 'total: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
