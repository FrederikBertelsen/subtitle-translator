from ast import List
import os
import secrets
import threading
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.security.api_key import APIKeyHeader
from dotenv import load_dotenv

from main import translate_folder

load_dotenv()
_raw_api_key = os.getenv("API_KEY")
if not _raw_api_key:
    raise ValueError("API_KEY not found in environment variables. Please set it in the .env file.")
# Narrow the type for static checkers: API_KEY is guaranteed to be a str here.
API_KEY: str = _raw_api_key

ENDPOINT_SCRAMBLE = os.getenv("ENDPOINT_SCRAMBLE", "")


app = FastAPI(title="Subtitle Translator")

_api_key_header = APIKeyHeader(name="X-API-Key")


def _require_api_key(key: str = Security(_api_key_header)) -> None:
    # Security dependency may pass `None` in some edge cases; validate first.
    if key is None:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    if not secrets.compare_digest(key, API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key.")


# In-memory job store: job_id -> {status, result, error}
_jobs: dict[str, dict] = {}


def _clean_name_and_split(name: str) -> list[str]:
    for char in "._-'\":()":
        name = name.replace(char, " ")
    return list(set(name.lower().split()))

def _find_media_folder(name: str) -> str | None:
    MEDIA_BASE_PATHS = os.getenv("MEDIA_BASE_PATHS")
    if not MEDIA_BASE_PATHS:
        raise ValueError("MEDIA_BASE_PATH not set in environment variables.")
    base_paths = MEDIA_BASE_PATHS.split(",")

    # Normalize the name by replacing common separators with spaces, and splitting into words
    name_words = _clean_name_and_split(name)

    for base_path in base_paths:
        # look if there is a direct subfolder that contains all the words in the name
        for entry in os.listdir(base_path):
            entry_path = os.path.join(base_path, entry)
            if os.path.isdir(entry_path):
                entry_words = _clean_name_and_split(entry)
                
                matching_words = 0
                for word in name_words:
                    if word in entry_words:
                        matching_words += 1
                
                if matching_words > len(name_words) - 1:
                    return entry_path

    return None

def _run(job_id: str, name: str, lang: str) -> None:
    try:
        path = _find_media_folder(name)
        if path is None:
            raise ValueError(f"Media folder not found for name: {name}")
        
        print(f"Found media folder: {path} for name: {name}")

        summary = translate_folder(path, lang)
        _jobs[job_id] = {"status": "done", "result": summary, "error": None}
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "result": None, "error": str(e)}


@app.post("/translate" if ENDPOINT_SCRAMBLE == "" else f"/{ENDPOINT_SCRAMBLE}", status_code=202)
async def translate(
    name: str = Query(..., description="Media name"),
    lang: str = Query(..., description="Target language code, e.g. 'en', 'da', 'de'"),
    _: None = Depends(_require_api_key),
):
    """Start an async translation job for the given media name. Returns a job_id to poll."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "result": None, "error": None}

    threading.Thread(target=_run, args=(job_id, name, lang), daemon=True).start()

    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, _: None = Depends(_require_api_key)):
    """Poll translation job status. When status is 'done', the result field contains the translated SRT."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": job["status"], "result": job["result"], "error": job["error"]}
