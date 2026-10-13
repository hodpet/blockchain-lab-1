"""Byte-level Bitcoin transaction parser for Lab 01.

Public API::

    from txparser import parse_hex, parse_transaction
    from txparser.script import disassemble, classify, address_for

Everything is implemented against the raw byte stream with no Bitcoin library,
because the serialisation format is the subject of the lab.
"""

from .parser import (
    Transaction,
    TxInput,
    TxOutput,
    hash160,
    parse_hex,
    parse_transaction,
    read_compact_size,
    sha256d,
    write_compact_size,
)

__all__ = [
    "Transaction",
    "TxInput",
    "TxOutput",
    "hash160",
    "parse_hex",
    "parse_transaction",
    "read_compact_size",
    "sha256d",
    "write_compact_size",
]

__version__ = "1.0.0"
