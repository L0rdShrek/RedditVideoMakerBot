"""
Lightweight HTTP API for the Reddit Video Maker Bot.

Designed for integration with workflow automation tools like n8n.
Provides endpoints to trigger video generation, check job status,
and manage configuration.

Usage:
    python api.py [--host 0.0.0.0] [--port 5000]
"""

import argparse
import math
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomlkit
from flask import Flask, jsonify, request

from reddit.subreddit import get_subreddit_threads
from utils import settings
from utils.cleanup import cleanup
from utils.ffmpeg_install import ffmpeg_install
from utils.id import extract_id
from video_creation.background import (
    chop_background,
    download_background_audio,
    download_background_video,
    get_background_config,
)
from video_creation.final_video import make_final_video
from video_creation.screenshot_downloader import get_screenshots_of_reddit_posts
from video_creation.voices import save_text_to_mp3

app = Flask(__name__)

# In-memory job store
jobs: dict[str, dict[str, Any]] = {}


def _init_config() -> bool:
    """Load config.toml and initialize settings."""
    directory = Path().absolute()
    config = settings.check_toml(
        f"{directory}/utils/.config.template.toml", f"{directory}/config.toml"
    )
    return config is not False


def _run_video_job(job_id: str, post_id: str | None = None, config_overrides: dict | None = None) -> None:
    """Run video generation in a background thread."""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        # Apply config overrides if provided
        if config_overrides:
            _apply_config_overrides(config_overrides)

        reddit_object = get_subreddit_threads(post_id)
        reddit_id = extract_id(reddit_object)
        jobs[job_id]["reddit_id"] = reddit_id

        length, number_of_comments = save_text_to_mp3(reddit_object)
        length = math.ceil(length)
        get_screenshots_of_reddit_posts(reddit_object, number_of_comments)

        bg_config = {
            "video": get_background_config("video"),
            "audio": get_background_config("audio"),
        }
        download_background_video(bg_config["video"])
        download_background_audio(bg_config["audio"])
        chop_background(bg_config, length, reddit_object)
        make_final_video(number_of_comments, length, reddit_object, bg_config)

        # Find the output file
        results_dir = Path("results") / reddit_object["thread_title"]
        output_files = list(results_dir.glob("*.mp4")) if results_dir.exists() else []

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        jobs[job_id]["result"] = {
            "reddit_id": reddit_id,
            "thread_title": reddit_object.get("thread_title", ""),
            "number_of_comments": number_of_comments,
            "video_length_seconds": length,
            "output_files": [str(f) for f in output_files],
        }

        cleanup(reddit_id)

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        jobs[job_id]["error"] = str(e)


def _apply_config_overrides(overrides: dict) -> None:
    """Apply runtime config overrides to settings.config."""
    for section, values in overrides.items():
        if section in settings.config:
            if isinstance(values, dict):
                for key, val in values.items():
                    if isinstance(settings.config[section], dict) and key in settings.config[section]:
                        if isinstance(val, dict):
                            for sub_key, sub_val in val.items():
                                settings.config[section][key][sub_key] = sub_val
                        else:
                            settings.config[section][key] = val


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint for n8n monitoring."""
    return jsonify({"status": "ok", "version": "3.4.0"})


@app.route("/api/generate", methods=["POST"])
def generate_video():
    """
    Trigger video generation.

    JSON body (all fields optional):
        {
            "post_id": "abc123",
            "subreddit": "AskReddit",
            "config": {
                "settings": {
                    "theme": "dark",
                    "storymode": false
                }
            }
        }

    Returns a job ID for status polling.
    """
    data = request.get_json(silent=True) or {}
    post_id = data.get("post_id")
    config_overrides = data.get("config")

    # If subreddit is provided, override it in config
    if data.get("subreddit") and not config_overrides:
        config_overrides = {"reddit": {"thread": {"subreddit": data["subreddit"]}}}
    elif data.get("subreddit") and config_overrides:
        config_overrides.setdefault("reddit", {}).setdefault("thread", {})["subreddit"] = data["subreddit"]

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "post_id": post_id,
    }

    thread = threading.Thread(target=_run_video_job, args=(job_id, post_id, config_overrides))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str):
    """Check the status of a video generation job."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List all jobs, optionally filtered by status."""
    status_filter = request.args.get("status")
    if status_filter:
        filtered = {k: v for k, v in jobs.items() if v["status"] == status_filter}
        return jsonify(list(filtered.values()))
    return jsonify(list(jobs.values()))


@app.route("/api/config", methods=["GET"])
def get_config():
    """Return the current configuration (with secrets redacted)."""
    config = tomlkit.loads(Path("config.toml").read_text())

    # Redact sensitive values
    if "reddit" in config and "creds" in config["reddit"]:
        for key in ["client_secret", "password"]:
            if key in config["reddit"]["creds"]:
                config["reddit"]["creds"][key] = "***REDACTED***"
    if "settings" in config and "tts" in config["settings"]:
        for key in ["tiktok_sessionid", "elevenlabs_api_key", "openai_api_key"]:
            if key in config["settings"]["tts"]:
                config["settings"]["tts"][key] = "***REDACTED***"

    return jsonify(dict(config))


@app.route("/api/config", methods=["PATCH"])
def update_config():
    """
    Update configuration values.

    JSON body example:
        {
            "reddit": {"thread": {"subreddit": "AskReddit"}},
            "settings": {"theme": "light"}
        }
    """
    data = request.get_json(silent=True) or {}
    config_path = Path("config.toml")
    config = tomlkit.loads(config_path.read_text())

    def deep_update(base, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                deep_update(base[key], value)
            else:
                base[key] = value

    deep_update(config, data)
    config_path.write_text(tomlkit.dumps(config))

    # Reload settings
    _init_config()

    return jsonify({"status": "updated"})


@app.route("/api/results", methods=["GET"])
def list_results():
    """List all generated videos."""
    results_dir = Path("results")
    if not results_dir.exists():
        return jsonify([])

    videos = []
    for folder in results_dir.iterdir():
        if folder.is_dir():
            mp4_files = list(folder.glob("*.mp4"))
            for mp4 in mp4_files:
                videos.append({
                    "title": folder.name,
                    "file": str(mp4),
                    "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(
                        mp4.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })

    return jsonify(videos)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reddit Video Maker Bot API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    args = parser.parse_args()

    ffmpeg_install()
    if not _init_config():
        print("Error: config.toml not found or invalid. Please run main.py first to generate it.")
        sys.exit(1)

    print(f"Starting API server on {args.host}:{args.port}")
    print("Use this server with n8n HTTP Request nodes.")
    app.run(host=args.host, port=args.port, debug=False)
