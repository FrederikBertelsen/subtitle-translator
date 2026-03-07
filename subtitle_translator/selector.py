import os
from typing import Dict, List, Optional
from subtitle_translator.language_utils import lang_matches
from subtitle_translator.extractor import list_subtitle_streams
from subtitle_translator.media_utils import count_subtitle_lines
from subtitle_translator import config


def _is_commentary(s: Dict) -> bool:
    title = (s.get("title") or "").lower()
    return "comment" in title or "commentary" in title


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


def _best_in_group(group: List[Dict]) -> Optional[Dict]:
    if not group:
        return None
    return max(group, key=lambda s: s.get("nb_read_packets", 0))


def find_best_english_stream(streams: List[Dict]) -> Optional[Dict]:
    if not streams:
        return None
    english = [s for s in streams if lang_matches(s.get("language"), "en")]
    english_non_forced = [s for s in english if not _is_forced(s) and not _is_commentary(s)]
    if english_non_forced:
        normal = [s for s in english_non_forced if not _is_sdh(s)]
        sdh = [s for s in english_non_forced if _is_sdh(s)]
        for group in (normal, sdh):
            best = _best_in_group(group)
            if best:
                return best
    return None


def find_usable_subtitle_stream(streams: List[Dict]) -> Optional[Dict]:
    if not streams:
        return None

    def usable(s: Dict) -> bool:
        return not _is_forced(s) and not _is_commentary(s)

    english_usable = [s for s in streams if lang_matches(s.get("language"), "en") and usable(s)]
    if english_usable:
        normal = [s for s in english_usable if not _is_sdh(s)]
        sdh = [s for s in english_usable if _is_sdh(s)]
        for group in (normal, sdh):
            best = _best_in_group(group)
            if best:
                return best

    danish_usable = [s for s in streams if lang_matches(s.get("language"), "da") and usable(s)]
    if danish_usable:
        return _best_in_group(danish_usable)

    non_forced = [s for s in streams if usable(s)]
    if non_forced:
        return _best_in_group(non_forced)

    return None


def has_usable_subtitle(path: str) -> bool:
    streams = list_subtitle_streams(path)
    return find_usable_subtitle_stream(streams) is not None


def has_usable_subtitle_of_language(path: str, language: str) -> bool:
    streams = list_subtitle_streams(path)
    for s in streams:
        if _is_forced(s):
            continue
        if lang_matches(s.get("language"), language):
            return True
    return False


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
        commentary_marker = ""
        if _is_sdh(s) and "sdh" not in title_raw.lower():
            sdh_marker = " – SDH"
        if _is_forced(s) and "forced" not in title_raw.lower():
            forced_marker = " – Forced"
        if _is_commentary(s) and "comment" not in title_raw.lower():
            commentary_marker = " – Commentary"
        chosen = " <-- will be used" if best_idx is not None and s["sub_index"] == best_idx else ""
        print(
            f"  {s['sub_index']}: ffprobe_index={s['ffprobe_index']} {s['codec_name']} [{lang}]{default}{title}{sdh_marker}{forced_marker}{commentary_marker}{chosen}"
        )


def pick_external_subtitle(folder: str, files: list[str], video_file: str) -> str | None:
    base = os.path.splitext(video_file)[0]
    srt_files = [f for f in files if f.lower().endswith(config.SUBTITLE_EXTENSION) and f.startswith(base)]

    if not srt_files:
        return None

    def filter_unwanted(candidates: list[str]) -> list[str]:
        filtered = [f for f in candidates if "forced" not in f.lower() and "commentary" not in f.lower()]
        return filtered or candidates

    def pick_most_lines(candidates: list[str]) -> str:
        return max(candidates, key=lambda f: count_subtitle_lines(os.path.join(folder, f)))

    english_subs = [f for f in srt_files if any(pat in f for pat in config.LANGUAGE_PATTERNS_EN)]
    if english_subs:
        return pick_most_lines(filter_unwanted(english_subs))

    danish_subs = [f for f in srt_files if any(pat in f for pat in config.LANGUAGE_PATTERNS_DA)]
    if danish_subs:
        return pick_most_lines(filter_unwanted(danish_subs))

    if len(srt_files) == 1:
        return srt_files[0]

    return None
