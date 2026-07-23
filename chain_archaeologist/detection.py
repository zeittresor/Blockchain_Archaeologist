from __future__ import annotations

import json
import math
import mimetypes
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    detected_type: str
    extension: str
    mime: str
    confidence: float
    magic_offset: int
    preview_text: str | None = None


MAGIC: list[tuple[bytes, str, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "PNG image", ".png", "image/png"),
    (b"\xff\xd8\xff", "JPEG image", ".jpg", "image/jpeg"),
    (b"GIF87a", "GIF image", ".gif", "image/gif"),
    (b"GIF89a", "GIF image", ".gif", "image/gif"),
    (b"BM", "BMP image", ".bmp", "image/bmp"),
    (b"II*\x00", "TIFF image", ".tif", "image/tiff"),
    (b"MM\x00*", "TIFF image", ".tif", "image/tiff"),
    (b"%PDF-", "PDF document", ".pdf", "application/pdf"),
    (b"PK\x03\x04", "ZIP archive", ".zip", "application/zip"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive", ".7z", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "RAR archive", ".rar", "application/vnd.rar"),
    (b"\x1f\x8b\x08", "GZIP stream", ".gz", "application/gzip"),
    (b"OggS", "Ogg media", ".ogg", "application/ogg"),
    (b"fLaC", "FLAC audio", ".flac", "audio/flac"),
    (b"RIFF", "RIFF container", ".riff", "application/octet-stream"),
    (b"ID3", "MP3 audio", ".mp3", "audio/mpeg"),
    (b"MZ", "Windows executable", ".exe", "application/vnd.microsoft.portable-executable"),
    (b"\x7fELF", "ELF executable", ".elf", "application/x-elf"),
    (b"\x00asm", "WebAssembly module", ".wasm", "application/wasm"),
    (b"SQLite format 3\x00", "SQLite database", ".sqlite", "application/vnd.sqlite3"),
]

SOURCE_PATTERNS = [
    (re.compile(r"^\s*(?:#!.*\n)?\s*(?:from\s+\w+\s+import|import\s+\w+|def\s+\w+\s*\(|class\s+\w+\s*[:(])", re.S), "Python source", ".py", "text/x-python"),
    (re.compile(r"^\s*(?:#include\s*[<\"]|int\s+main\s*\()", re.S), "C/C++ source", ".c", "text/x-c"),
    (re.compile(r"^\s*(?:#!/bin/(?:ba)?sh|set\s+-[eux]|function\s+\w+)", re.S), "Shell script", ".sh", "text/x-shellscript"),
]


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _text_detection(payload: bytes, preview_limit: int) -> Detection | None:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text) / len(text)
    if printable < 0.92:
        return None
    stripped = text.lstrip("\ufeff \r\n\t")
    preview = text[:preview_limit]
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return Detection("JSON document", ".json", "application/json", 0.99, 0, preview)
        except Exception:
            pass
    if stripped.startswith("<?xml") or (stripped.startswith("<") and stripped.endswith(">")):
        if stripped.lower().startswith(("<!doctype html", "<html")):
            return Detection("HTML document", ".html", "text/html", 0.96, 0, preview)
        return Detection("XML/text markup", ".xml", "application/xml", 0.90, 0, preview)
    for pattern, kind, ext, mime in SOURCE_PATTERNS:
        if pattern.search(text):
            return Detection(kind, ext, mime, 0.92, 0, preview)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) >= 2 and all("," in line for line in lines[:10]):
        return Detection("CSV-like text", ".csv", "text/csv", 0.82, 0, preview)
    return Detection("UTF-8 text", ".txt", "text/plain", min(0.98, 0.80 + printable * 0.18), 0, preview)


def detect_payload(payload: bytes, declared_mime: str | None = None, preview_limit: int = 65536) -> Detection:
    normalized_mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    if normalized_mime:
        ext = mimetypes.guess_extension(normalized_mime) or ".bin"
        preview = None
        if normalized_mime.startswith("text/") or normalized_mime in {"application/json", "application/xml"}:
            try:
                preview = payload[:preview_limit].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                preview = None
        return Detection(f"Declared {normalized_mime}", ext, normalized_mime, 1.0, 0, preview)

    # Strict high-confidence signatures at offset zero.
    for signature, kind, ext, mime in MAGIC:
        if payload.startswith(signature):
            if signature == b"RIFF" and len(payload) >= 12:
                subtype = payload[8:12]
                if subtype == b"WAVE":
                    return Detection("WAV audio", ".wav", "audio/wav", 0.99, 0)
                if subtype == b"WEBP":
                    return Detection("WebP image", ".webp", "image/webp", 0.99, 0)
                if subtype == b"AVI ":
                    return Detection("AVI video", ".avi", "video/x-msvideo", 0.99, 0)
            return Detection(kind, ext, mime, 0.99, 0)

    # TAR's ustar signature is not at offset zero.
    if len(payload) > 262 and payload[257:262] == b"ustar":
        return Detection("TAR archive", ".tar", "application/x-tar", 0.98, 257)

    # MP3 frame sync without ID3.
    if len(payload) >= 2 and payload[0] == 0xFF and (payload[1] & 0xE0) == 0xE0:
        return Detection("MP3-like audio frame", ".mp3", "audio/mpeg", 0.90, 0)

    text = _text_detection(payload, preview_limit)
    if text:
        return text

    # A signature shortly after a small protocol prefix is useful for cataloging,
    # but not considered safe for automatic bulk extraction.
    prefix_window = payload[:128]
    for signature, kind, ext, mime in MAGIC:
        offset = prefix_window.find(signature)
        if offset > 0:
            return Detection(f"{kind} after prefix", ext, mime, 0.72, offset)

    return Detection("Unknown binary", ".bin", "application/octet-stream", 0.0, -1)
