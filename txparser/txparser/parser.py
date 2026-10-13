"""Byte-level parser for raw Bitcoin transactions.

The whole point of this module is that it uses no Bitcoin library. Every field is
read from the byte stream by hand, so that the serialisation format becomes
concrete rather than a diagram in a specification.

Reference: the transaction serialisation in Bitcoin Core's `primitives/transaction.h`
and BIP-141 for the SegWit marker/flag and witness section.

Serialisation layout
--------------------

    version        4 bytes, little-endian
    [marker=0x00]  1 byte, SegWit only
    [flag=0x01]    1 byte, SegWit only
    input count    CompactSize
    inputs         input count x TxInput
    output count   CompactSize
    outputs        output count x TxOutput
    [witnesses]    SegWit only: one stack per input
    locktime       4 bytes, little-endian

    TxInput:  prev txid (32 bytes, LE) | prev vout (4 bytes, LE)
              | scriptSig (CompactSize length + bytes) | sequence (4 bytes, LE)
    TxOutput: value in satoshi (8 bytes, LE) | scriptPubKey (CompactSize + bytes)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ._ripemd160 import ripemd160 as _pure_ripemd160

# --------------------------------------------------------------------------- #
# Hashing helpers
# --------------------------------------------------------------------------- #


def sha256d(data: bytes) -> bytes:
    """Double SHA-256, as used everywhere in Bitcoin.

    Applied twice to defend against length-extension attacks on the
    Merkle-Damgard construction. See Week 4 of the theory notes.
    """
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _ripemd160(data: bytes) -> bytes:
    """RIPEMD-160 via OpenSSL when available, else the bundled implementation.

    OpenSSL 3 disables RIPEMD-160 by default (it lives in the legacy provider),
    so `hashlib.new("ripemd160")` raises on many modern systems. Bitcoin needs
    it for HASH160, so we fall back rather than fail.
    """
    try:
        return hashlib.new("ripemd160", data).digest()
    except (ValueError, TypeError):
        return _pure_ripemd160(data)


def hash160(data: bytes) -> bytes:
    """RIPEMD-160(SHA-256(x)), used for address derivation."""
    return _ripemd160(hashlib.sha256(data).digest())


# --------------------------------------------------------------------------- #
# CompactSize (VarInt)
# --------------------------------------------------------------------------- #


def read_compact_size(data: bytes, offset: int) -> tuple[int, int]:
    """Read a CompactSize integer. Returns (value, bytes_consumed).

    Four length classes:
        0x00..0xfc  -> the byte itself
        0xfd        -> next 2 bytes, little-endian
        0xfe        -> next 4 bytes, little-endian
        0xff        -> next 8 bytes, little-endian
    """
    first = data[offset]
    if first < 0xFD:
        return first, 1
    if first == 0xFD:
        return int.from_bytes(data[offset + 1 : offset + 3], "little"), 3
    if first == 0xFE:
        return int.from_bytes(data[offset + 1 : offset + 5], "little"), 5
    return int.from_bytes(data[offset + 1 : offset + 9], "little"), 9


def write_compact_size(value: int) -> bytes:
    """Inverse of read_compact_size, needed to re-serialise for txid computation."""
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    return b"\xff" + value.to_bytes(8, "little")


# --------------------------------------------------------------------------- #
# Cursor
# --------------------------------------------------------------------------- #


class Reader:
    """A cursor over a byte string that records where each field started.

    Tracking offsets is not decorative: reporting the byte offset of every field
    is a lab deliverable, and it is what turns 'the parser works' into
    'I can point at the bytes'.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, n: int) -> bytes:
        if self.remaining() < n:
            raise ValueError(
                f"truncated transaction: wanted {n} bytes at offset {self.pos}, "
                f"only {self.remaining()} remain"
            )
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def peek(self, n: int) -> bytes:
        return self.data[self.pos : self.pos + n]

    def u32le(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def u64le(self) -> int:
        return int.from_bytes(self.take(8), "little")

    def compact_size(self) -> int:
        value, consumed = read_compact_size(self.data, self.pos)
        self.pos += consumed
        return value

    def var_bytes(self) -> bytes:
        """CompactSize length prefix followed by that many bytes."""
        return self.take(self.compact_size())

    def txid_be(self) -> bytes:
        """Read a 32-byte hash stored little-endian, return it big-endian.

        THIS is the endianness trap. Hashes are serialised in little-endian byte
        order but displayed reversed everywhere: block explorers, RPC output,
        your report. Getting this wrong is the single most common reason a
        hand-written parser disagrees with `decoderawtransaction`.
        """
        return self.take(32)[::-1]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class TxInput:
    offset: int
    prev_txid: bytes  # big-endian, display order
    prev_vout: int
    script_sig: bytes
    sequence: int
    witness: list[bytes] = field(default_factory=list)

    @property
    def is_coinbase(self) -> bool:
        # A coinbase input references the null outpoint: all-zero hash, vout 0xffffffff.
        return self.prev_txid == b"\x00" * 32 and self.prev_vout == 0xFFFFFFFF

    def serialise(self) -> bytes:
        return (
            self.prev_txid[::-1]
            + self.prev_vout.to_bytes(4, "little")
            + write_compact_size(len(self.script_sig))
            + self.script_sig
            + self.sequence.to_bytes(4, "little")
        )


@dataclass
class TxOutput:
    offset: int
    value_sat: int
    script_pubkey: bytes

    @property
    def value_btc(self) -> str:
        # Rendered as a decimal string rather than a float: 1 BTC = 10^8 satoshi,
        # and binary floating point cannot represent satoshi amounts exactly.
        whole, frac = divmod(self.value_sat, 100_000_000)
        return f"{whole}.{frac:08d}"

    def serialise(self) -> bytes:
        return (
            self.value_sat.to_bytes(8, "little")
            + write_compact_size(len(self.script_pubkey))
            + self.script_pubkey
        )


@dataclass
class Transaction:
    version: int
    is_segwit: bool
    inputs: list[TxInput]
    outputs: list[TxOutput]
    locktime: int
    raw: bytes

    # ---- serialisation ---------------------------------------------------- #

    def serialise(self, include_witness: bool) -> bytes:
        out = self.version.to_bytes(4, "little")
        if include_witness and self.is_segwit:
            out += b"\x00\x01"
        out += write_compact_size(len(self.inputs))
        for i in self.inputs:
            out += i.serialise()
        out += write_compact_size(len(self.outputs))
        for o in self.outputs:
            out += o.serialise()
        if include_witness and self.is_segwit:
            for i in self.inputs:
                out += write_compact_size(len(i.witness))
                for item in i.witness:
                    out += write_compact_size(len(item)) + item
        out += self.locktime.to_bytes(4, "little")
        return out

    # ---- identifiers ------------------------------------------------------ #

    @property
    def txid(self) -> str:
        """The transaction identifier: sha256d of the LEGACY serialisation.

        Witness data is excluded. This is precisely what SegWit fixed: because
        signatures no longer contribute to the txid, a third party can no longer
        change the identifier of a valid transaction by re-encoding its
        signature (transaction malleability). See Week 2 and Week 4.
        """
        return sha256d(self.serialise(include_witness=False))[::-1].hex()

    @property
    def wtxid(self) -> str:
        """The witness transaction identifier: sha256d of the FULL serialisation.

        Equal to the txid for non-SegWit transactions.
        """
        return sha256d(self.serialise(include_witness=True))[::-1].hex()

    # ---- derived sizes ---------------------------------------------------- #

    @property
    def size(self) -> int:
        """Total serialised size in bytes."""
        return len(self.raw)

    @property
    def stripped_size(self) -> int:
        """Size excluding witness data."""
        return len(self.serialise(include_witness=False))

    @property
    def weight(self) -> int:
        """BIP-141 weight: witness bytes count a quarter as much as base bytes.

            weight = base_size * 3 + total_size

        This discount is what allowed SegWit to raise effective capacity
        without changing the 1 MB block-size limit.
        """
        return self.stripped_size * 3 + self.size

    @property
    def vsize(self) -> int:
        """Virtual size: weight / 4, rounded up. Fee rates are quoted per vbyte."""
        return (self.weight + 3) // 4

    @property
    def total_output_sat(self) -> int:
        return sum(o.value_sat for o in self.outputs)


# --------------------------------------------------------------------------- #
# The parser
# --------------------------------------------------------------------------- #


def parse_transaction(raw: bytes) -> Transaction:
    """Parse a raw transaction. Raises ValueError on malformed input."""
    r = Reader(raw)

    version = r.u32le()

    # SegWit detection (BIP-144). After the version, a SegWit transaction has
    # marker 0x00 followed by flag 0x01. A legacy transaction cannot begin its
    # input count with 0x00, because a transaction with zero inputs is invalid.
    is_segwit = r.peek(2) == b"\x00\x01"
    if is_segwit:
        r.take(2)

    inputs: list[TxInput] = []
    for _ in range(r.compact_size()):
        offset = r.pos
        inputs.append(
            TxInput(
                offset=offset,
                prev_txid=r.txid_be(),
                prev_vout=r.u32le(),
                script_sig=r.var_bytes(),
                sequence=r.u32le(),
            )
        )

    outputs: list[TxOutput] = []
    for _ in range(r.compact_size()):
        offset = r.pos
        outputs.append(
            TxOutput(offset=offset, value_sat=r.u64le(), script_pubkey=r.var_bytes())
        )

    if is_segwit:
        # One witness stack per input, in input order. An input with no witness
        # (a legacy input inside a SegWit transaction) has a stack of zero items.
        for txin in inputs:
            txin.witness = [r.var_bytes() for _ in range(r.compact_size())]

    locktime = r.u32le()

    if r.remaining() != 0:
        raise ValueError(f"{r.remaining()} trailing bytes after locktime")

    return Transaction(
        version=version,
        is_segwit=is_segwit,
        inputs=inputs,
        outputs=outputs,
        locktime=locktime,
        raw=raw,
    )


def parse_hex(hex_str: str) -> Transaction:
    """Convenience wrapper accepting a hex string, with or without whitespace."""
    cleaned = "".join(hex_str.split())
    if cleaned.startswith(("0x", "0X")):
        cleaned = cleaned[2:]
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"input is not valid hexadecimal: {exc}") from exc
    if not raw:
        raise ValueError("empty input")
    return parse_transaction(raw)
