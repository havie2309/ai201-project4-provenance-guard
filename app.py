import os
import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import storage
import signals
import scoring

load_dotenv()
storage.init_db()

app = Flask(__name__)


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id", "unknown")

    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text field is required and must be a non-empty string"}), 400

    content_id = str(uuid.uuid4())

    # --- Both signals now wired in ---
    llm_result = signals.llm_signal(text)
    llm_score = llm_result["score"]

    stylo_result = signals.stylometric_signal(text)
    stylometric_score = stylo_result["score"]

    confidence = scoring.combine_scores(llm_score, stylometric_score)
    attribution = scoring.get_attribution(confidence)
    label = scoring.get_label(confidence)

    storage.log_classification(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        attribution=attribution,
        confidence=confidence,
        llm_score=llm_score,
        stylometric_score=stylometric_score,
        label=label,
    )

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signals": {
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
        },
    })


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": storage.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)