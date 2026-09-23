"""Kademe 1: cheap-model classification of the most significant onchain
events each run (see docs/PROJECT-PLAN.md section 5 -- "7/24, cok ucuz").

Uses the Hermes Agent CLI (already installed/authenticated on this
machine via a ChatGPT/Codex subscription, verified during Brain-Eleven
work this session -- no separate API key, no new cost). One call is
~7-9s, so this is bounded to a small number of events per run (only the
largest unclassified ones), not every event -- 50+ calls would blow past
the scheduled task's 5-minute execution limit and the 15-minute cycle.

This is classification, not a trading signal: "how significant/what kind
of movement does this look like," never "buy/sell." Kademe 2/3 (Sonnet/
Opus, actual signal combination) are separate, later phases."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

_HERMES_PATH = shutil.which("hermes") or str(
    Path.home() / "AppData" / "Local" / "hermes" / "bin" / "hermes.exe"
)
_TIMEOUT_S = 30

_INSTRUCTION = """Sen bir kripto piyasası zincir-üstü hareket sınıflandırıcısısın.
Sana bir stablecoin transferi verilecek. Yalnızca şu tam şekilde bir JSON nesnesi döndür:
{"significance": "high"|"medium"|"low", "interpretation": "<en fazla 15 kelimelik kısa yorum>", "confidence": <0.0-1.0 arası sayı>}
Kurallar:
- Bilinen bir borsaya giren büyük transfer: olası satış baskısı, significance genelde high/medium.
- Bilinen bir borsadan çıkan büyük transfer: olası biriktirme, significance genelde high/medium.
- İki bilinmeyen cüzdan arası transfer: yorumu daha temkinli yap, confidence'ı düşük tut.
- DEX veya işaretlenmiş (flagged) bir taraf varsa bunu interpretation'da belirt.
- ASLA "al", "sat", "işlem yap" gibi bir tavsiye üretme -- yalnızca ne olduğunu tanımla, ne yapılması gerektiğini değil.
- Başka hiçbir alan, başka hiçbir metin ekleme."""


class ClassificationError(RuntimeError):
    """Raised when the classifier CLI fails or returns an unexpected shape."""


def _call_hermes(prompt: str) -> str:
    if not Path(_HERMES_PATH).is_file():
        raise ClassificationError("hermes CLI not found")
    try:
        completed = subprocess.run(
            [_HERMES_PATH, "-z", prompt, "--ignore-rules"],
            capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClassificationError("hermes CLI invocation failed") from error
    if completed.returncode != 0:
        raise ClassificationError(f"hermes CLI returned non-zero: {completed.stderr[-200:]}")
    return completed.stdout.strip()


def classify_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return {"significance", "interpretation", "confidence"} for one
    onchain event. Raises ClassificationError on any failure -- callers
    should treat a classification failure as "skip it," never as a
    reason to fail the whole observer run (see observe.py)."""
    from_tag = event.get("from_known_exchange") or "bilinmeyen cüzdan"
    to_tag = event.get("to_known_exchange") or "bilinmeyen cüzdan"
    description = (
        f"Token: {event['token']}\n"
        f"Miktar: ${event['amount_usd_estimate']:,.0f}\n"
        f"Gönderen: {from_tag}\n"
        f"Alan: {to_tag}"
    )
    prompt = f"{_INSTRUCTION}\n\nTransfer:\n{description}"

    raw = _call_hermes(prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ClassificationError(f"hermes returned non-JSON output: {raw[:200]}") from error

    if not isinstance(parsed, dict) or not {"significance", "interpretation", "confidence"} <= parsed.keys():
        raise ClassificationError(f"hermes JSON missing required fields: {parsed}")
    if parsed["significance"] not in {"high", "medium", "low"}:
        raise ClassificationError(f"invalid significance value: {parsed['significance']}")
    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError) as error:
        raise ClassificationError(f"invalid confidence value: {parsed['confidence']}") from error
    if not 0.0 <= confidence <= 1.0:
        raise ClassificationError(f"confidence out of range: {confidence}")

    return {
        "significance": parsed["significance"],
        "interpretation": str(parsed["interpretation"])[:200],
        "confidence": confidence,
    }


def classify_top_events(events: list[dict[str, Any]], *, limit: int = 5) -> dict[int, dict[str, Any]]:
    """Classify only the `limit` largest events by dollar amount -- bounded
    cost/latency, see module docstring. Returns {event_index_in_input: classification}
    for whichever ones succeeded; a failed classification is silently
    skipped (logged by the caller), not retried, not fatal."""
    ranked = sorted(range(len(events)), key=lambda i: events[i]["amount_usd_estimate"], reverse=True)
    results: dict[int, dict[str, Any]] = {}
    for index in ranked[:limit]:
        try:
            results[index] = classify_event(events[index])
        except ClassificationError:
            continue
    return results
