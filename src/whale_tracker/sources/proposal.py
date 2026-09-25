"""Kademe 3: final paper-only trade proposal, counter-arguments, worst-case
scenario (see docs/PROJECT-PLAN.md section 5 -- tool: Claude Opus, "sadece
karar aninda"). The rarest, most expensive tier: only escalates when Kademe
2 already called a candidate "strong" -- most candidates never reach here.

This is a PROPOSAL, never an executed trade -- consistent with README.md's
"Kritik sinir" (Claude never executes a real financial transaction, at any
stage, even with approval). Nothing in this module places an order; there
is no exchange trading client imported here, deliberately, same boundary
signal.py's own docstring states for itself.

Two things are deliberately NOT left to the AI's judgment, per section 7's
"Risk Kurallari (Degismez Anayasa)" -- position size and stop-loss are
fixed code constants/derivations, not AI-proposed numbers:
- MAX_POSITION_SIZE_PCT: the 1% ACCOUNT-RISK rule (loss at stop = 1% of
  capital), not a per-trade AI decision. Despite the historical name it is
  not a notional cap -- sizing.position_size_usd turns it into a size.
- stop_loss_price: derived deterministically from the technical snapshot's
  support level (code), never from free-form AI output -- guarantees
  "Her islemin mutlaka stop-loss'u olur" instead of hoping the model
  remembers to include one.

Also deliberately narrow, matching section 6 ("Bas,ta sadece spot alim
(long)"): only `accumulation` candidates can produce a real proposal.
`distribution` would imply shorting, out of scope at this trading-style
stage -- always no_action, not escalated to the AI at all (saves the
Opus-tier cost on a candidate this stage can't act on anyway)."""

from __future__ import annotations

import json
from typing import Any

from whale_tracker.sizing import ACCOUNT_RISK_PCT

from .analysis import AnalysisError, _call_claude

# Section 7: "Islem basina maksimum risk: sermayenin %1'i" -- fixed, never
# a per-trade AI decision.
# Historical name kept (it is also a final_proposals column); the value is
# account risk per trade, see sizing.py.
MAX_POSITION_SIZE_PCT = ACCOUNT_RISK_PCT

# Not calibrated against this project's own trade history yet (there is
# none -- no trades exist) -- a conservative first-pass buffer below the
# technical support level, same "revisit once real history accumulates"
# caveat as signal.py's FUNDING_* /SENTIMENT_* bands.
STOP_LOSS_SUPPORT_BUFFER_PCT = 0.02

_SYSTEM_PROMPT = "Sen kisa, yapilandirilmis JSON ciktisi ureten kidemli bir strateji asistanisin."

_INSTRUCTION = """Sen bir kripto piyasasi kidemli stratejistisin. Sana
Kademe 1 (olay siniflandirma) ve Kademe 2 (baglamsal analiz) ile zaten
zenginlestirilmis, GUCLU olarak degerlendirilmis bir sinyal adayi
verilecek. Gorevin bunu nihai bir KAGIT UZERINDE (paper) islem onerisine
donusturmek -- gercek bir islem asla yurutulmeyecek, bu yalnizca oneri
metni, bir emir degil.

Yalnizca su tam sekilde bir JSON nesnesi dondur:
{"entry_rationale": "<en fazla 60 kelime, neden simdi>",
 "worst_case_scenario": "<en fazla 50 kelime, en kotu ne olabilir>",
 "counter_arguments": ["<kisa madde>", ...En fazla 3 tane],
 "conviction": "low"|"medium"|"high"}

Kurallar:
- Bu kagit uzerinde bir oneridir; gercek bir islem emri degildir ve asla
  olmayacak -- bunu varsayarak yaz.
- Pozisyon buyuklugu ve stop-loss fiyati zaten kod tarafinda sabit
  kurallarla belirleniyor -- bunlarla ilgili sayi uretme, yalnizca yon ve
  gerekceye odaklan.
- Kaldiraç veya açığa satış önerme -- şu an yalnızca spot uzun (long)
  kapsamda."""


class ProposalError(RuntimeError):
    """Raised when the Claude CLI call fails or returns an unexpected shape."""


def _compute_stop_loss(technical: dict[str, Any] | None) -> float | None:
    if not technical or not technical.get("support"):
        return None
    return round(technical["support"] * (1 - STOP_LOSS_SUPPORT_BUFFER_PCT), 2)


def _no_action(reason: str) -> dict[str, Any]:
    return {
        "action": "no_action",
        "reason": reason,
        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
        "stop_loss_price": None,
        "entry_rationale": None,
        "worst_case_scenario": None,
        "counter_arguments": [],
        "conviction": None,
    }


def _format_context(candidate: dict[str, Any], deep_analysis: dict[str, Any], context: dict[str, Any]) -> str:
    lines = [
        f"Aday yon: {candidate['direction']}",
        f"Mekanik guven puani: {candidate['confidence']:.2f}",
        f"Kademe 2 degerlendirmesi ({deep_analysis['corroboration_strength']}): {deep_analysis['assessment']}",
        f"Kademe 2 karsi senaryosu: {deep_analysis['counter_argument']}",
    ]
    if deep_analysis.get("risk_flags"):
        lines.append(f"Kademe 2 risk bayraklari: {', '.join(deep_analysis['risk_flags'])}")
    technical = context.get("technical_snapshot")
    if technical:
        lines.append(
            f"Teknik: trend={technical['trend']}, support=${technical['support']:,.0f}, "
            f"guncel_fiyat=${technical['current_price']:,.0f}"
        )
    return "\n".join(lines)


def generate_final_proposal(
    candidate: dict[str, Any], deep_analysis: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """Return a paper-only proposal dict, or a fixed no_action dict when
    this stage's own trading-style/risk-rule constraints already rule it
    out (see module docstring) -- those cases never call the AI at all.
    Raises ProposalError on an AI-call failure; callers should treat this
    as "skip it," matching classify.py/analysis.py's contract."""
    if candidate["direction"] != "accumulation":
        return _no_action("yon 'accumulation' degil -- bu asamada yalnizca spot uzun kapsamda")

    stop_loss_price = _compute_stop_loss(context.get("technical_snapshot"))
    if stop_loss_price is None:
        return _no_action("teknik anlik goruntu/destek seviyesi yok -- stop-loss hesaplanamadi, zorunlu kural")

    prompt = f"{_INSTRUCTION}\n\nBaglam:\n{_format_context(candidate, deep_analysis, context)}"
    try:
        raw = _call_claude(prompt, model="opus", system_prompt=_SYSTEM_PROMPT)
    except AnalysisError as error:
        raise ProposalError(str(error)) from error

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProposalError(f"claude returned non-JSON proposal: {raw[:200]}") from error

    required = {"entry_rationale", "worst_case_scenario", "counter_arguments", "conviction"}
    if not isinstance(parsed, dict) or not required <= parsed.keys():
        raise ProposalError(f"claude JSON missing required fields: {parsed}")
    if parsed["conviction"] not in {"low", "medium", "high"}:
        raise ProposalError(f"invalid conviction: {parsed['conviction']}")
    if not isinstance(parsed["counter_arguments"], list):
        raise ProposalError(f"counter_arguments must be a list: {parsed['counter_arguments']}")

    return {
        "action": "long_candidate",
        "reason": None,
        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
        "stop_loss_price": stop_loss_price,
        "entry_rationale": str(parsed["entry_rationale"])[:400],
        "worst_case_scenario": str(parsed["worst_case_scenario"])[:300],
        "counter_arguments": [str(item)[:150] for item in parsed["counter_arguments"]][:5],
        "conviction": parsed["conviction"],
    }
