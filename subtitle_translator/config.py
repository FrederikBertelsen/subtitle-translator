import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o")
COST_PER_1K_INPUT = float(os.getenv("DEFAULT_MODEL_COST_PER_1K_TOKENS_INPUT", "0.0025"))
COST_PER_1K_OUTPUT = float(os.getenv("DEFAULT_MODEL_COST_PER_1K_TOKENS_OUTPUT", "0.01"))
MAX_REQUEST_COST = float(os.getenv("MAX_REQUEST_COST", "1"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "2"))

API_KEY = os.getenv("API_KEY")
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS")
TRANSLATION_ENDPOINT_SCRAMBLE = os.getenv("TRANSLATION_ENDPOINT_SCRAMBLE", "translate")
JOB_ENDPOINT_SCRAMBLE = os.getenv("JOB_ENDPOINT_SCRAMBLE", "jobs")
MEDIA_BASE_PATHS = os.getenv("MEDIA_BASE_PATHS")

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv")
SUBTITLE_EXTENSION = ".srt"

LANGUAGE_PATTERNS_EN = (".en.", ".eng.", ".english.")
LANGUAGE_PATTERNS_DA = (".da.", ".dan.", ".danish.")

FILTER_KEYWORDS = ("forced", "commentary", "sdh")

BACKUP_DIR_NAME = "translated_subtitles"

DEFAULT_SYS_PROMPT = (
    "You are a professional translator. Respond only with the content translated. "
    "Do not add explanations, comments, or any extra text."
)

DEFAULT_USER_PROMPT = (
    "Please respect the original meaning, maintain the original format, "
    "and rewrite the following content in {target_language}.\n\n{context}"
)

CONTEXT_TEMPLATE = (
    "This is a subtitle file. Each line is formatted as INDEX|TEXT, "
    "where INDEX is the subtitle line number and TEXT is the dialogue. "
    "And \"<br>\" is a line break within a subtitle. "
    "Translate ONLY the TEXT portion of each line. Keep the INDEX and | separator and <br> line breaks unchanged. "
    "The INDEX numbers may not start at 1 — preserve the exact index numbers from the input in your response.\n\n"
    "CRITICAL REQUIREMENTS:\n"
    "1. You MUST translate every single line without changing the meaning\n"
    "2. Keep the exact format: INDEX|translated text\n"
    "3. If a line contains only sounds/exclamations, still translate them appropriately"
)
