"""Shared retry-with-backoff helper for this project's HTTP-based
sources. sources/onchain.py's own _rpc already had this exact pattern
(3 attempts, linear 2s/4s backoff) for its POST-based JSON-RPC calls;
extracted here so binance.py/technical.py/sentiment.py/news.py don't
each reimplement it slightly differently -- before this, a single
transient network hiccup (timeout, 5xx) lost that source's data for the
whole 15-minute cycle instead of being retried the same way onchain.py's
RPC calls already were. observe.py already treats a source failure as
non-fatal (falls back to the last stored value, or skips), so this isn't
about crash-safety -- it's about not needlessly losing a cycle's data to
something a second try would likely have fixed."""

from __future__ import annotations

import time
from typing import Callable

import requests

DEFAULT_RETRIES = 3
_BACKOFF_BASE_S = 2  # linear backoff: 2s, 4s, ... matching onchain.py's own _rpc


def get_with_retries(fn: Callable[[], requests.Response], *, retries: int = DEFAULT_RETRIES) -> requests.Response:
    """Call `fn` (expected to perform one requests.get(...) and either
    have already called raise_for_status() or return a Response the
    caller still needs to check) up to `retries` times total, with linear
    backoff between attempts, retrying only on requests.RequestException
    (network/timeout/5xx -- not on a 2xx response with an unexpected
    body shape, which a retry can't fix). Re-raises the last exception
    unchanged so callers keep converting it to their own domain error
    class exactly as before; this only adds retries around the same call."""
    last_error: requests.RequestException | None = None
    for attempt in range(retries):
        try:
            return fn()
        except requests.RequestException as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(_BACKOFF_BASE_S * (attempt + 1))
    assert last_error is not None
    raise last_error
