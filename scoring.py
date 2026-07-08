"""
scoring.py — combines Signal 1 (LLM) and Signal 2 (stylometric) into a
single confidence score, and maps that score to an attribution category
and transparency label, per planning.md.
"""

AI_THRESHOLD = 0.70       # >= this -> likely_ai (high confidence)
HUMAN_THRESHOLD = 0.35    # <= this -> likely_human (high confidence)

LABELS = {
    "likely_ai": (
        "This piece shows strong signs of being AI-generated. Multiple "
        "independent checks agree it's likely not written by a human."
    ),
    "uncertain": (
        "We can't confidently tell whether this piece is AI-generated or "
        "human-written. The signals we checked were mixed or inconclusive "
        "— treat this as inconclusive, not a verdict."
    ),
    "likely_human": (
        "This piece shows strong signs of human authorship. Our checks "
        "found no significant indicators of AI generation."
    ),
}


def combine_scores(llm_score: float, stylometric_score: float) -> float:
    """
    Weighted combination: LLM signal weighted higher (0.6) since it
    captures meaning; stylometric weighted 0.4 since it's structural only.

    If the two signals disagree sharply (>0.4 apart), that disagreement
    itself signals genuine uncertainty, so the raw score is pulled 30%
    of the way toward 0.5 rather than trusting either signal fully.
    """
    raw = 0.6 * llm_score + 0.4 * stylometric_score

    disagreement = abs(llm_score - stylometric_score)
    if disagreement > 0.4:
        raw = raw + (0.5 - raw) * 0.3

    return round(max(0.0, min(1.0, raw)), 3)


def combine_scores_ensemble(llm_score: float, stylometric_score: float, phrase_score: float) -> float:
    """
    Stretch: ensemble detection across 3 signals.

    Weights: LLM 0.5, stylometric 0.3, phrase-pattern 0.2. LLM keeps the
    largest weight as the most holistic signal; stylometric second since
    it's a broad statistical signature; phrase-pattern lowest since it's
    the easiest to evade (paraphrasing defeats it) and most prone to
    false positives on formal human writing.

    Voting cross-check: each signal casts an informal "vote" (ai / human /
    neutral) based on its own value crossing 0.7 / 0.3. If the weighted
    score disagrees with what 2+ signals voted, that's treated as spread
    (see below) and the score is pulled toward 0.5 rather than trusted.
    """
    raw = 0.5 * llm_score + 0.3 * stylometric_score + 0.2 * phrase_score

    scores = [llm_score, stylometric_score, phrase_score]
    spread = max(scores) - min(scores)
    if spread > 0.5:
        raw = raw + (0.5 - raw) * 0.3

    return round(max(0.0, min(1.0, raw)), 3)


def get_attribution(confidence: float) -> str:
    if confidence >= AI_THRESHOLD:
        return "likely_ai"
    elif confidence <= HUMAN_THRESHOLD:
        return "likely_human"
    else:
        return "uncertain"


def get_label(confidence: float) -> str:
    return LABELS[get_attribution(confidence)]