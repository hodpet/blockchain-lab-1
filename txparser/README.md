# txparser — byte-level Bitcoin transaction parser

Reference implementation for **Lab 01, Part C**. Parses a raw Bitcoin transaction
from its hexadecimal serialisation, using nothing but the Python standard library.

No Bitcoin library is used on purpose: pulling one in would hide exactly the
details the lab exists to teach.

## Usage

```bash
uv sync
uv run python -m txparser <RAW_TX_HEX>
```

Read from stdin instead:

```bash
docker compose exec -T bitcoind bitcoin-cli -rpcwallet=lab01 \
  getrawtransaction <TXID> | uv run python -m txparser
```

Address encoding follows the regtest network by default. Override with
`--network mainnet` or `--network testnet`.

## What it reports

- every field with its **byte offset** in the stream
- `txid` and `wtxid`, both recomputed from the bytes rather than read from anywhere
- size, stripped size, weight and virtual size (BIP-141 witness discount)
- scriptSig and scriptPubKey disassembled into opcode mnemonics
- output type classification (P2PKH, P2SH, P2WPKH, P2WSH, P2TR, P2PK, nulldata, multisig)
  and the corresponding address
- the witness stack for each input on SegWit transactions

## Tests

```bash
uv run pytest -v
```

The fixtures are the genesis coinbase transaction and the first ever
person-to-person Bitcoin payment (block 170), so the expected identifiers can be
checked against any block explorer. A synthetic SegWit transaction is built
inside the test file so that every byte of it is accounted for.

These tests are the specification for the `[STUDENT TASK]` implementation.

## Module layout

| File | Responsibility |
|---|---|
| `txparser/parser.py` | CompactSize, the byte cursor, the data model, txid/wtxid |
| `txparser/script.py` | opcode disassembly, output classification, Base58Check and Bech32/Bech32m |
| `txparser/_ripemd160.py` | pure-Python RIPEMD-160 fallback (OpenSSL 3 disables it by default) |
| `txparser/cli.py` | argument parsing and the field-by-field report |
| `txparser/__main__.py` | entry point for `python -m txparser` |

## A note on the project layout

`pyproject.toml` sets `[tool.uv] package = false` and lets pytest find the code
through `pythonpath`, rather than installing the project as an editable package.

This is deliberate. An editable install writes an absolute path into a `.pth`
file, and on Windows those files are read using the system code page rather than
UTF-8. Because this repository lives under a directory with an accented
character (`Óbuda`), an editable install produces a mangled path and the package
fails to import with a confusing `ModuleNotFoundError`. Every Python lab in this
course uses the same flat layout for that reason.
