"""Bitcoin Script disassembly, output classification and address encoding.

Script is a stack-based, postfix, loop-free language. Because it has no loops,
every script terminates in at most as many steps as it has instructions, which
is why Bitcoin needs no gas metering (see Week 2 of the theory notes).

This module does three things:

  * disassemble raw script bytes into opcode mnemonics
  * recognise the handful of standard output patterns
  * encode the corresponding address (Base58Check or Bech32/Bech32m)
"""

from __future__ import annotations

from .parser import hash160, sha256d  # noqa: F401  (hash160 re-exported for tests)

# --------------------------------------------------------------------------- #
# Opcodes
# --------------------------------------------------------------------------- #

OPCODES: dict[int, str] = {
    0x00: "OP_0",
    0x4C: "OP_PUSHDATA1",
    0x4D: "OP_PUSHDATA2",
    0x4E: "OP_PUSHDATA4",
    0x4F: "OP_1NEGATE",
    0x61: "OP_NOP",
    0x63: "OP_IF",
    0x64: "OP_NOTIF",
    0x67: "OP_ELSE",
    0x68: "OP_ENDIF",
    0x69: "OP_VERIFY",
    0x6A: "OP_RETURN",
    0x6D: "OP_2DROP",
    0x6E: "OP_2DUP",
    0x75: "OP_DROP",
    0x76: "OP_DUP",
    0x77: "OP_NIP",
    0x78: "OP_OVER",
    0x7C: "OP_SWAP",
    0x82: "OP_SIZE",
    0x87: "OP_EQUAL",
    0x88: "OP_EQUALVERIFY",
    0x8B: "OP_1ADD",
    0x8C: "OP_1SUB",
    0x93: "OP_ADD",
    0x94: "OP_SUB",
    0x9A: "OP_BOOLAND",
    0x9B: "OP_BOOLOR",
    0x9C: "OP_NUMEQUAL",
    0x9D: "OP_NUMEQUALVERIFY",
    0xA6: "OP_RIPEMD160",
    0xA7: "OP_SHA1",
    0xA8: "OP_SHA256",
    0xA9: "OP_HASH160",
    0xAA: "OP_HASH256",
    0xAB: "OP_CODESEPARATOR",
    0xAC: "OP_CHECKSIG",
    0xAD: "OP_CHECKSIGVERIFY",
    0xAE: "OP_CHECKMULTISIG",
    0xAF: "OP_CHECKMULTISIGVERIFY",
    0xB1: "OP_CHECKLOCKTIMEVERIFY",
    0xB2: "OP_CHECKSEQUENCEVERIFY",
}

# OP_1 .. OP_16 push the numbers 1..16 onto the stack.
for _n in range(1, 17):
    OPCODES[0x50 + _n] = f"OP_{_n}"


def disassemble(script: bytes) -> list[str]:
    """Render script bytes as a list of tokens.

    Data pushes are rendered as <hex> so that the distinction between an opcode
    and pushed data stays visible, which is exactly the distinction a reader of
    raw hex loses.
    """
    tokens: list[str] = []
    i = 0
    n = len(script)
    while i < n:
        op = script[i]
        i += 1

        # 0x01..0x4b: the opcode value IS the number of bytes to push.
        if 0x01 <= op <= 0x4B:
            data = script[i : i + op]
            i += op
            tokens.append(f"<{data.hex()}>")
            continue

        if op in (0x4C, 0x4D, 0x4E):
            width = {0x4C: 1, 0x4D: 2, 0x4E: 4}[op]
            if i + width > n:
                tokens.append("<TRUNCATED PUSHDATA>")
                break
            length = int.from_bytes(script[i : i + width], "little")
            i += width
            data = script[i : i + length]
            i += length
            tokens.append(f"{OPCODES[op]} <{data.hex()}>")
            continue

        tokens.append(OPCODES.get(op, f"OP_UNKNOWN_{op:02x}"))

    return tokens


# --------------------------------------------------------------------------- #
# Output classification
# --------------------------------------------------------------------------- #


def classify(script: bytes) -> tuple[str, bytes | None]:
    """Recognise a standard output pattern.

    Returns (type_name, payload) where payload is the hash or key the address
    is derived from, or None if the type carries no address.
    """
    n = len(script)

    # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    if (
        n == 25
        and script[0] == 0x76
        and script[1] == 0xA9
        and script[2] == 0x14
        and script[23] == 0x88
        and script[24] == 0xAC
    ):
        return "p2pkh", script[3:23]

    # P2SH: OP_HASH160 <20 bytes> OP_EQUAL
    if n == 23 and script[0] == 0xA9 and script[1] == 0x14 and script[22] == 0x87:
        return "p2sh", script[2:22]

    # P2WPKH: OP_0 <20 bytes>
    if n == 22 and script[0] == 0x00 and script[1] == 0x14:
        return "p2wpkh", script[2:22]

    # P2WSH: OP_0 <32 bytes>
    if n == 34 and script[0] == 0x00 and script[1] == 0x20:
        return "p2wsh", script[2:34]

    # P2TR: OP_1 <32 bytes>  (BIP-341 Taproot)
    if n == 34 and script[0] == 0x51 and script[1] == 0x20:
        return "p2tr", script[2:34]

    # P2PK: <33 or 65 byte pubkey> OP_CHECKSIG. The archaic form used by early
    # coinbase outputs, and the one most exposed to a future quantum adversary
    # because the public key is on-chain before spending (see Week 4).
    if n in (35, 67) and script[-1] == 0xAC and script[0] in (33, 65):
        return "p2pk", script[1:-1]

    # OP_RETURN: provably unspendable, used to embed data.
    if n >= 1 and script[0] == 0x6A:
        return "nulldata", None

    # Bare multisig: OP_M <pubkey>... OP_N OP_CHECKMULTISIG
    if n >= 3 and script[-1] == 0xAE and 0x51 <= script[0] <= 0x60:
        return "multisig", None

    return "nonstandard", None


# --------------------------------------------------------------------------- #
# Address encoding
# --------------------------------------------------------------------------- #

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Version bytes and human-readable parts per network.
NETWORKS = {
    "mainnet": {"p2pkh": 0x00, "p2sh": 0x05, "hrp": "bc"},
    "testnet": {"p2pkh": 0x6F, "p2sh": 0xC4, "hrp": "tb"},
    "regtest": {"p2pkh": 0x6F, "p2sh": 0xC4, "hrp": "bcrt"},
}


def base58check(payload: bytes) -> str:
    """Base58 with a 4-byte double-SHA256 checksum appended.

    The alphabet omits 0, O, I and l because they are visually confusable, and
    omits + and / so that an address can be selected by double-click.
    """
    full = payload + sha256d(payload)[:4]

    num = int.from_bytes(full, "big")
    out = ""
    while num > 0:
        num, rem = divmod(num, 58)
        out = _B58_ALPHABET[rem] + out

    # Each leading zero byte becomes a leading '1'; the integer conversion above
    # would otherwise discard them.
    for byte in full:
        if byte != 0:
            break
        out = "1" + out

    return out


_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data: bytes, frombits: int, tobits: int) -> list[int]:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def bech32_encode(hrp: str, witver: int, witprog: bytes) -> str:
    """Encode a SegWit address (BIP-173 for v0, BIP-350 Bech32m for v1+).

    Bech32 uses a BCH code rather than a truncated hash, so it detects up to
    four character errors with certainty and can indicate their position --
    materially stronger than Base58Check's 4-byte checksum.
    """
    const = _BECH32_CONST if witver == 0 else _BECH32M_CONST
    data = [witver] + _convertbits(witprog, 8, 5)
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ const
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in data + checksum)


def address_for(script_type: str, payload: bytes | None, network: str = "regtest") -> str | None:
    """Derive the address for a classified output, or None if it has none."""
    if payload is None:
        return None
    params = NETWORKS[network]

    if script_type == "p2pkh":
        return base58check(bytes([params["p2pkh"]]) + payload)
    if script_type == "p2sh":
        return base58check(bytes([params["p2sh"]]) + payload)
    if script_type in ("p2wpkh", "p2wsh"):
        return bech32_encode(params["hrp"], 0, payload)
    if script_type == "p2tr":
        return bech32_encode(params["hrp"], 1, payload)
    if script_type == "p2pk":
        # P2PK has no address of its own; show the address of the equivalent P2PKH
        # so the output is still identifiable.
        return base58check(bytes([params["p2pkh"]]) + hash160(payload))
    return None
