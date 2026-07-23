from __future__ import annotations

import json
from pathlib import Path

from .config import PROJECT_ROOT


class Translator:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._fallback = self._load("en")
        self._active = self._load(language)

    def _load(self, language: str) -> dict[str, str]:
        path = PROJECT_ROOT / "assets" / "locales" / f"{language}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def set_language(self, language: str) -> None:
        self.language = language
        self._active = self._load(language)

    def t(self, key: str, **kwargs: object) -> str:
        text = self._active.get(key, self._fallback.get(key, key))
        try:
            return text.format(**kwargs)
        except Exception:
            return text
