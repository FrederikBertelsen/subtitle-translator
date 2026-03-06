import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from utils import lang_matches


def _check_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} not found in PATH; please install ffmpeg/ffprobe")
    return path


def list_subtitle_streams(path: str) -> List[Dict]:
    _check_bin("ffprobe")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_type,codec_name,codec_long_name,disposition:stream_tags=language,title",
        "-of",
        "json",
        path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr.strip()}")
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams", [])
    out = []
    for i, s in enumerate(streams):
        tags = s.get("tags") or {}
        out.append(
            {
                "ffprobe_index": s.get("index"),
                "sub_index": i,
                "codec_name": s.get("codec_name"),
                "codec_long_name": s.get("codec_long_name"),
                "language": tags.get("language"),
                "title": tags.get("title"),
                "disposition": s.get("disposition", {}),
            }
        )
    return out


def print_subtitle_streams(path: str) -> None:
    streams = list_subtitle_streams(path)
    if not streams:
        print("No subtitle streams found.")
        return
    best = find_usable_subtitle_stream(streams)
    best_idx = best["sub_index"] if best else None
    print("Subtitle streams:")
    for s in streams:
        lang = s["language"] or "und"
        title_raw = s.get("title") or ""
        title = f" – {title_raw}" if title_raw else ""
        default = " (default)" if s.get("disposition", {}).get("default") else ""
        sdh_marker = ""
        forced_marker = ""
        if _is_sdh(s) and "sdh" not in title_raw.lower():
            sdh_marker = " – SDH"
        if _is_forced(s) and "forced" not in title_raw.lower():
            forced_marker = " – Forced"
        chosen = " <-- will be used" if best_idx is not None and s["sub_index"] == best_idx else ""
        print(
            f"  {s['sub_index']}: ffprobe_index={s['ffprobe_index']} {s['codec_name']} [{lang}]{default}{title}{sdh_marker}{forced_marker}{chosen}"
        )


def _is_english_lang(lang: Optional[str]) -> bool:
    if not lang:
        return False
    l = lang.lower()
    return l.startswith("en") or l in ("eng", "english")


def _is_forced(s: Dict) -> bool:
    disp = s.get("disposition", {}) or {}
    title = (s.get("title") or "").lower()
    codec_long = (s.get("codec_long_name") or "").lower()
    return bool(disp.get("forced")) or "forced" in title or "forced" in codec_long


def _is_sdh(s: Dict) -> bool:
    title = (s.get("title") or "").lower()
    codec_long = (s.get("codec_long_name") or "").lower()
    return (
        "sdh" in title
        or "sdh" in codec_long
        or "subtitles for the deaf" in title
        or "hard of hearing" in title
        or "hearing impaired" in title
    )


def find_best_english_stream(streams: List[Dict]) -> Optional[Dict]:
    if not streams:
        return None
    english = [s for s in streams if lang_matches(s.get("language"), "en")]
    # ignore forced tracks entirely
    english_non_forced = [s for s in english if not _is_forced(s)]
    if english_non_forced:
        # prefer normal subtitles (not SDH), then SDH
        normal = [s for s in english_non_forced if not _is_sdh(s)]
        sdh = [s for s in english_non_forced if _is_sdh(s)]
        for group in (normal, sdh):
            if not group:
                continue
            # prefer default among group
            for s in group:
                if s.get("disposition", {}).get("default"):
                    return s
            return group[0]

    # no usable (non-forced) English subtitles found
    return None


def find_usable_subtitle_stream(streams: List[Dict]) -> Optional[Dict]:
    """
    Select a usable subtitle stream from `streams`.

    Rules:
    - Never return a forced subtitle.
    - Prefer non-forced English subtitles (prefer normal over SDH, prefer default within a group).
    - If no non-forced English exists, pick the first non-forced subtitle (prefer default).
    - Return None if no non-forced subtitles exist.
    """
    if not streams:
        return None

    # Prefer non-forced English subtitles
    english_non_forced = [s for s in streams if lang_matches(s.get("language"), "en") and not _is_forced(s)]
    if english_non_forced:
        normal = [s for s in english_non_forced if not _is_sdh(s)]
        sdh = [s for s in english_non_forced if _is_sdh(s)]
        for group in (normal, sdh):
            if not group:
                continue
            for s in group:
                if s.get("disposition", {}).get("default"):
                    return s
            return group[0]

    # Second priority: non-forced Danish subtitles
    danish_non_forced = [s for s in streams if lang_matches(s.get("language"), "da") and not _is_forced(s)]
    if danish_non_forced:
        for s in danish_non_forced:
            if s.get("disposition", {}).get("default"):
                return s
        return danish_non_forced[0]

    # Fallback: first non-forced subtitle (prefer default)
    non_forced = [s for s in streams if not _is_forced(s)]
    if non_forced:
        for s in non_forced:
            if s.get("disposition", {}).get("default"):
                return s
        return non_forced[0]

    # All subtitle streams are forced or no subtitles at all
    return None


def has_usable_subtitle(path: str) -> bool:
    """Return True if a usable (non-forced) subtitle stream exists in `path`."""
    streams = list_subtitle_streams(path)
    return find_usable_subtitle_stream(streams) is not None





def has_usable_subtitle_of_language(path: str, language: str) -> bool:
    """Return True if there's a usable (non-forced) subtitle of `language` in `path`.

    `language` can be an ISO code (e.g., "en") or a name (e.g., "english").
    Forced subtitles are ignored.
    """
    streams = list_subtitle_streams(path)
    for s in streams:
        if _is_forced(s):
            continue
        if lang_matches(s.get("language"), language):
            return True
    return False


def extract_usable_subtitle_as_srt(input_path: str, output_path: Optional[str] = None) -> str:
    """Extract a usable (non-forced) subtitle stream to SRT and return the output path.

    Prefers non-forced English; if none, falls back to the first non-forced subtitle.
    Raises RuntimeError if there are no subtitle streams or no non-forced subtitles.
    """
    streams = list_subtitle_streams(input_path)
    if not streams:
        raise RuntimeError("No subtitle streams found")
    best = find_usable_subtitle_stream(streams)
    if not best:
        raise RuntimeError("No usable (non-forced) subtitle stream found")
    out = output_path or f"{Path(input_path).stem}.usable.srt"
    extract_subtitle_stream_to_srt(input_path, out, best["sub_index"])
    return out


def extract_subtitle_stream_to_srt(input_path: str, output_path: str, sub_index: int) -> None:
    _check_bin("ffmpeg")
    streams = list_subtitle_streams(input_path)
    if sub_index < 0 or sub_index >= len(streams):
        raise IndexError("subtitle sub_index out of range")
    codec = (streams[sub_index]["codec_name"] or "").lower()
    image_codecs = {"dvd_subtitle", "hdmv_pgs_subtitle", "pgs", "vobsub"}
    if codec in image_codecs:
        raise RuntimeError("Image-based subtitle codecs (VobSub/PGS) cannot be converted to SRT with ffmpeg; use OCR.")
    cmd = ["ffmpeg", "-y", "-i", input_path, "-map", f"0:s:{sub_index}", "-c:s", "srt", output_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.strip()}")

