import argparse
import os
import sys

from extract_subtitle import (
    extract_subtitle_stream_to_srt,
    find_usable_subtitle_stream,
    has_usable_subtitle_of_language,
    list_subtitle_streams,
)
from pocket_logger import PocketLogger
from subtitle import Subtitle
from translate_subtitle import translate_subtitle


def is_media_file(filename: str) -> bool:
    return filename.lower().endswith((".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv"))


def _count_subtitle_lines(path: str) -> int:
    try:
        return len(Subtitle.from_file(path).lines)
    except Exception:
        return 0


def pick_external_subtitle(folder: str, files: list[str], video_file: str) -> str | None:
    """Return the best external .srt path for translation, or None if none are suitable."""
    base = os.path.splitext(video_file)[0]
    srt_files = [f for f in files if f.lower().endswith(".srt") and f.startswith(base)]

    if not srt_files:
        return None

    def filter_unwanted(candidates: list[str]) -> list[str]:
        filtered = [f for f in candidates if "forced" not in f.lower() and "commentary" not in f.lower()]
        return filtered or candidates

    def pick_most_lines(candidates: list[str]) -> str:
        return max(candidates, key=lambda f: _count_subtitle_lines(os.path.join(folder, f)))

    english_subs = [f for f in srt_files if ".en." in f or ".eng." in f or ".english." in f]
    if english_subs:
        return pick_most_lines(filter_unwanted(english_subs))

    danish_subs = [f for f in srt_files if ".da." in f or ".dan." in f or ".danish." in f]
    if danish_subs:
        return pick_most_lines(filter_unwanted(danish_subs))

    # Fall back to a single unrecognised subtitle rather than guessing among many
    if len(srt_files) == 1:
        return srt_files[0]

    return None


def translate_folder(path: str, lang: str) -> dict:
    PocketLogger(
        log_file_path="logs/logs.log", 
        print_time=True,
        print_message=True,
        save_time=True,
        save_message=True,
        create_new_log_file=False,
    )
    
    """Programmatic wrapper for the CLI logic. Translates subtitles in `path` to `lang`.

    Returns a summary dict with per-file results.
    """
    summary: dict = {"path": path, "lang": lang, "videos": {}}

    if not os.path.isdir(path):
        raise ValueError(f"'{path}' is not a valid directory")

    if not lang:
        raise ValueError("target language is required")

    print(f"Starting subtitle translation | folder: {path} | target lang: {lang}")

    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    video_files = [f for f in files if is_media_file(f)]

    if not video_files:
        raise ValueError("No video files found in the folder")

    print(f"Found {len(video_files)} video file(s):\n" + "\n".join(f"  - {f}" for f in video_files))

    project_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(project_dir, "translated_subtitles")
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except Exception:
        backup_dir = None

    for video_file in video_files:
        video_result: dict = {"status": None, "messages": [], "media_output": None, "backup_output": None}
        video_path = os.path.join(path, video_file)
        usable_subtitle_path = None

        def _log(msg: str) -> None:
            pref = f"[{video_file}] {msg}"
            video_result["messages"].append(pref)
            print(pref)

        # 1. CHECK IF ALREADY IN TARGET LANGUAGE (embedded or external)
        try:
            if has_usable_subtitle_of_language(video_path, lang):
                video_result["status"] = "skipped"
                _log(f"Already has embedded subtitle in '{lang}'. Skipping.")
                summary["videos"][video_file] = video_result
                continue
        except Exception:
            # If the check fails, continue to attempt external files
            pass

        if any(f".{lang}." in f for f in files if f.lower().endswith(".srt") and f.startswith(os.path.splitext(video_file)[0])):
            video_result["status"] = "skipped"
            _log(f"Already has external subtitle in '{lang}'. Skipping.")
            summary["videos"][video_file] = video_result
            continue

        # 2. FIND A SUBTITLE TO TRANSLATE — prefer embedded, then external
        try:
            streams = list_subtitle_streams(video_path)
        except RuntimeError as e:
            _log(f"Could not read subtitle streams: {e}. Falling back to external files.")
            streams = []

        if streams:
            _log(f"Found {len(streams)} embedded subtitle stream(s).")
            best_stream = find_usable_subtitle_stream(streams)
            if best_stream:
                extracted_path = os.path.join(path, f"{os.path.splitext(video_file)[0]}.usable.srt")
                try:
                    extract_subtitle_stream_to_srt(video_path, extracted_path, best_stream["sub_index"])
                    usable_subtitle_path = extracted_path
                    _log("Successfully extracted embedded subtitle.")
                except Exception as e:
                    _log(f"Failed to extract embedded subtitle: {e}. Falling back to external files.")
            else:
                _log("No usable (non-forced) embedded stream found. Falling back to external files.")
        else:
            _log("No embedded subtitle streams found. Looking for external .srt files...")

        if not usable_subtitle_path:
            base = os.path.splitext(video_file)[0]
            srt_files = [f for f in files if f.lower().endswith(".srt") and f.startswith(base)]
            if srt_files:
                _log(f"Found {len(srt_files)} external .srt file(s): {srt_files}")
            else:
                video_result["status"] = "failed"
                _log("No external .srt files found.")
                summary["videos"][video_file] = video_result
                continue
            result = pick_external_subtitle(path, files, video_file)
            if result is None:
                video_result["status"] = "failed"
                _log("No usable subtitle found.")
                summary["videos"][video_file] = video_result
                continue
            usable_subtitle_path = os.path.join(path, result)
            _log(f"Selected external subtitle: {result}")

        # 3. TRANSLATE
        is_extracted = usable_subtitle_path == os.path.join(path, f"{os.path.splitext(video_file)[0]}.usable.srt")
        try:
            subtitle = Subtitle.from_file(usable_subtitle_path)
        except ValueError as e:
            video_result["status"] = "failed"
            _log(f"Invalid subtitle file: {e}")
            summary["videos"][video_file] = video_result
            continue

        _log(f"Translating to '{lang}' ...")
        try:
            translated_subtitle = translate_subtitle(subtitle, lang)
        except Exception as e:
            video_result["status"] = "failed"
            _log(f"Translation failed: {e}")
            summary["videos"][video_file] = video_result
            continue

        # Attempt to save into the media folder, and always write a local backup
        media_output_path = os.path.join(path, f"{os.path.splitext(video_file)[0]}.{lang}.srt")

        saved_to_media = False
        saved_to_backup = False

        try:
            translated_subtitle.to_srt_file(media_output_path)
            saved_to_media = True
            _log(f"Saved translated subtitle to media folder: {media_output_path}")
            video_result["media_output"] = media_output_path
        except Exception as e:
            _log(f"Could not save subtitle to media folder: {e}")

        if backup_dir:
            backup_output_path = os.path.join(backup_dir, f"{os.path.splitext(video_file)[0]}.{lang}.srt")
            try:
                translated_subtitle.to_srt_file(backup_output_path)
                saved_to_backup = True
                _log(f"Saved translated subtitle to local backup: {backup_output_path}")
                video_result["backup_output"] = backup_output_path
            except Exception as e:
                _log(f"Failed to save local backup '{backup_output_path}': {e}")

        if not (saved_to_media or saved_to_backup):
            video_result["status"] = "failed"
            _log("Translation failed: could not save subtitle to media folder or local backup.")
            summary["videos"][video_file] = video_result
            continue

        if is_extracted:
            if (saved_to_media or saved_to_backup):
                try:
                    os.remove(usable_subtitle_path)
                    _log("Deleted temporary extracted subtitle.")
                except Exception as e:
                    _log(f"Warning: failed to delete temporary extracted subtitle: {e}")
            else:
                _log(f"Leaving temporary extracted subtitle at {usable_subtitle_path} (save failed).")

        video_result["status"] = "done"
        summary["videos"][video_file] = video_result

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Translate subtitles using OpenAI API.")
    parser.add_argument("path", help="media folder path")
    parser.add_argument("--lang", help="Language subtitles should be translated to (e.g. 'en', 'de', 'fr').")
    args = parser.parse_args(argv)
    try:
        summary = translate_folder(args.path, args.lang)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Print a concise summary for CLI users
    for vf, info in summary.get("videos", {}).items():
        status = info.get("status")
        print(f"{vf}: {status}")

if __name__ == "__main__":
    main()
