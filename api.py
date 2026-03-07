import logging
import os
import secrets
import sys
import threading
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Security, Request
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from main import translate_folder

load_dotenv()

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_orig_stdout = sys.stdout

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(_orig_stdout),
        logging.FileHandler(os.path.join(_LOG_DIR, "logs.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


class _PrintToLog:
    """Redirect sys.stdout so that print() calls anywhere in the app also go to the log file."""
    def write(self, msg: str) -> None:
        msg = msg.rstrip("\n\r")
        if msg.strip():
            log.info(msg)

    def flush(self) -> None:
        pass


sys.stdout = _PrintToLog()  # type: ignore[assignment]

log.info("Subtitle Translator starting up")

_raw_api_key = os.getenv("API_KEY")
if not _raw_api_key:
    raise ValueError("API_KEY not found in environment variables. Please set it in the .env file.")
API_KEY: str = _raw_api_key

TRANSLATION_ENDPOINT_SCRAMBLE = os.getenv("TRANSLATION_ENDPOINT_SCRAMBLE", "translate")
JOB_ENDPOINT_SCRAMBLE = os.getenv("JOB_ENDPOINT_SCRAMBLE", "jobs")

app = FastAPI(title="Subtitle Translator", docs_url=None, redoc_url=None, openapi_url=None)

_cors_env = os.getenv("CORS_ALLOW_ORIGINS")
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_translation_path = f"/{TRANSLATION_ENDPOINT_SCRAMBLE}" if TRANSLATION_ENDPOINT_SCRAMBLE else "/translate"
_job_root = f"/{JOB_ENDPOINT_SCRAMBLE}" if JOB_ENDPOINT_SCRAMBLE else "/jobs"

@app.middleware("http")
async def _restrict_endpoints(request: Request, call_next):
    path = request.url.path.rstrip("/")
    if path == "":
        path = "/"
    if path == _translation_path or path == _job_root or path.startswith(_job_root + "/"):
        return await call_next(request)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

_api_key_header = APIKeyHeader(name="X-API-Key")

def _require_api_key(key: str = Security(_api_key_header)) -> None:
    if key is None:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    if not secrets.compare_digest(key, API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key.")


_jobs: dict[str, dict] = {}


def _clean_name_and_split(name: str) -> list[str]:
    for char in "._-'\":()":
        name = name.replace(char, " ")
    return list(set(name.lower().split()))

def _find_media_folders(name: str, type: str) -> list[str]:
    MEDIA_BASE_PATHS = os.getenv("MEDIA_BASE_PATHS")
    if not MEDIA_BASE_PATHS:
        raise ValueError("MEDIA_BASE_PATH not set in environment variables.")
    base_paths = MEDIA_BASE_PATHS.split(",")

    matched_base_path = None
    for base_path in base_paths:
        if type.lower().strip() in base_path.lower():
            matched_base_path = base_path
            break

    if not matched_base_path:
        raise ValueError(f"Base path for type '{type}' not found.")

    name_words = _clean_name_and_split(name)
    for entry in os.listdir(matched_base_path):
        entry_path = os.path.join(matched_base_path, entry)
        if os.path.isdir(entry_path):
            entry_words = _clean_name_and_split(entry)
            
            matching_words = 0
            for word in name_words:
                if word in entry_words:
                    matching_words += 1
                
            if matching_words > len(name_words) - 1 and matching_words > len(entry_words) - 2:

                season_folders = []
                for sub_entry in os.listdir(entry_path):
                    sub_entry_path = os.path.join(entry_path, sub_entry)
                    if os.path.isdir(sub_entry_path) and "season" in sub_entry.lower():
                        season_folders.append(sub_entry_path)
                    
                if season_folders:
                    return season_folders
                else:
                    return [entry_path]
    return []

def _run(job_id: str, name: str, lang: str, type: str) -> None:
    try:
        paths = _find_media_folders(name, type)
        if not paths:
            raise ValueError(f"Media folder not found for name: {name}")
        
        for path in paths:
            log.info(f"Found media folder: {path} for name: {name}")

        summaries = []
        for path in paths:
            def _on_progress(current: int, total: int) -> None:
                _jobs[job_id]["progress"] = f"{current}/{total}"
            summary = translate_folder(path, lang, on_progress=_on_progress)
            summaries.append(summary)
        _jobs[job_id] = {"status": "done", "result": summaries, "error": None}
    except Exception as e:
        log.error(f"Job {job_id} failed: {e}", exc_info=True)
        _jobs[job_id] = {"status": "failed", "result": None, "error": str(e)}


@app.post(_translation_path, status_code=202)
async def translate(
    name: str = Query(..., description="Media name"),
    lang: str = Query(..., description="Target language code, e.g. 'en', 'da', 'de'"),
    type: str = Query(..., description="Media type"),
    _: None = Depends(_require_api_key),
):
    """Start an async translation job for the given media name. Returns a job_id to poll."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "progress": None, "result": None, "error": None}

    threading.Thread(target=_run, args=(job_id, name, lang, type), daemon=True).start()

    return {"job_id": job_id}


@app.get("{_job_root}/{job_id}")
async def get_job(job_id: str, _: None = Depends(_require_api_key)):
    """Poll translation job status. When status is 'done', the result field contains the translated SRT."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": job["status"], "progress": job.get("progress"), "result": job["result"], "error": job["error"]}
