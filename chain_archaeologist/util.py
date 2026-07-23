from __future__ import annotations

import math
import os
import time
from collections import deque
from pathlib import Path


def human_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while abs(value) >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.2f} {units[idx]}"


def human_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "—"
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


class RateEstimator:
    """Rolling linear rate/ETA estimator with basic outlier resistance."""

    def __init__(self, max_samples: int = 20) -> None:
        self.samples: deque[tuple[float, float]] = deque(maxlen=max_samples)

    def reset(self) -> None:
        self.samples.clear()

    def add(self, value: float, timestamp: float | None = None) -> None:
        self.samples.append((timestamp if timestamp is not None else time.monotonic(), value))

    def rate(self) -> float | None:
        if len(self.samples) < 2:
            return None
        rates: list[float] = []
        for (t1, v1), (t2, v2) in zip(self.samples, list(self.samples)[1:]):
            dt = t2 - t1
            dv = v2 - v1
            if dt > 0 and dv >= 0:
                rates.append(dv / dt)
        if not rates:
            return None
        rates.sort()
        return rates[len(rates) // 2]

    def eta(self, current: float, total: float) -> float | None:
        rate = self.rate()
        if rate is None or rate <= 0 or total <= current:
            return 0.0 if total <= current else None
        return (total - current) / rate
