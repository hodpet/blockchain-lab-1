# Lab 01 — Bitcoin Core in Regtest: UTXO state and raw transactions

**Theory:** [[01 - Introduction to Blockchain Technology and the History of Bitcoin]]
**Stack:** Docker, Bitcoin Core 27, Python 3.11+ (uv)
**Points:** 10

---

## Objectives

By the end of this lab you will have run a private Bitcoin network, mined blocks into your own wallet, and constructed a transaction byte by byte without any wallet software helping you.

The point is not to move coins — any wallet does that. The point is to see that a "balance" is a derived quantity, that a transaction is a set operation over UTXOs, and that the fee is a remainder rather than a field. These three facts are stated in the theory chapter; here you verify them against a real consensus implementation that will reject you if you get them wrong.

You will also write a parser for the raw serialisation format, which is the most reliable way to learn it. Reading the format specification produces recognition; implementing it produces understanding.

---

## Prerequisites

- Docker Desktop running (WSL 2 backend on Windows)
- `uv` installed (see `../README.md`)
- Roughly 2 GB of free disk space

No Bitcoin knowledge beyond the Week 1 chapter is assumed. **Regtest mode uses no real money and connects to no public network.** The coins you mine here have no existence outside your machine.

---

## What is regtest?

Bitcoin Core supports three networks. **Mainnet** is the real one. **Testnet** is a public network with worthless coins and real, slow mining. **Regtest** (regression test mode) is a private network where *you* control block production: blocks are mined on demand, instantly, at difficulty 1.

Regtest is the correct environment for this lab because it gives determinism. You decide when a block exists, so there are no confirmation delays and no interference from other participants.

---

## Setup

### 1. Start the node

```powershell
docker compose up -d
```

This starts `bitcoind` in regtest mode with RPC exposed on port 18443. Configuration lives in `bitcoin.conf`; read it — every line is commented and explains a consensus- or RPC-relevant setting.

Check that it is alive:

```powershell
docker compose exec bitcoind bitcoin-cli getblockchaininfo
```

You should see `"chain": "regtest"` and `"blocks": 0`. If you see a connection error, wait five seconds and retry; the daemon takes a moment to open the RPC port.

### 2. Create a wallet and mine

```powershell
./scripts/setup.ps1
```

On macOS or Linux use `./scripts/setup.sh` instead. The script is short and worth reading before running — it does four things.

It creates a descriptor wallet named `lab01`. It generates a receiving address. It mines **101 blocks** to that address. And it prints the resulting balance.

> [!NOTE]
> **Why 101 blocks and not 1?**
> A coinbase output — the block reward — cannot be spent until 100 further blocks have been built on top of it. This is the **coinbase maturity** rule, and it exists because a chain reorganisation invalidates the coinbase of any orphaned block; without maturity, coins from a block that later disappears could already have been spent onward, corrupting the ledger. Mining 101 blocks matures exactly the first one, giving you one spendable 50 BTC output.

After the script completes:

```powershell
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 getbalance
```

You should see `50.00000000`.

---

## Part A — Observing UTXO state

Run:

```powershell
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 listunspent
```

The output is a JSON array. Note carefully what it is and what it is not: it is a list of **discrete outputs**, each with a `txid`, a `vout` index and an `amount`. It is not a balance. The balance reported by `getbalance` is the sum of this list, computed by the wallet, not stored anywhere in the protocol.

**Record for your report:** the `txid` and `vout` of your single mature output, and the total number of unspent outputs the wallet can see (mature and immature).

Now inspect the UTXO set from the node's perspective, which is independent of any wallet:

```powershell
docker compose exec bitcoind bitcoin-cli gettxoutsetinfo
```

Compare `txouts` with what the wallet reported and explain the difference in your report.

---

## Part B — Building a raw transaction by hand

This is the core exercise. You will spend your mature 50 BTC output, sending 10 BTC to a new address and returning the remainder to yourself, paying a fee you compute manually.

### B1. Get the input

```powershell
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 listunspent 100
```

The `100` argument filters to outputs with at least 100 confirmations — that is, mature ones. Take note of `txid` and `vout`.

### B2. Generate a destination and a change address

```powershell
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 getnewaddress "destination"
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 getnewaddress "change"
```

### B3. Compute the amounts

You have 50 BTC. You are sending 10. Choose a fee of 0.0001 BTC. Therefore:

```
change = 50 - 10 - 0.0001 = 39.9999
```

> [!WARNING]
> **This arithmetic is the entire lab.** There is no fee field in a Bitcoin transaction. The fee is `sum(inputs) - sum(outputs)`, computed implicitly by every validating node. If you omit the change output, you will construct a *perfectly valid* transaction that pays a 40 BTC fee to yourself as the miner. On mainnet this class of error has destroyed real money many times. Do it once here, deliberately, in Part D.

### B4. Create, sign and broadcast

```powershell
$RAW = docker compose exec -T bitcoind bitcoin-cli -rpcwallet=lab01 createrawtransaction `
  '[{\"txid\":\"<YOUR_TXID>\",\"vout\":<YOUR_VOUT>}]' `
  '[{\"<DEST_ADDR>\":10.0},{\"<CHANGE_ADDR>\":39.9999}]'
echo $RAW
```

`createrawtransaction` performs no validation of amounts against inputs — it is a pure serialiser. It will happily build a transaction spending more than exists. Validation happens at broadcast.

Sign it:

```powershell
docker compose exec -T bitcoind bitcoin-cli -rpcwallet=lab01 signrawtransactionwithwallet $RAW
```

The response contains `hex` (the signed transaction) and `complete: true`. **Save the signed hex** — Part C needs it.

Inspect before broadcasting:

```powershell
docker compose exec -T bitcoind bitcoin-cli decoderawtransaction <SIGNED_HEX>
```

Broadcast:

```powershell
docker compose exec -T bitcoind bitcoin-cli -rpcwallet=lab01 sendrawtransaction <SIGNED_HEX>
```

The returned value is the `txid`. Confirm it:

```powershell
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 getrawmempool
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 -generate 1
docker compose exec bitcoind bitcoin-cli -rpcwallet=lab01 gettransaction <TXID>
```

**Record for your report:** the fee reported by `gettransaction`, and whether it matches your computation.

---

## Part C — Parsing the raw format

The `decoderawtransaction` RPC does the parsing for you. Now do it yourself.

```powershell
cd txparser
uv sync
uv run python -m txparser <SIGNED_HEX>
```

You can also pipe the node's output straight in:

```powershell
docker compose exec -T bitcoind bitcoin-cli getrawtransaction <TXID> | uv run python -m txparser
```

The parser prints a field-by-field breakdown with byte offsets, decodes the scripts to opcodes, recognises the standard output patterns, and recomputes both `txid` and `wtxid` from scratch.

Verify the output against `decoderawtransaction`. The `txid` your parser computes must match the one the node returned. If it does not, you have almost certainly hit the endianness trap described below.

> [!WARNING]
> **Endianness.** Transaction hashes are stored in the serialised format in **little-endian** byte order, but displayed everywhere — block explorers, RPC output, your report — in **big-endian**. The bytes are simply reversed. This single detail accounts for the majority of failed attempts at manual transaction handling. The parser handles it; look at `_read_txid` in `parser.py` to see where.

Run the test suite, which parses known-good transactions including a SegWit one:

```powershell
uv run pytest -v
```

---

## Part D — The deliberate mistake

Repeat Part B, but **omit the change output**: send 10 BTC to the destination and nothing else.

```powershell
# inputs: your 50 BTC output.  outputs: only 10 BTC to destination.
```

Sign, broadcast, mine a block, then inspect the block:

```powershell
docker compose exec bitcoind bitcoin-cli getblock <BLOCKHASH> 2
```

Look at the coinbase transaction of that block. Its value exceeds the 50 BTC subsidy — the excess is your 40 BTC fee.

**For your report:** state precisely who received the 40 BTC and why the transaction was nonetheless consensus-valid. Then explain, in one paragraph, why the account-based model of Ethereum makes this specific error impossible, referring to the state transition functions in the Week 2 chapter.

---

## `[STUDENT TASK]` — What you must implement yourself

The reference parser in `txparser/` is complete. For assessment, submit **your own implementation** in a separate repository, satisfying:

1. Parse a legacy (non-SegWit) transaction into all fields, reporting byte offsets.
2. Parse a SegWit transaction, including marker, flag and the witness stack for each input.
3. Correctly implement `CompactSize` (VarInt) decoding for all four length classes.
4. Recompute `txid` (hash of the legacy serialisation, excluding witness data) and verify it against the node.
5. Disassemble `scriptPubKey` to opcode mnemonics and classify the output type.

The reference implementation's test suite (`txparser/tests/`) is a valid specification for yours. If your implementation passes those tests, it satisfies requirements 1 to 4.

---

## Deliverables

Submit a single PDF report plus a link to your repository. The report must contain:

1. The output of `listunspent` after mining, with an explanation of why 100 of the 101 mined outputs are unspendable.
2. Your amount computation for Part B, and the fee actually reported by the node.
3. Your parser's output for the Part B transaction, alongside `decoderawtransaction` output, with a note on any field where the two representations differ (there is at least one — the hashes).
4. The Part D analysis.
5. A short section (≤ 300 words) answering: *why does Bitcoin's fee mechanism have no explicit fee field, and what does this design buy?*

---

## Grading rubric (10 points)

| Criterion | Points |
|---|---|
| Node running, wallet created, 101 blocks mined, evidence provided | 2 |
| Part B transaction constructed, broadcast and confirmed correctly | 2 |
| Own parser handles legacy transactions and recomputes txid correctly | 2 |
| Own parser handles SegWit transactions including witness stack | 2 |
| Part D performed and analysed correctly | 1 |
| Report quality: correct terminology, clear reasoning | 1 |

---

## Troubleshooting

**`Could not connect to the server`** — the daemon has not finished starting. Wait, then check `docker compose logs bitcoind`.

**`Wallet file verification failed` / wallet not found** — regtest wallets are not auto-loaded after a container restart. Run `docker compose exec bitcoind bitcoin-cli loadwallet lab01`.

**`bad-txns-in-belowout` on broadcast** — your outputs sum to more than your inputs. Recheck the arithmetic; note that `createrawtransaction` did not warn you.

**`bad-txns-premature-spend-of-coinbase`** — you are trying to spend an immature coinbase output. Use `listunspent 100` to filter to mature ones, or mine more blocks.

**`min relay fee not met`** — your fee is below the relay threshold. Increase it, or lower `minrelaytxfee` in `bitcoin.conf`.

**Parser txid does not match the node's** — byte-order error on the input hashes, or you included witness data in the txid computation. The txid is computed over the *legacy* serialisation only.

**Reset everything:**

```powershell
docker compose down -v
docker compose up -d
```

This destroys the regtest chain and starts from the genesis block. There is nothing of value to lose.
