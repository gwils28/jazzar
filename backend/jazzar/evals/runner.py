"""Harness d'évaluation : rejoue le golden set sur le système complet et mesure
retrieval (pass@k), génération (must_include, interdits, couverture de citation), comportement (refus),
et fidélité via un juge LLM. Les seuils (gates) bloquent si non atteints.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from jazzar.config import get_settings
from jazzar.db import get_session
from jazzar.llm.answer import answer_stream
from jazzar.llm.client import get_llm
from jazzar.logging import get_logger
from jazzar.models import EvalRun
from jazzar.text import BACKEND as TEXT_BACKEND

log = get_logger(__name__)
GOLDEN_DIR = Path(__file__).parent


class Judgement(BaseModel):
    behavior: str = Field(description="answer | refuse | ask_clarification")
    faithfulness: float = Field(ge=0, le=1, description="Part des affirmations étayées par les extraits")
    unsupported_claims: list[str] = Field(default_factory=list)


JUDGE_SYSTEM = """Tu es le juge d'un système de questions-réponses sur archives jazz. On te donne la question, les
extraits fournis au système et sa réponse. Détermine :
- behavior : 'refuse' si la réponse dit explicitement qu'elle ne peut pas répondre / corrige une prémisse fausse ;
  'ask_clarification' si elle demande une précision ; sinon 'answer'.
- faithfulness : fraction (0 à 1) des affirmations factuelles de la réponse qui sont étayées par les extraits.
  Une réponse qui refuse proprement a une fidélité de 1.
- unsupported_claims : liste des affirmations non étayées (texte court)."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'"))


def load_golden(name: str = "golden_set_v1.json") -> dict:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


async def run_case(case: dict, lang: str = "fr") -> dict[str, Any]:
    t0 = time.perf_counter()
    tokens: list[str] = []
    sources: list[dict] = []
    done: dict = {}
    async with get_session() as session:
        async for ev in answer_stream(session, case["question"], lang=lang, use_cache=False):
            if ev["type"] == "token":
                tokens.append(ev["text"])
            elif ev["type"] == "sources":
                sources = ev["hits"]
            elif ev["type"] == "done":
                done = ev
    answer = "".join(tokens)
    norm_answer = _norm(answer)

    # Retrieval : un titre doré apparaît-il dans les sources remontées ?
    golden_titles = case.get("golden_titles", [])
    retrieval_hit = (not golden_titles) or any(_norm(t) in _norm(s.get("title", "")) for t in golden_titles for s in sources)

    must_rate = 1.0
    if case["must_include"]:
        must_rate = sum(1 for m in case["must_include"] if _norm(m) in norm_answer) / len(case["must_include"])
    forbidden = [m for m in case.get("must_not_include", []) if _norm(m) in norm_answer]

    # Couverture de citation : pour une réponse (pas un refus), au moins une référence [n]
    cited = bool(re.search(r"\[\d{1,2}\]", answer))

    # Juge
    judgement = Judgement(behavior="answer", faithfulness=0.0)
    llm = get_llm()
    cost = done.get("cost_usd", 0.0)
    if llm.available and answer:
        src_text = "\n\n".join(f"[{s.get('n')}] {s.get('title')} — {s.get('text', '')[:1200]}" for s in sources[:12])
        try:
            judgement, jcost = await llm.parse(
                purpose="eval:judge", system=JUDGE_SYSTEM, output_format=Judgement, effort="low", max_tokens=1500,
                messages=[{"role": "user", "content": f"QUESTION\n{case['question']}\n\nEXTRAITS\n{src_text}\n\nRÉPONSE\n{answer}"}],
            )
            cost += jcost
        except Exception as exc:  # noqa: BLE001
            log.warning("eval.judge_failed", error=str(exc))

    expected = case.get("behavior", "answer")
    behavior_ok = (judgement.behavior == expected) or (expected == "refuse" and judgement.behavior == "ask_clarification")
    if expected == "refuse":
        passed = behavior_ok and not forbidden
    else:
        passed = behavior_ok and must_rate >= 0.99 and not forbidden and cited and judgement.faithfulness >= 0.95

    return {
        "id": case["id"], "type": case["type"], "question": case["question"], "expected_behavior": expected,
        "behavior_observed": judgement.behavior, "behavior_ok": behavior_ok, "retrieval_hit": retrieval_hit,
        "must_include_rate": round(must_rate, 3), "forbidden_found": forbidden, "citation_coverage": 1.0 if (cited or expected == "refuse") else 0.0,
        "faithfulness": judgement.faithfulness, "unsupported_claims": judgement.unsupported_claims,
        "route": done.get("route"), "latency_ms": int((time.perf_counter() - t0) * 1000), "cost_usd": round(cost, 5),
        "passed": passed, "answer": answer[:1500],
    }


def aggregate(per_case: list[dict], gates: dict) -> tuple[dict, bool]:
    def rate(cases: list[dict], key, pred=lambda v: bool(v)) -> float:
        return round(sum(1 for c in cases if pred(c[key])) / len(cases), 3) if cases else 1.0

    traps = [c for c in per_case if c["type"] == "refusal_trap"]
    factual = [c for c in per_case if c["type"] != "refusal_trap"]
    retrievable = [c for c in per_case if c["expected_behavior"] == "answer"]
    agg = {
        "n_cases": len(per_case),
        "pass_rate": rate(per_case, "passed"),
        "refusal_trap_pass_rate": rate(traps, "passed"),
        "citation_coverage": rate(factual, "citation_coverage", lambda v: v >= 1.0),
        "faithfulness_factual": round(sum(c["faithfulness"] for c in factual) / len(factual), 3) if factual else 1.0,
        "retrieval_passk": rate(retrievable, "retrieval_hit"),
        "avg_latency_ms": int(sum(c["latency_ms"] for c in per_case) / len(per_case)) if per_case else 0,
        "total_cost_usd": round(sum(c["cost_usd"] for c in per_case), 4),
    }
    passed_gates = all(agg.get(k, 0) >= v for k, v in gates.items())
    agg["gates"] = gates
    return agg, passed_gates


async def run_golden(name: str = "golden_set_v1.json", only: list[str] | None = None, lang: str = "fr") -> EvalRun:
    golden = load_golden(name)
    s = get_settings()
    cases = [c for c in golden["cases"] if not only or c["id"] in only]
    per_case = []
    for case in cases:
        log.info("eval.case", id=case["id"])
        per_case.append(await run_case(case, lang))
    agg, ok = aggregate(per_case, golden.get("gates", {}))
    run = EvalRun(
        system_version=f"{s.model_large}+{s.model_small}|{s.embedding_model}|text={TEXT_BACKEND}",
        golden_set=golden["name"], aggregate=agg, per_case=per_case, passed_gates=ok, cost_usd=agg["total_cost_usd"],
    )
    async with get_session() as session:
        session.add(run)
        await session.commit()
        await session.refresh(run)
    return run
