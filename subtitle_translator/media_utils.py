import os
from subtitle_translator.subtitle import Subtitle
from subtitle_translator import config


def is_media_file(filename: str) -> bool:
    return filename.lower().endswith(config.VIDEO_EXTENSIONS)


def count_subtitle_lines(path: str) -> int:
    try:
        return len(Subtitle.from_file(path).lines)
    except Exception:
        return 0


def clean_name_and_split(name: str) -> list[str]:
    for char in "._-'\":()":
        name = name.replace(char, " ")
    return list(set(name.lower().split()))


def find_media_folders(name: str, type: str) -> list[str]:
    if not config.MEDIA_BASE_PATHS:
        raise ValueError("MEDIA_BASE_PATH not set in environment variables.")
    base_paths = config.MEDIA_BASE_PATHS.split(",")

    matched_base_path = None
    for base_path in base_paths:
        if type.lower().strip() in base_path.lower():
            matched_base_path = base_path
            break

    if not matched_base_path:
        raise ValueError(f"Base path for type '{type}' not found.")

    name_words = clean_name_and_split(name)
    for entry in os.listdir(matched_base_path):
        entry_path = os.path.join(matched_base_path, entry)
        if os.path.isdir(entry_path):
            entry_words = clean_name_and_split(entry)
            
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
