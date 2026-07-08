import os
import uuid
from flask import Flask, request, jsonify
from dotenv import load_dotenv

import storage
import signals

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

    # --- Milestone 3: only signal 1 is wired in. Confidence/label are placeholders
    # until Milestone 4 adds signal 2 and real scoring. ---
    llm_result = signals.llm_signal(text)
    llm_score = llm_result["score"]

    placeholder_confidence = llm_score
    if placeholder_confidence >= 0.7:
        attribution = "likely_ai"
    elif placeholder_confidence <= 0.35:
        attribution = "likely_human"
    else:
        attribution = "uncertain"
    placeholder_label = f"[placeholder label — real label lands in Milestone 5] attribution={attribution}"

    storage.log_classification(
        content_id=content_id,
        creator_id=creator_id,
        text=text,
        attribution=attribution,
        confidence=placeholder_confidence,
        llm_score=llm_score,
        stylometric_score=None,  # added in Milestone 4
        label=placeholder_label,
    )

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": placeholder_confidence,
        "label": placeholder_label,
    })


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": storage.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)