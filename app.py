import os
import uuid
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

import storage
import signals
import scoring

load_dotenv()
storage.init_db()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
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

    # Stretch: ensemble detection (3rd signal)
    phrase_result = signals.ai_phrase_signal(text)
    phrase_score = phrase_result["score"]

    confidence = scoring.combine_scores_ensemble(llm_score, stylometric_score, phrase_score)
    attribution = scoring.get_attribution(confidence)
    label = scoring.get_label(confidence)

    # Stretch: provenance certificate — surface certified status alongside the label
    certified = storage.has_certificate(creator_id)
    if certified:
        label = label + " This creator holds an active Verified Human certificate."

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
        "creator_certified": certified,
        "signals": {
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
            "phrase_pattern_score": phrase_score,
        },
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(force=True, silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return jsonify({"error": "content_id and creator_reasoning are both required"}), 400

    if not storage.content_exists(content_id):
        return jsonify({"error": f"no classification found for content_id {content_id}"}), 404

    storage.log_appeal(content_id, creator_reasoning)

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received. Your content has been marked for human review.",
    })


@app.route("/certify", methods=["POST"])
def certify():
    data = request.get_json(force=True, silent=True) or {}
    creator_id = data.get("creator_id")

    if not creator_id:
        return jsonify({"error": "creator_id is required"}), 400

    eligible, reason, qualifying_count = storage.eligibility_check(creator_id)

    if not eligible:
        return jsonify({
            "creator_id": creator_id,
            "certified": False,
            "reason": reason,
        }), 200

    basis = f"{qualifying_count} submissions scoring <= {storage.CERT_CONFIDENCE_CEILING} confidence, no open appeals"
    storage.issue_certificate(creator_id, basis)

    return jsonify({
        "creator_id": creator_id,
        "certified": True,
        "basis": basis,
    })


@app.route("/certificate/<creator_id>", methods=["GET"])
def get_certificate(creator_id):
    cert = storage.get_certificate(creator_id)
    if not cert:
        return jsonify({"creator_id": creator_id, "certified": False}), 404
    return jsonify({"creator_id": creator_id, "certified": True, **cert})


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": storage.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)