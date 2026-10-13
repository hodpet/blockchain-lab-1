#!/usr/bin/env bash
# Lab 01 setup: create a wallet, mine 101 blocks, report the state.
#
# Read this script before running it. It is deliberately short and does nothing
# you could not type by hand; the point is that you should be able to.

set -euo pipefail

WALLET="lab01"

bc()  { docker compose exec -T bitcoind bitcoin-cli "$@"; }
bcw() { docker compose exec -T bitcoind bitcoin-cli "-rpcwallet=${WALLET}" "$@"; }

echo "== Waiting for bitcoind RPC =="
for _ in $(seq 1 30); do
  if bc getblockchaininfo >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "${ready:-0}" != "1" ]; then
  echo "bitcoind did not become ready. Check: docker compose logs bitcoind" >&2
  exit 1
fi

echo "== Creating / loading wallet '${WALLET}' =="
# createwallet fails if the wallet already exists, so try loadwallet first.
# A descriptor wallet (the modern default) is used; legacy wallets are deprecated.
if bc loadwallet "${WALLET}" >/dev/null 2>&1; then
  echo "   loaded existing wallet"
else
  bc createwallet "${WALLET}" >/dev/null
  echo "   created new descriptor wallet"
fi

echo "== Generating mining address =="
ADDR="$(bcw getnewaddress "mining")"
echo "   ${ADDR}"

echo "== Mining 101 blocks =="
# 101 and not 1: a coinbase output requires 100 further blocks before it is
# spendable (COINBASE_MATURITY). Mining 101 matures exactly the first reward.
bcw -generate 101 >/dev/null

HEIGHT="$(bc getblockcount)"
BALANCE="$(bcw getbalance)"
MATURE="$(bcw listunspent 100 | grep -c '"txid"' || true)"
ALL="$(bcw listunspent 0 | grep -c '"txid"' || true)"

cat <<EOF

== State ==
   block height        : ${HEIGHT}
   spendable balance   : ${BALANCE} BTC
   mature UTXOs        : ${MATURE}
   UTXOs incl. immature: ${ALL}

Note the asymmetry: 101 coinbase outputs exist, exactly one is spendable.
Explain that in your report.

Next: docker compose exec bitcoind bitcoin-cli -rpcwallet=${WALLET} listunspent 100
EOF
