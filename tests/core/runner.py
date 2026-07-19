from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

# How often to log a "still waiting" progress line during a poll_until call,
# regardless of its own retry/delay settings -- long polls (e.g. waiting up
# to ~60 minutes for a bare-metal cluster to become Ready) would otherwise
# print nothing until they finish or time out.
_PROGRESS_LOG_INTERVAL_S = 30


def run(*args: str, timeout: int = 300) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout.strip()


def run_unchecked(*args: str, timeout: int = 300) -> tuple[str, int]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    combined = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
    return combined, result.returncode


def poll_until(
    *, fn: Callable[[], T], until: Callable[[T], bool], retries: int = 60, delay: int = 5, description: str
) -> T:
    value: T | None = None
    start = time.monotonic()
    last_logged = start
    logger.info("Waiting for %s...", description)
    for attempt in range(retries):
        value = fn()
        if until(value):
            logger.info("%s — done after %.0fs", description, time.monotonic() - start)
            return value
        now = time.monotonic()
        if now - last_logged >= _PROGRESS_LOG_INTERVAL_S:
            logger.info(
                "Still waiting for %s (attempt %d/%d, %.0fs elapsed, last value: %r)",
                description, attempt + 1, retries, now - start, value,
            )
            last_logged = now
        time.sleep(delay)
    raise TimeoutError(f"{description} — timeout after {retries * delay}s, last value: {value!r}")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        msg = f"Required environment variable {name} is not set"
        raise RuntimeError(msg)
    return value
