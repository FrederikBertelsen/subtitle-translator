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

from subtitle_translator.translation_service import estimate_folder_progress_units, translate_folder
from subtitle_translator.media_utils import find_media_folders
from subtitle_translator import config

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
    def write(self, msg: str) -> None:
        msg = msg.rstrip("\n\r")
        if msg.strip():
            log.info(msg)

    def flush(self) -> None:
        pass


sys.stdout = _PrintToLog()

log.info("Subtitle Translator starting up")

if not config.API_KEY:
    raise ValueError("API_KEY not found in environment variables. Please set it in the .env file.")

app = FastAPI(title="Subtitle Translator", docs_url=None, redoc_url=None, openapi_url=None)

if config.CORS_ALLOW_ORIGINS:
    _cors_origins = [o.strip() for o in config.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
else:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_translation_path = f"/{config.TRANSLATION_ENDPOINT_SCRAMBLE}" if config.TRANSLATION_ENDPOINT_SCRAMBLE else "/translate"
_job_root = f"/{config.JOB_ENDPOINT_SCRAMBLE}" if config.JOB_ENDPOINT_SCRAMBLE else "/jobs"


@app.middleware("http")
async def _restrict_endpoints(request: Request, call_next):
    path = request.url.path.rstrip("/")
    if path == "":
        path = "/"
    if path == _translation_path or path.startswith(_translation_path + "/") or path == _job_root or path.startswith(_job_root + "/"):
        return await call_next(request)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


_api_key_header = APIKeyHeader(name="X-API-Key")


def _require_api_key(key: str = Security(_api_key_header)) -> None:
    if key is None or config.API_KEY is None:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    if not secrets.compare_digest(key, config.API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key.")


_jobs: dict[str, dict] = {}


def _run(job_id: str, name: str, lang: str, type: str) -> None:
    try:
        paths = find_media_folders(name, type)
        if not paths:
            raise ValueError(f"Media folder not found for name: {name}")
        
        for path in paths:
            log.info(f"Found media folder: {path} for name: {name}")

        folder_progress_units = [estimate_folder_progress_units(path) for path in paths]
        total_work_units = sum(folder_progress_units)
        completed_work_units = 0

        summaries = []
        for path, folder_total_units in zip(paths, folder_progress_units):

            def _on_progress(current_units: int) -> None:
                global_current = min(total_work_units, completed_work_units + max(0, current_units))
                _jobs[job_id]["progress"] = f"{global_current}/{total_work_units}"

            _jobs[job_id]["progress"] = f"{completed_work_units}/{total_work_units}"
            summary = translate_folder(path, lang, on_progress=_on_progress)
            summaries.append(summary)
            completed_work_units += folder_total_units
            _jobs[job_id]["progress"] = f"{completed_work_units}/{total_work_units}"
        _jobs[job_id] = {
            "status": "done",
            "progress": f"{total_work_units}/{total_work_units}",
            "result": summaries,
            "error": None,
        }
    except Exception as e:
        log.error(f"Job {job_id} failed: {e}", exc_info=True)
        _jobs[job_id] = {
            "status": "failed",
            "progress": _jobs.get(job_id, {}).get("progress"),
            "result": None,
            "error": str(e),
        }


@app.post(_translation_path, status_code=202)
async def translate(
    name: str = Query(..., description="Media name"),
    lang: str = Query(..., description="Target language code, e.g. 'en', 'da', 'de'"),
    type: str = Query(..., description="Media type"),
    _: None = Depends(_require_api_key),
):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending", "progress": None, "result": None, "error": None}

    threading.Thread(target=_run, args=(job_id, name, lang, type), daemon=True).start()

    return {"job_id": job_id}


@app.get(f"{_job_root}/{{job_id}}")
async def get_job(job_id: str, _: None = Depends(_require_api_key)):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": job["status"], "progress": job.get("progress"), "result": job["result"], "error": job["error"]}
