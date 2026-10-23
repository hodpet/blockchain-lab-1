"""Command-line entry point: pretty-print a raw transaction field by field."""

from __future__ import annotations

import argparse
import sys
import requests

from .parser import Transaction, parse_hex
from .script import address_for, classify, disassemble

RULE = "-" * 78


def _fmt_sequence(seq: int) -> str:
    """Annotate the sequence field, whose meaning is entirely non-obvious."""
    if seq == 0xFFFFFFFF:
        return f"0x{seq:08x}  (final: opts out of RBF and of nLockTime)"
    if seq == 0xFFFFFFFE:
        return f"0x{seq:08x}  (nLockTime enabled, RBF disabled)"
    return f"0x{seq:08x}  (RBF signalled, BIP-125)"


def _fmt_locktime(lt: int) -> str:
    if lt == 0:
        return "0  (no timelock)"
    if lt < 500_000_000:
        return f"{lt}  (block height)"
    return f"{lt}  (Unix timestamp)"


def render(tx: Transaction, network: str) -> str:
    out: list[str] = []
    a = out.append

    a(RULE)
    a("TRANSACTION")
    a(RULE)
    a(f"  txid            : {tx.txid}")
    a(f"  wtxid           : {tx.wtxid}")
    a(f"  version         : {tx.version}")
    a(f"  segwit          : {tx.is_segwit}")
    a(f"  locktime        : {_fmt_locktime(tx.locktime)}")
    a(f"  size            : {tx.size} bytes")
    a(f"  stripped size   : {tx.stripped_size} bytes  (witness excluded)")
    a(f"  weight          : {tx.weight} WU")
    a(f"  virtual size    : {tx.vsize} vbytes  (fee rates are quoted per vbyte)")
    a("")

    if tx.txid == tx.wtxid and tx.is_segwit:
        a("  NOTE: txid == wtxid on a segwit transaction means no input carried")
        a("        witness data (all inputs are legacy).")
        a("")

    a(RULE)
    a(f"INPUTS ({len(tx.inputs)})")
    a(RULE)
    for idx, i in enumerate(tx.inputs):
        a(f"  [{idx}] byte offset {i.offset}")
        if i.is_coinbase:
            a("      COINBASE input (null outpoint)")
            a(f"      coinbase data : {i.script_sig.hex()}")
        else:
            a(f"      prev txid     : {i.prev_txid.hex()}")
            a(f"      prev vout     : {i.prev_vout}")
            a(f"      scriptSig     : {len(i.script_sig)} bytes")
            if i.script_sig:
                for token in disassemble(i.script_sig):
                    a(f"                      {token}")
        a(f"      sequence      : {_fmt_sequence(i.sequence)}")
        if i.witness:
            a(f"      witness       : {len(i.witness)} stack item(s)")
            for j, item in enumerate(i.witness):
                a(f"        [{j}] ({len(item)} B) {item.hex()}")
        elif tx.is_segwit:
            a("      witness       : empty stack")
        a("")

    a(RULE)
    a(f"OUTPUTS ({len(tx.outputs)})")
    a(RULE)
    for idx, o in enumerate(tx.outputs):
        stype, payload = classify(o.script_pubkey)
        addr = address_for(stype, payload, network)
        a(f"  [{idx}] byte offset {o.offset}")
        a(f"      value         : {o.value_btc} BTC  ({o.value_sat} sat)")
        a(f"      type          : {stype}")
        if addr:
            a(f"      address       : {addr}   [{network}]")
        a(f"      scriptPubKey  : {len(o.script_pubkey)} bytes")
        for token in disassemble(o.script_pubkey):
            a(f"                      {token}")
        a("")

    a(RULE)
    a("TOTALS")
    a(RULE)
    a(f"  sum of outputs  : {tx.total_output_sat} sat")
    a("")
    a("  The FEE is not a field in this structure. It is")
    a("      sum(inputs) - sum(outputs)")
    a("  and the input values live in the outputs being spent, which are not")
    a("  part of this transaction. To compute the fee you must look up each")
    a("  previous output -- for example with:")
    a("      bitcoin-cli gettxout <prev_txid> <prev_vout>")
    a(RULE)

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="txparser",
        description="Parse a raw Bitcoin transaction byte by byte.",
    )
    p.add_argument(
        "hex",
        nargs="?",
        help="raw transaction as hex; omit to read from stdin",
    )
    p.add_argument(
        "-n",
        "--network",
        default="regtest",
        choices=["mainnet", "testnet", "regtest"],
        help="network used for address encoding (default: regtest)",
    )
    p.add_argument(
        "--rpc",
        type=str,
        help="Bitcoin RPC URL (e.g., http://lab:lab@127.0.0.1:18443)"
    )
    args = p.parse_args(argv)

    raw_hex = args.hex if args.hex else sys.stdin.read()
    if not raw_hex.strip():
        p.error("no input; pass a hex string or pipe one on stdin")

    try:
        tx = parse_hex(raw_hex)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(render(tx, args.network))

    # --- BONUS E1 LOGIC ---
    if args.rpc:
        total_input_sats = 0
        
        for i in tx.inputs:
            if i.is_coinbase:
                continue # Coinbase transactions don't spend previous outputs
                
            prev_txid = i.prev_txid.hex()
            prev_vout = i.prev_vout
            
            payload = {
                "jsonrpc": "1.0",
                "id": "txparser",
                "method": "getrawtransaction",
                "params": [prev_txid, True]
            }
            
            try:
                response = requests.post(args.rpc, json=payload)
                rpc_data = response.json()
                
                if "result" in rpc_data and rpc_data["result"]:
                    for vout in rpc_data["result"]["vout"]:
                        if vout["n"] == prev_vout:
                            total_input_sats += int(vout["value"] * 100_000_000)
                            break
            except Exception as e:
                print(f"RPC connection failed: {e}", file=sys.stderr)
                return 1

        fee_sats = total_input_sats - tx.total_output_sat
        fee_rate = fee_sats / tx.vsize
        
        print("-" * 78)
        print(f"fee {fee_sats} sat")
        print(f"{fee_rate:.1f} sat/vB")
        print("-" * 78)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
