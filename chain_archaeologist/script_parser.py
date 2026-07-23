from __future__ import annotations

from dataclasses import dataclass

OP_0 = 0x00
OP_FALSE = 0x00
OP_IF = 0x63
OP_ENDIF = 0x68
OP_RETURN = 0x6A
OP_PUSHDATA1 = 0x4C
OP_PUSHDATA2 = 0x4D
OP_PUSHDATA4 = 0x4E


@dataclass(frozen=True)
class ScriptToken:
    opcode: int
    data: bytes | None = None


def parse_script(script: bytes) -> list[ScriptToken]:
    tokens: list[ScriptToken] = []
    i = 0
    length = len(script)
    while i < length:
        opcode = script[i]
        i += 1
        if opcode == OP_0:
            tokens.append(ScriptToken(opcode, b""))
            continue
        if 1 <= opcode <= 75:
            if i + opcode > length:
                break
            tokens.append(ScriptToken(opcode, script[i:i + opcode]))
            i += opcode
            continue
        if opcode == OP_PUSHDATA1:
            if i + 1 > length:
                break
            size = script[i]
            i += 1
        elif opcode == OP_PUSHDATA2:
            if i + 2 > length:
                break
            size = int.from_bytes(script[i:i + 2], "little")
            i += 2
        elif opcode == OP_PUSHDATA4:
            if i + 4 > length:
                break
            size = int.from_bytes(script[i:i + 4], "little")
            i += 4
        else:
            tokens.append(ScriptToken(opcode, None))
            continue
        if i + size > length:
            break
        tokens.append(ScriptToken(opcode, script[i:i + size]))
        i += size
    return tokens


def data_pushes(script: bytes) -> list[bytes]:
    return [t.data for t in parse_script(script) if t.data is not None and len(t.data) > 0]


def op_return_payloads(script: bytes) -> list[bytes]:
    tokens = parse_script(script)
    for idx, token in enumerate(tokens):
        if token.opcode == OP_RETURN and token.data is None:
            return [t.data for t in tokens[idx + 1:] if t.data is not None]
    return []


@dataclass(frozen=True)
class OrdinalEnvelope:
    content_type: str | None
    body: bytes


def ordinal_envelopes(script: bytes) -> list[OrdinalEnvelope]:
    """Extract common ord-style envelopes from a tapscript witness item.

    This parser is deliberately conservative and does not execute script.
    """
    tokens = parse_script(script)
    found: list[OrdinalEnvelope] = []
    i = 0
    while i + 2 < len(tokens):
        if (
            tokens[i].data == b""
            and tokens[i + 1].opcode == OP_IF
            and tokens[i + 2].data == b"ord"
        ):
            i += 3
            content_type: str | None = None
            body_parts: list[bytes] = []
            in_body = False
            while i < len(tokens):
                token = tokens[i]
                if token.opcode == OP_ENDIF and token.data is None:
                    break
                if token.data == b"":
                    in_body = True
                    i += 1
                    continue
                if token.data is None:
                    i += 1
                    continue
                if in_body:
                    body_parts.append(token.data)
                else:
                    # Common envelope field: tag 0x01 followed by MIME type.
                    if token.data == b"\x01" and i + 1 < len(tokens) and tokens[i + 1].data is not None:
                        try:
                            content_type = tokens[i + 1].data.decode("utf-8", errors="strict")
                        except UnicodeDecodeError:
                            content_type = None
                        i += 1
                i += 1
            body = b"".join(body_parts)
            if body:
                found.append(OrdinalEnvelope(content_type, body))
        i += 1
    return found
