# Provenance Guard

A backend system that classifies submitted creative text as likely AI-generated, likely human-written, or uncertain — with a confidence score, a plain-language transparency label, an appeals process, rate limiting, and a structured audit log.

## Architecture Overview

A creator submits text + `creator_id` to `POST /submit`. The text is run through three independent detection signals in sequence: an LLM-based semantic check (Groq), a stylometric structural check (pure Python), and a lexical AI-cliché phrase check. The three scores are combined via a weighted formula into a single confidence score, which is mapped to one of three transparency labels using asymmetric thresholds. A `content_id` is generated, and the full record (all signal scores, combined confidence, label, timestamp) is written to a structured SQLite audit log before the response returns. If a creator disputes the result, `POST /appeal` looks up the `content_id`, sets its status to `under_review`, and appends a linked audit log entry with their reasoning. Creators who accumulate a track record of confidently-human submissions can be issued a "Verified Human" certificate via `POST /certify`, which is then surfaced alongside future classifications.

```
POST /submit (text, creator_id)
        |
        v
  +-----------+   +--------------+   +------------------+
  | Signal 1  |   | Signal 2     |   | Signal 3         |
  | Groq LLM  |   | Stylometric  |   | Phrase-pattern   |
  | -> 0-1    |   | heuristics   |   | matching -> 0-1  |
  +-----+-----+   +------+-------+   +--------+---------+
        |                |                    |
        +----------------+--------------------+
                          v
              Confidence Scoring (weighted +
                disagreement dampening)
                          v
                   Label Lookup
                          v
                Audit Log Write
                          v
        Response: {content_id, attribution,
                   confidence, label, signals}

POST /appeal (content_id, creator_reasoning)
                          v
              Status -> "under_review"
                          v
              Audit Log Write (linked)
                          v
              Response: confirmation
```

## Detection Signals

**Signal 1 — LLM-based classification (Groq, llama-3.3-70b-versatile).** Sends the text to the model with a prompt asking it to assess AI-likelihood on a 0–1 scale, returning a structured JSON response. Captures holistic semantic and stylistic coherence — does the writing "read" as generated. What it misses: it can misjudge very formal, technical, or non-native-English human writing as AI, and can be fooled by short or heavily hand-edited AI text.

**Signal 2 — Stylometric heuristics (pure Python).** Computes three structural metrics — sentence-length variance, type-token ratio (vocabulary diversity), and punctuation density — and averages them into one score. AI-generated text tends toward more uniform sentence length and a narrower, more consistent vocabulary band; human writing is "burstier." What it misses: unreliable under ~50 words, since variance and vocabulary diversity need enough text to mean anything; can be spoofed by deliberately varied AI generations.

**Signal 3 (ensemble stretch) — AI-cliché phrase matching.** Counts occurrences of stock LLM phrases ("it is important to note," "delve into," "paradigm shift," etc.) per 100 words. Captures a narrow, targeted lexical pattern distinct from both the holistic LLM judgment and the broad statistical structure of Signal 2. What it misses: trivially defeated by paraphrasing, and produces false positives on formal human writing (academic/business prose) that uses these phrases naturally.

**Combining signals:** `confidence = 0.5 * llm_score + 0.3 * stylometric_score + 0.2 * phrase_score`. LLM is weighted highest because it captures meaning, not just surface features; the phrase signal is weighted lowest because it's the easiest to evade and the most prone to false positives. If the spread between the highest and lowest of the three individual scores exceeds 0.5, the combined score is pulled 30% of the way toward 0.5 — treating strong disagreement between signals as itself a form of uncertainty, rather than letting one confident signal dominate.

## Confidence Scoring

Thresholds are asymmetric on purpose: mislabeling a human's work as AI-generated is a worse outcome for a creative platform than the reverse, so the bar for "likely AI" is set higher than the bar for "likely human."

| Confidence range | Category |
|---|---|
| `>= 0.70` | Likely AI-generated |
| `0.35 – 0.69` | Uncertain |
| `<= 0.35` | Likely human-written |

**Validation approach:** tested against 4 deliberately chosen inputs spanning the range — a clearly AI-generated paragraph, a clearly human casual review, a borderline formal-human paragraph (false-positive risk case), and a borderline lightly-edited AI paragraph — then checked whether the resulting scores and labels matched intuition, adjusting weights/thresholds based on the results rather than assuming the first formula was correct.

**Example — higher-confidence case** (clearly human, casual writing):
```
Input: "ok so i finally tried that new ramen place downtown and honestly?
underwhelming. the broth was fine but they put WAY too much sodium in it..."
llm_score: 0.2, stylometric_score: 0.175, confidence: 0.19 -> likely_human
```

**Example — lower-confidence case** (clearly AI-generated text, but signals disagreed):
```
Input: "Artificial intelligence represents a transformative paradigm shift
in modern society. It is important to note that while the benefits of AI
are numerous..."
llm_score: 0.8, stylometric_score: 0.247, confidence: 0.555 -> uncertain
```
Here the LLM signal strongly suspected AI (0.8) but the stylometric signal disagreed (0.247, reading as structurally human), and the disagreement-dampening pulled the combined score down into the uncertain band rather than trusting either signal alone.

## Transparency Label

| Category | Label text |
|---|---|
| High-confidence AI | "This piece shows strong signs of being AI-generated. Multiple independent checks agree it's likely not written by a human." |
| Uncertain | "We can't confidently tell whether this piece is AI-generated or human-written. The signals we checked were mixed or inconclusive — treat this as inconclusive, not a verdict." |
| High-confidence human | "This piece shows strong signs of human authorship. Our checks found no significant indicators of AI generation." |

No jargon (no "classifier," "logit," "signal score") — a non-technical reader can understand the result without explanation. If a creator holds an active "Verified Human" certificate, an additional sentence is appended: *"This creator holds an active Verified Human certificate."*

## Appeals Workflow

`POST /appeal` accepts `{content_id, creator_reasoning}`. The system verifies the `content_id` exists, sets its status to `under_review`, and appends a new linked audit log entry containing the appeal reasoning and a timestamp. Automated re-classification is not performed — this is a hand-off to a human reviewer.

**Example evidence** (from actual testing):
```json
// Original classification (id: 5), before appeal:
{ "content_id": "eee65c02-...", "attribution": "likely_human", "confidence": 0.19, "status": "classified" }

// After POST /appeal with creator_reasoning:
// "I wrote this myself from personal experience. I am a non-native English
//  speaker and my writing style may appear more formal than typical."

// Original entry (id: 5) now shows:
{ "content_id": "eee65c02-...", "status": "under_review" }

// New linked entry (id: 6):
{ "content_id": "eee65c02-...", "event_type": "appeal",
  "appeal_reasoning": "I wrote this myself from personal experience...",
  "status": "under_review" }
```

## Rate Limiting

`POST /submit` is limited to **10 requests per minute and 100 per day**, per IP (Flask-Limiter, in-memory storage).

**Reasoning:** a genuine creator submitting their own work would rarely submit more than a handful of pieces in quick succession — 10/minute comfortably covers someone submitting a batch of short pieces or retrying after a typo, without allowing meaningful abuse. The 100/day ceiling allows for a very active user or a platform doing batch re-checks, while still bounding worst-case load from a single source. Both numbers are generous enough not to interfere with legitimate use, but tight enough that a scripted flood is throttled within seconds.

**Evidence** — 12 rapid requests against the limit:
```
200
200
200
200
200
200
200
200
200
200
429
429
```
The first 10 succeed; requests 11 and 12 are rejected with `429 Too Many Requests`.

## Audit Log

Stored in SQLite (`audit_log.db`), structured with columns for `content_id`, `creator_id`, `timestamp`, `event_type`, `attribution`, `confidence`, `llm_score`, `stylometric_score`, `label`, `status`, and `appeal_reasoning`. Retrieved via `GET /log`.

**Sample entries (from actual testing):**

| id | event_type | content_id | attribution | confidence | status |
|---|---|---|---|---|---|
| 1 | classification | e046af13-... | uncertain | 0.555 | classified |
| 2 | classification | 6c4a7961-... | likely_human | 0.19 | classified |
| 3 | classification | 329e388b-... | uncertain | 0.371 | classified |
| 4 | classification | f0e982e0-... | likely_human | 0.278 | classified |
| 5 | classification | eee65c02-... | likely_human | 0.19 | under_review |
| 6 | appeal | eee65c02-... | — | — | under_review |

Entry 6 shows the appeal linked to entry 5's `content_id`, with `appeal_reasoning` populated and the original entry's status flipped — satisfying the requirement that an appeal be visible alongside its original classification.

## Stretch Features Completed

**Ensemble Detection:** extended from 2 to 3 signals (added phrase-pattern matching), combined via a documented weighted formula (0.5 / 0.3 / 0.2) with disagreement dampening across all three scores. See `scoring.combine_scores_ensemble()`.

**Provenance Certificate ("Verified Human"):** implemented in `storage.py` / `app.py`. A creator becomes eligible after at least 2 prior submissions score `<= 0.20` confidence with no open appeal (`POST /certify` checks this and issues the certificate; `GET /certificate/<creator_id>` checks status). Once certified, the creator's future submissions include `"creator_certified": true` and an appended sentence on the label. This does not override per-submission detection — a certified creator can still receive an "uncertain" or "likely_ai" result on any individual piece; the certificate is a reputational signal shown alongside the result, not a bypass.

## Known Limitations

Lightly-edited AI text can slip past this system as "likely human." In testing, a paragraph that read as plausible AI-smoothed writing about remote work scored `llm_score: 0.2, stylometric_score: 0.394` and landed as `likely_human` (confidence 0.278) — both signals were fooled, since light editing removes the LLM's obvious tells and introduces enough sentence-length variation to pass the stylometric check. This is a direct consequence of both signals' documented blind spots (Signal 1's difficulty with edited AI text, Signal 2's need for strong statistical uniformity to flag AI) rather than a generic accuracy gap.

## Spec Reflection

**How the spec helped:** deciding the confidence thresholds and label text in `planning.md` before writing any scoring code meant the combination formula had a concrete target to hit, rather than being tuned after the fact. When Signal 3 (phrase-pattern) was added for the ensemble stretch, the existing "what does 0.6 mean" framing from the spec made it straightforward to decide how to weight the new signal rather than guessing.

**Where implementation diverged:** the spec originally didn't anticipate that the LLM and stylometric signals would sometimes disagree sharply enough to actively point in opposite directions (e.g. the "paradigm shift" test case: LLM said 0.8, stylometric said 0.247). The disagreement-dampening logic — pulling the combined score toward 0.5 when the spread between signals is large — was added during Milestone 4 testing once this pattern showed up, and wasn't in the original planning.md formula. It's now documented in planning.md and here, but it emerged from testing rather than upfront design.

## AI Usage

**Instance 1 — Groq signal function.** Directed the AI tool to generate a Flask route stub and a Groq API call function based on the "Detection Signals" section of planning.md, asking for a function that returns a float 0–1 plus a rationale string. The generated version initially didn't handle malformed JSON responses from the model gracefully; I added a `try/except` fallback that defaults to a neutral 0.5 score with an explanatory rationale, so a parsing failure fails toward "uncertain" rather than crashing or silently returning a misleading score.

**Instance 2 — Confidence scoring / disagreement dampening.** Asked the AI tool to implement the weighted combination formula from planning.md. The first version it produced used a straightforward weighted average with no handling for cases where the two signals disagreed sharply. After testing with the four sample inputs and noticing the "paradigm shift" case produced a confidently-wrong result, I directed a revision to add the disagreement-dampening step (pulling the score toward 0.5 when signal spread exceeds a threshold), which I then extended myself to the 3-signal ensemble case in Milestone 5's stretch work.