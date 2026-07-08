# Provenance Guard — Planning

## 1. Detection Signals

Two independent signals, chosen because one is semantic and one is structural — they fail in different situations, so combining them is more informative than either alone.

**Signal 1 — LLM-based classification (Groq, llama-3.3-70b-versatile)**
- Measures: holistic semantic/stylistic coherence — does the writing "read" as generated.
- Output shape: a float `0.0–1.0` ("AI-likelihood"), parsed from a structured JSON response the model is prompted to return, plus a one-sentence rationale string (stored for the audit log / appeal review, not used in scoring math).
- Why it differs human vs AI: LLMs are well-tuned to recognize their own family's tells — even-handed hedging, generic transition phrases ("It is important to note that..."), overly balanced arguments.
- Blind spot: can misjudge very formal, technical, or non-native-English human writing as AI (false positive risk). Can also be fooled by short or heavily hand-edited AI text.

**Signal 2 — Stylometric heuristics (pure Python)**
- Measures: structural uniformity via three metrics: sentence-length variance, type-token ratio (vocabulary diversity), and punctuation density.
- Output shape: each metric normalized to `0.0–1.0`, averaged into a single float `0.0–1.0` ("structural AI-likelihood").
- Why it differs human vs AI: AI-generated text tends toward uniform sentence length and moderate, consistent vocabulary. Human writing is "burstier" — mixing short and long sentences, more irregular punctuation.
- Blind spot: unreliable under ~50 words (not enough data for variance to mean anything). Can be spoofed by AI text deliberately varied in length.

**Combining into a confidence score:**
```
raw = 0.6 * llm_score + 0.4 * stylometric_score
```
LLM is weighted higher because it captures meaning, not just surface structure. If the two signals disagree sharply (`abs(llm_score - stylometric_score) > 0.4`), that disagreement is itself informative — it means the evidence is mixed — so the raw score is pulled 30% of the way toward 0.5 before being finalized. This prevents one confident-but-wrong signal from dominating when the other signal actively disagrees.

## 2. Uncertainty Representation

The final `confidence` score (`0.0–1.0`) represents *"how likely this content is AI-generated,"* not raw model confidence. A score of 0.6 means: the evidence leans toward AI, but not strongly enough to state it plainly — a human reader should treat it as a leaning, not a verdict.

Thresholds are **asymmetric on purpose** (per the false-positive hint — wrongly calling a human's work "AI" is worse than the reverse, so the bar for "likely AI" is set higher than the bar for "likely human"):

| Range | Category |
|---|---|
| `>= 0.70` | Likely AI-generated (high confidence) |
| `0.35 – 0.69` | Uncertain |
| `<= 0.35` | Likely human-written (high confidence) |

## 3. Transparency Label Design

Exact text returned by the API and shown to readers:

| Category | Label text |
|---|---|
| High-confidence AI | `"This piece shows strong signs of being AI-generated. Multiple independent checks agree it's likely not written by a human."` |
| Uncertain | `"We can't confidently tell whether this piece is AI-generated or human-written. The signals we checked were mixed or inconclusive — treat this as inconclusive, not a verdict."` |
| High-confidence human | `"This piece shows strong signs of human authorship. Our checks found no significant indicators of AI generation."` |

No jargon ("classifier," "logit," "signal score") appears in any label — a non-technical reader should understand each one without explanation.

## 4. Appeals Workflow

- **Who:** the original creator (identified by `creator_id` tied to the `content_id`), submitting via `POST /appeal`.
- **What they provide:** `content_id` and `creator_reasoning` (free-text explanation of why they believe the classification is wrong).
- **What the system does:** looks up the original submission by `content_id`, sets its status to `"under_review"`, and appends a new audit log entry containing the appeal reasoning, timestamp, and a reference back to the original decision (signal scores, confidence, label). No automated re-classification occurs.
- **What a human reviewer would see:** the original text excerpt, both signal scores, the combined confidence and label, the creator's reasoning, and the timestamp of both the original classification and the appeal — everything needed to make a manual call without re-running the pipeline.

## 5. Anticipated Edge Cases

1. **Very short submissions (under ~30 words)** — e.g., a haiku or a one-line caption. The stylometric signal needs enough text for sentence-length variance and type-token ratio to be meaningful; on very short text these metrics are close to noise, which can push the combined score into "uncertain" for the wrong reason (lack of data, not genuine ambiguity) or, worse, produce a spuriously confident score in either direction.
2. **Formal or technical human writing** (e.g., an academic abstract, or writing by a non-native English speaker who leans on more rigid sentence structures) — the LLM signal is prone to reading consistent structure and hedging language as "AI-like," creating a false-positive risk against exactly the kind of writer the system should be protecting.

## Architecture

```
Submission flow:
POST /submit (text, creator_id)
        |
        v
  +-----------+       +--------------------+
  | Signal 1  |       | Signal 2           |
  | Groq LLM  |       | Stylometric        |
  | -> 0-1    |       | heuristics -> 0-1  |
  +-----+-----+       +----------+---------+
        |                        |
        +----------+-------------+
                   v
          Confidence Scoring
     (weighted combo + disagreement
            dampening)
                   v
          Label Lookup
   (likely_ai / uncertain / likely_human)
                   v
           Audit Log Write
                   v
     Response: {content_id, attribution,
                confidence, label}

Appeal flow:
POST /appeal (content_id, creator_reasoning)
                   v
      Status -> "under_review"
                   v
      Audit Log Write (linked to
      original content_id)
                   v
      Response: confirmation
```

A submission flows through both signals in parallel, gets combined into one confidence score, is mapped to a label, and every step is recorded in the audit log before the response returns. An appeal looks up the existing `content_id`, flips status to `under_review`, and writes a linked log entry — no re-scoring occurs.

## AI Tool Plan

**M3 (submission endpoint + first signal):**
- Spec sections given to AI tool: "Detection Signals" (Signal 1 only) + the Architecture diagram.
- What I'll ask for: a Flask app skeleton with the `POST /submit` route stub, and a standalone `llm_signal(text)` function calling Groq.
- Verification: call `llm_signal()` directly on 2–3 test strings before wiring it into the route; confirm it returns a float `0–1`, not a string or dict shape that doesn't match the spec.

**M4 (second signal + confidence scoring):**
- Spec sections given: "Detection Signals" (both) + "Uncertainty Representation" + diagram.
- What I'll ask for: a standalone `stylometric_signal(text)` function, and a `combine_scores(llm_score, stylo_score)` function implementing the weighted formula and disagreement dampening.
- Verification: run both signals on the four test inputs (clearly AI, clearly human, two borderline) and confirm scores land in the expected ranges relative to each other, and that the combine function's output matches the thresholds table exactly — not an approximation of it.

**M5 (production layer):**
- Spec sections given: "Transparency Label Design" + "Appeals Workflow" + diagram.
- What I'll ask for: a `get_label(confidence)` function returning the exact label strings from the table, and the `POST /appeal` endpoint.
- Verification: call `get_label()` with scores just above/below each threshold to confirm the exact quoted text comes back; submit a test appeal and confirm `GET /log` shows `status: "under_review"` with `appeal_reasoning` populated.