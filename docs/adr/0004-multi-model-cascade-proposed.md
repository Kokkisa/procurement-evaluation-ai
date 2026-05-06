# ADR 0004: Multi-Model Cascade for Cost Optimization

- **Status:** Proposed (target: v0.2)
- **Date:** Block 10 (post-OpenAI-migration cost analysis)
- **Decision-maker:** Project lead

## Context

After the Block 10 provider migration (Anthropic -> OpenAI, see [ADR-0001](0001-provider-agnostic-llm-factory.md)), per-run cost dropped to **$0.06 against gpt-4o-mini** for a full 5-vendor evaluation. That is already cheap, but two observations from LangSmith trace inspection suggest meaningful headroom:

1. **A majority of criteria evaluations are unambiguous.** "Is this PAN card document provided?" -- the answer is binary, the prompt is trivial, and gpt-4o-mini handles it confidently. There is no measurable quality difference vs Claude Sonnet for this class of criterion.
2. **A minority of criteria are nuanced.** "Does this similar-works experience match the technical scope?" -- this requires careful interpretation of vendor narrative, comparing dates, project scopes, and qualitative judgments. gpt-4o-mini occasionally produces low-confidence verdicts here that a stronger model resolves cleanly.

Today the system uses a **single model** for every criterion. The cheap model is good enough for ~80% of cases and adequate for the rest -- but adequate is not the same as defensible.

A two-tier cascade could likely reduce cost further while improving quality on the borderline cases.

## Proposed Decision (not yet implemented)

**Implement a two-tier model cascade where gpt-4o-mini handles first-pass evaluation, and Claude Sonnet (or gpt-4o) is invoked only for borderline-confidence cases.**

Sketch:

```python
async def evaluate_criterion(criterion, vendor_doc):
    # Tier 1: cheap fast model
    draft = await mini_chain.ainvoke({"criterion": criterion, "doc": vendor_doc})
    if draft.confidence >= settings.cascade_confidence_threshold:
        return draft
    # Tier 2: stronger model, used only when needed
    refined = await sonnet_chain.ainvoke({
        "criterion": criterion,
        "doc": vendor_doc,
        "draft_verdict": draft,
        "draft_reasoning": draft.reasoning,
    })
    return refined
```

Two new configuration knobs:

| Knob | Default (proposed) | Purpose |
|---|---|---|
| `LLM_CASCADE_ENABLED` | false | Master switch; off by default |
| `LLM_CASCADE_CONFIDENCE_THRESHOLD` | 0.85 | Below this, escalate to tier 2 |

Tier 2 receives the tier-1 draft as additional context. It is not a re-evaluation from scratch -- it is a refinement, which costs fewer tokens than a cold-start evaluation.

## Expected Impact (estimates, not measured)

Assumptions, conservatively chosen for the v0.1 dataset:

- 80% of criteria pass tier 1 with confidence >= 0.85 (gpt-4o-mini at $0.15 / 1M input tokens).
- 20% escalate to tier 2 (Claude Sonnet at $3 / 1M input tokens, with reduced input due to draft-as-context).
- Per-call token counts roughly stable at ~5K input + ~1K output.

Single-model cost (current): ~$0.06 / run.

Cascade cost (estimated):
- Tier 1: ~80 calls x ~$0.0007 = ~$0.06 (same as today)
- Tier 2: ~16 escalations x ~$0.04 = ~$0.64 if always at full price...

Wait -- that math goes backwards. Let me redo.

Assumptions (corrected):

- Tier 1 covers 100% of calls (gpt-4o-mini, ~$0.0007 each, ~80 calls = ~$0.06)
- Tier 2 covers 20% of calls (Claude Sonnet, ~$0.04 each on full prompt, ~16 calls = ~$0.64)
- **Total: ~$0.70 / run**

That is **~12x more expensive** than today, not cheaper. The original "80% cost reduction" intuition assumed we were currently running everything on Sonnet -- which we are not. We migrated off Sonnet in Block 10.

So the **real** value proposition for the cascade is **quality**, not cost: the borderline 20% get a stronger model, while the easy 80% pay the cheap-model price. Total cost goes up, but stays in the cents-per-run range. Quality on nuanced criteria likely improves.

This is precisely the kind of intuition that needs measurement before building. The decision is therefore deferred.

## Why this is deferred to v0.2

- **The cost intuition was wrong.** A "cost optimization" framing only holds if the baseline is the expensive model. Our baseline is the cheap model. The cascade is a **quality** intervention, not a cost intervention.
- **Confidence threshold needs real evaluation data.** A 0.85 threshold is a guess. Tuning it requires a labeled dataset of "borderline cases that gpt-4o-mini got wrong but Claude got right" -- which we do not have.
- **Premature optimization risks regression.** Adding a tier-2 escalation path before the system has been used at scale could mask v0.1 quality issues that should be addressed at the prompt layer first.
- **The factory pattern from [ADR-0001](0001-provider-agnostic-llm-factory.md) makes this trivially addable later.** The cascade can be built as a wrapper Runnable on top of the existing factory without disturbing agent code. There is no architectural debt incurred by waiting.

## Alternatives Considered

- **Always use the strongest model.** Highest quality, highest cost. Anthropic Tier 1 rate limits also reintroduce throttling pain (see [ADR-0002](0002-bounded-concurrency-orchestration.md)). Rejected for v0.1; remains a deployment option via `.env`.
- **Always use the cheapest model.** Where we are today. Adequate quality, lowest cost.
- **Random A/B routing.** Useful for evaluation, not for production. Could be a v0.2 step **before** cascade -- generate the labeled dataset that cascade tuning needs.
- **Self-consistency / vote ensembles.** Run gpt-4o-mini three times, take majority vote. Cheaper than escalating to Sonnet but loses the quality-uplift case for genuinely nuanced criteria. Worth considering as a v0.2 alternative.

## Open Questions

These need answers before promoting this ADR from Proposed to Accepted:

1. **What fraction of v0.1 verdicts would actually flip under tier 2?** Without measurement, the 20% assumption is unsupported.
2. **What is the false-confidence rate of gpt-4o-mini?** That is, when it says confidence=0.95 on a borderline criterion, how often is it actually wrong? The cascade only helps if the confidence signal is calibrated.
3. **Is per-criterion confidence even available?** Today's structured output schema does not include a confidence field. Adding it requires prompt changes and re-evaluation against the existing fixture.
4. **What is the latency impact?** Tier 2 escalation adds an extra round-trip for ~20% of calls. At cap=1, sleep=10s, that adds ~3 minutes to a 5-minute run. Worth it only if quality uplift is real.

## Validation (when accepted)

To promote this ADR from Proposed to Accepted, we will need:

- A labeled evaluation dataset of >= 50 "borderline" criteria with ground-truth verdicts.
- Confidence calibration data showing gpt-4o-mini's reported confidence correlates with correctness (Brier score, reliability diagram).
- A measured cost-per-run number against the cascade with the labeled dataset.
- A measured quality delta (precision/recall on the labeled set, ideally with statistical significance).

## Related

- [ADR-0001](0001-provider-agnostic-llm-factory.md) -- Factory pattern that makes cascade trivially additive.
- [ADR-0002](0002-bounded-concurrency-orchestration.md) -- Concurrency layer that the cascade would inherit.

## Lesson banked

The original framing of this ADR claimed "~80% cost reduction." Working through the actual math during writing showed the framing was wrong: the cascade increases cost ~12x against today's baseline, and its real value is quality, not cost. **Always do the math before writing the marketing.** Promoting this from Proposed to Accepted will require measured numbers, not estimates.
