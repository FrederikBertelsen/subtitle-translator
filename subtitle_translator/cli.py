import argparse
import sys
from subtitle_translator.translation_service import translate_folder


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

    for vf, info in summary.get("videos", {}).items():
        status = info.get("status")
        print(f"{vf}: {status}")


if __name__ == "__main__":
    main()
