"""Kademe 2: combine an important situation (a scored signal candidate)
with its full context and produce a qualitative analysis (see
docs/PROJECT-PLAN.md section 5 -- "Onemli durumlari baglamla birlestirip
analiz", tool: Claude Sonnet, frequency: "saatte birkac kez").

Only runs when signal.py's mechanical scoring already produced a
candidate -- most cycles produce none, so this is naturally rare, not a
per-cycle cost. Uses the Claude Code CLI already authenticated on this
machine (Claude Pro subscription, verified via `claude` config during this
session) rather than a separate Anthropic API key, mirroring Kademe 1's
"reuse existing auth, no new credential" posture in classify.py.

Cost/usage note (measured, not assumed): a bare `claude -p` call from a
project directory pulls in that project's full MCP/skill/memory context
(~250K cache-creation tokens observed). `--strict-mcp-config` (no MCP
servers) plus `--tools ""` (no built-in tools) cuts this to ~15K tokens --
still real usage against the account's shared Claude Pro quota (the same
quota interactive sessions draw from), not free, hence the gate above.
This module never overrides signal.py's mechanical confidence score --
Kademe 2's job is added qualitative context, not a different number.
Kademe 3 (Opus/Fable, final trade proposal + counter-arguments) is a
separate, later, not-yet-built phase; no buy/sell output happens here."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from ._hidden_subprocess import hide_windows_matching, run_hidden_and_reap

_TIMEOUT_S = 90

_SYSTEM_PROMPT = "Sen kisa, yapilandirilmis JSON ciktisi ureten bir analiz asistanisin."

_INSTRUCTION = """Sen bir kripto piyasasi analistisin. Sana mekanik olarak
hesaplanmis bir "sinyal adayi" (yon + guven puani + bilesenleri) ve o anki
piyasa baglami verilecek. Gorevin bu adayi baglamla birlestirip nitel bir
degerlendirme yapmak -- guven puanini degistirmek DEGIL, ona ek bakis acisi
saglamak.

Yalnizca su tam sekilde bir JSON nesnesi dondur:
{"assessment": "<en fazla 40 kelime, adayin baglamla ne kadar tutarli oldugu>",
 "counter_argument": "<en fazla 30 kelime, PROJECT-PLAN'in kendi karsi-ornek
 mantigiyla: en guclu ters senaryo ne olabilir>",
 "risk_flags": ["<kisa flag>", ...En fazla 3 tane, bos liste de olabilir],
 "corroboration_strength": "weak"|"moderate"|"strong"}

Kurallar:
- ASLA "al", "sat", "pozisyon ac/kapat" gibi bir tavsiye uretme -- yalnizca
  neyin ne kadar tutarli/riskli oldugunu tanimla, ne yapilmasi gerektigini degil.
- Mekanik guven puanini kendi sayinla degistirmeye calisma, yalnizca nitel
  yorum yap.
- Baska hicbir alan, baska hicbir metin ekleme."""


class AnalysisError(RuntimeError):
    """Raised when the Claude CLI call fails or returns an unexpected shape."""


def _discover_claude() -> str | None:
    return shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")


def _call_claude(prompt: str, *, model: str = "sonnet", system_prompt: str = _SYSTEM_PROMPT) -> str:
    executable = _discover_claude()
    if not executable:
        raise AnalysisError("claude CLI not found")
    command = [
        executable, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--tools", "",
        "--strict-mcp-config",
        "--system-prompt", system_prompt,
    ]
    try:
        with hide_windows_matching("claude"):
            completed = run_hidden_and_reap(command, timeout=_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AnalysisError("claude CLI invocation failed") from error
    if completed.returncode != 0:
        # Scheduled runs discard both streams (WshShell.Run has nowhere to
        # send them -- see scripts/register-task.ps1), and error_reason is
        # the only trace that survives into ai_call_log. A real 2026-09-24
        # burst of failures left nothing to diagnose after the fact because
        # stderr happened to be empty and stdout was never even looked at
        # -- fall back to stdout so the next occurrence is actually
        # diagnosable instead of silently unobservable again.
        detail = completed.stderr[-200:].strip() or completed.stdout[-200:].strip() or "(çıktı yok)"
        raise AnalysisError(f"claude CLI returned non-zero (exit {completed.returncode}): {detail}")
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AnalysisError(f"claude CLI returned non-JSON envelope: {completed.stdout[:200]}") from error
    if not isinstance(envelope, dict):
        # json.loads succeeds on any valid JSON (null, a string, a list, a
        # bare number), not just objects -- the CLI's envelope shape isn't
        # a contract this codebase controls, so a non-dict result must be
        # treated as unavailable, not assumed to support .get() (an
        # AttributeError here would escape as neither AnalysisError nor
        # ProposalError and crash the whole observe.py run, defeating the
        # "AI calls fail gracefully" contract every caller relies on).
        raise AnalysisError(f"claude CLI envelope was not a JSON object: {completed.stdout[:200]}")
    if envelope.get("is_error"):
        raise AnalysisError(f"claude CLI reported an error result: {envelope.get('result')}")
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        raise AnalysisError("claude CLI envelope missing result text")
    return result


def _format_context(candidate: dict[str, Any], context: dict[str, Any]) -> str:
    lines = [
        f"Aday yon: {candidate['direction']}",
        f"Mekanik guven puani: {candidate['confidence']:.2f}",
        f"Bilesenler: {json.dumps(candidate['components'], ensure_ascii=False)}",
        "Gerekce:",
        *[f"- {line}" for line in candidate["rationale"]],
    ]
    market = context.get("market_snapshot")
    if market:
        lines.append(
            f"Piyasa: mark_price=${market['mark_price']:,.0f}, "
            f"funding={market['funding_rate']:.4%}, open_interest={market['open_interest']:,.0f}"
        )
    technical = context.get("technical_snapshot")
    if technical:
        lines.append(
            f"Teknik: trend={technical['trend']}, support=${technical['support']:,.0f}, "
            f"resistance=${technical['resistance']:,.0f}"
        )
    headlines = context.get("recent_headlines") or []
    if headlines:
        lines.append("Son basliklar: " + "; ".join(h["title"] for h in headlines[:5]))
    return "\n".join(lines)


def generate_deep_analysis(candidate: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Return a qualitative analysis dict for one signal candidate.
    Raises AnalysisError on any failure -- callers should treat this as
    "skip it," never as a reason to fail the whole observer run (mirrors
    classify.py's ClassificationError contract)."""
    prompt = f"{_INSTRUCTION}\n\nBaglam:\n{_format_context(candidate, context)}"
    raw = _call_claude(prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AnalysisError(f"claude returned non-JSON analysis: {raw[:200]}") from error

    required = {"assessment", "counter_argument", "risk_flags", "corroboration_strength"}
    if not isinstance(parsed, dict) or not required <= parsed.keys():
        raise AnalysisError(f"claude JSON missing required fields: {parsed}")
    if parsed["corroboration_strength"] not in {"weak", "moderate", "strong"}:
        raise AnalysisError(f"invalid corroboration_strength: {parsed['corroboration_strength']}")
    if not isinstance(parsed["risk_flags"], list):
        raise AnalysisError(f"risk_flags must be a list: {parsed['risk_flags']}")

    return {
        "assessment": str(parsed["assessment"])[:400],
        "counter_argument": str(parsed["counter_argument"])[:300],
        "risk_flags": [str(flag)[:100] for flag in parsed["risk_flags"]][:5],
        "corroboration_strength": parsed["corroboration_strength"],
    }
