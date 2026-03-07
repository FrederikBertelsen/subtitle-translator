import os
from subtitle_translator.subtitle import Subtitle
from subtitle_translator.translator import translate_subtitle
from subtitle_translator.extractor import list_subtitle_streams, extract_subtitle_stream_to_srt
from subtitle_translator.selector import (
    find_usable_subtitle_stream,
    has_usable_subtitle_of_language,
    pick_external_subtitle,
)
from subtitle_translator.media_utils import is_media_file
from subtitle_translator import config


def estimate_folder_progress_units(path: str) -> int:
    if not os.path.isdir(path):
        raise ValueError(f"'{path}' is not a valid directory")

    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    video_files = [f for f in files if is_media_file(f)]

    if not video_files:
        raise ValueError("No video files found in the folder")

    total_units = 0
    for video_file in video_files:
        base = os.path.splitext(video_file)[0]
        srt_files = [f for f in files if f.lower().endswith(config.SUBTITLE_EXTENSION) and f.startswith(base)]
        for srt_file in srt_files:
            try:
                total_units += len(Subtitle.from_file(os.path.join(path, srt_file)).lines)
                break
            except Exception:
                continue

    return max(total_units, len(video_files))


def translate_folder(path: str, lang: str, on_progress=None) -> dict:
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
    backup_dir = os.path.join(project_dir, config.BACKUP_DIR_NAME)
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except Exception:
        backup_dir = None

    completed_units = 0

    for video_file in video_files:
        video_result: dict = {"status": None, "messages": [], "media_output": None, "backup_output": None}
        video_path = os.path.join(path, video_file)
        usable_subtitle_path = None
        subtitle = None
        file_total_units = 1

        def _log(msg: str) -> None:
            pref = f"[{video_file}] {msg}"
            video_result["messages"].append(pref)
            print(pref)

        def _advance_file_progress() -> None:
            nonlocal completed_units
            completed_units += file_total_units
            if on_progress:
                on_progress(completed_units)

        try:
            if has_usable_subtitle_of_language(video_path, lang):
                video_result["status"] = "skipped"
                _log(f"Already has embedded subtitle in '{lang}'. Skipping.")
                summary["videos"][video_file] = video_result
                _advance_file_progress()
                continue
        except Exception:
            pass

        if any(f".{lang}." in f for f in files if f.lower().endswith(config.SUBTITLE_EXTENSION) and f.startswith(os.path.splitext(video_file)[0])):
            video_result["status"] = "skipped"
            _log(f"Already has external subtitle in '{lang}'. Skipping.")
            summary["videos"][video_file] = video_result
            _advance_file_progress()
            continue

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
            srt_files = [f for f in files if f.lower().endswith(config.SUBTITLE_EXTENSION) and f.startswith(base)]
            if srt_files:
                _log(f"Found {len(srt_files)} external .srt file(s): {srt_files}")
            else:
                video_result["status"] = "failed"
                _log("No external .srt files found.")
                summary["videos"][video_file] = video_result
                _advance_file_progress()
                continue
            result = pick_external_subtitle(path, files, video_file)
            if result is None:
                video_result["status"] = "failed"
                _log("No usable subtitle found.")
                summary["videos"][video_file] = video_result
                _advance_file_progress()
                continue
            usable_subtitle_path = os.path.join(path, result)
            _log(f"Selected external subtitle: {result}")

        is_extracted = usable_subtitle_path == os.path.join(path, f"{os.path.splitext(video_file)[0]}.usable.srt")
        try:
            subtitle = Subtitle.from_file(usable_subtitle_path)
            file_total_units = max(len(subtitle.lines), 1)
        except ValueError as e:
            video_result["status"] = "failed"
            _log(f"Invalid subtitle file: {e}")
            summary["videos"][video_file] = video_result
            _advance_file_progress()
            continue

        _log(f"Translating to '{lang}' ...")
        try:
            def _on_file_progress(current_units: int, _total_units: int) -> None:
                if on_progress:
                    on_progress(completed_units + current_units)

            translated_subtitle = translate_subtitle(subtitle, lang, on_progress=_on_file_progress)
        except Exception as e:
            video_result["status"] = "failed"
            _log(f"Translation failed: {e}")
            summary["videos"][video_file] = video_result
            _advance_file_progress()
            continue

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
            _advance_file_progress()
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
        _advance_file_progress()

    return summary
