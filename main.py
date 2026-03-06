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


logger = PocketLogger(
    log_file_path="logs/logs.log", 
    print_time=True,
    print_message=True,
    save_time=True,
    save_message=True,
    create_new_log_file=False,
)


def is_movie_file(filename: str) -> bool:
    return filename.lower().endswith((".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv"))

def _fmt_stream(s: dict) -> str:
    lang = s.get("language") or "und"
    title = f' "{s["title"]}"' if s.get("title") else ""
    flags = [k for k in ("default", "forced") if s.get("disposition", {}).get(k)]
    flag_str = f" ({', '.join(flags)})" if flags else ""
    return f"{s['sub_index']}: {s['codec_name']} [{lang}]{title}{flag_str}"


def pick_external_subtitle(files: list[str], video_file: str) -> str | None:
    """Return the best external .srt path for translation, or None if none are suitable."""
    base = os.path.splitext(video_file)[0]
    srt_files = [f for f in files if f.lower().endswith(".srt") and f.startswith(base)]

    if not srt_files:
        return None

    def best(candidates: list[str]) -> list[str]:
        filtered = [f for f in candidates if "forced" not in f.lower() and "commentary" not in f.lower()]
        return filtered or candidates

    english_subs = [f for f in srt_files if ".en." in f or ".eng." in f or ".english." in f]
    if english_subs:
        return best(english_subs)[0]

    danish_subs = [f for f in srt_files if ".da." in f or ".dan." in f or ".danish." in f]
    if danish_subs:
        return best(danish_subs)[0]

    # Fall back to a single unrecognised subtitle rather than guessing among many
    if len(srt_files) == 1:
        return srt_files[0]

    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Translate subtitles using OpenAI API.")
    parser.add_argument("path", help="media folder path")
    parser.add_argument("--lang", help="Language subtitles should be translated to (e.g. 'en', 'de', 'fr').")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.path):
        print(f"Error: '{args.path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    if not args.lang:
        print("Error: --lang is required (e.g. --lang en).", file=sys.stderr)
        sys.exit(1)

    print(f"Starting subtitle translation | folder: {args.path} | target lang: {args.lang}")

    files = [f for f in os.listdir(args.path) if os.path.isfile(os.path.join(args.path, f))]
    video_files = [f for f in files if is_movie_file(f)]

    if not video_files:
        print("No video files found. Please ensure there are valid video files in the folder.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(video_files)} video file(s):\n" + "\n".join(f"  - {f}" for f in video_files))

    for video_file in video_files:
        video_path = os.path.join(args.path, video_file)
        usable_subtitle_path = None

        # 1. CHECK IF ALREADY IN TARGET LANGUAGE (embedded or external)
        if has_usable_subtitle_of_language(video_path, args.lang):
            print(f"[{video_file}] Already has embedded subtitle in '{args.lang}'. Skipping.")
            continue

        if any(f".{args.lang}." in f for f in files if f.lower().endswith(".srt") and f.startswith(os.path.splitext(video_file)[0])):
            print(f"[{video_file}] Already has external subtitle in '{args.lang}'. Skipping.")
            continue

        # 2. FIND A SUBTITLE TO TRANSLATE — prefer embedded, then external
        try:
            streams = list_subtitle_streams(video_path)
        except RuntimeError as e:
            print(f"[{video_file}] Could not read subtitle streams: {e}. Falling back to external files.", file=sys.stderr)
            streams = []

        if streams:
            print(f"[{video_file}] Found {len(streams)} embedded subtitle stream(s):\n" + "\n".join(f"  - {_fmt_stream(s)}" for s in streams))
            best_stream = find_usable_subtitle_stream(streams)
            if best_stream:
                print(f"[{video_file}] Selected embedded stream: {_fmt_stream(best_stream)}")
                extracted_path = os.path.join(args.path, f"{os.path.splitext(video_file)[0]}.usable.srt")
                try:
                    extract_subtitle_stream_to_srt(video_path, extracted_path, best_stream["sub_index"])
                    usable_subtitle_path = extracted_path
                    print(f"[{video_file}] Successfully extracted embedded subtitle.")
                except Exception as e:
                    print(f"[{video_file}] Failed to extract embedded subtitle: {e}. Falling back to external files.", file=sys.stderr)
            else:
                print(f"[{video_file}] No usable (non-forced) embedded stream found. Falling back to external files.")
        else:
            print(f"[{video_file}] No embedded subtitle streams found. Looking for external .srt files...")

        if not usable_subtitle_path:
            base = os.path.splitext(video_file)[0]
            srt_files = [f for f in files if f.lower().endswith(".srt") and f.startswith(base)]
            if srt_files:
                print(f"[{video_file}] Found {len(srt_files)} external .srt file(s):\n" + "\n".join(f"  - {f}" for f in srt_files))
            else:
                print(f"[{video_file}] No external .srt files found.", file=sys.stderr)
            result = pick_external_subtitle(files, video_file)
            if result is None:
                print(f"[{video_file}] No usable subtitle found. Skipping.", file=sys.stderr)
                continue
            usable_subtitle_path = os.path.join(args.path, result)
            print(f"[{video_file}] Selected external subtitle: {result}")

        # 3. TRANSLATE
        is_extracted = usable_subtitle_path == os.path.join(args.path, f"{os.path.splitext(video_file)[0]}.usable.srt")
        try:
            subtitle = Subtitle.from_file(usable_subtitle_path)
        except ValueError as e:
            print(f"[{video_file}] Invalid subtitle file: {e}", file=sys.stderr)
            continue

        print(f"[{video_file}] Translating to '{args.lang}' ...")
        try:
            translated_subtitle = translate_subtitle(subtitle, args.lang)
        except Exception as e:
            print(f"[{video_file}] Translation failed: {e}", file=sys.stderr)
            continue

        # Attempt to save into the movie folder, and always write a local backup
        movie_output_path = os.path.join(args.path, f"{os.path.splitext(video_file)[0]}.{args.lang}.srt")
        project_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(project_dir, "translated_subtitles")
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except Exception as e:
            print(f"[{video_file}] Warning: could not create backup directory '{backup_dir}': {e}", file=sys.stderr)
            backup_dir = None

        saved_to_movie = False
        saved_to_backup = False

        try:
            translated_subtitle.to_srt_file(movie_output_path)
            saved_to_movie = True
            print(f"[{video_file}] Saved translated subtitle to movie folder: {movie_output_path}")
        except Exception as e:
            print(f"[{video_file}] Could not save subtitle to movie folder: {e}", file=sys.stderr)

        if backup_dir:
            backup_output_path = os.path.join(backup_dir, f"{os.path.splitext(video_file)[0]}.{args.lang}.srt")
            try:
                translated_subtitle.to_srt_file(backup_output_path)
                saved_to_backup = True
                print(f"[{video_file}] Saved translated subtitle to local backup: {backup_output_path}")
            except Exception as e:
                print(f"[{video_file}] Failed to save local backup '{backup_output_path}': {e}", file=sys.stderr)

        if not (saved_to_movie or saved_to_backup):
            print(f"[{video_file}] Translation failed: could not save subtitle to movie folder or local backup.", file=sys.stderr)
            continue

        if is_extracted:
            # Only remove temporary extracted subtitle if we saved it somewhere
            if (saved_to_movie or saved_to_backup) if 'saved_to_movie' in locals() else False:
                try:
                    os.remove(usable_subtitle_path)
                    print(f"[{video_file}] Deleted temporary extracted subtitle.")
                except Exception as e:
                    print(f"[{video_file}] Warning: failed to delete temporary extracted subtitle: {e}", file=sys.stderr)
            else:
                print(f"[{video_file}] Leaving temporary extracted subtitle at {usable_subtitle_path} (save failed).", file=sys.stderr)
        



if __name__ == "__main__":
    main()
