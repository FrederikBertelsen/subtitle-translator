import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


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
        "-count_packets",
        "-show_entries",
        "stream=index,codec_type,codec_name,codec_long_name,disposition,nb_read_packets:stream_tags=language,title",
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
                "nb_read_packets": int(s.get("nb_read_packets") or 0),
            }
        )
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


def extract_usable_subtitle_as_srt(input_path: str, output_path: Optional[str] = None) -> str:
    from subtitle_translator.selector import find_usable_subtitle_stream
    
    streams = list_subtitle_streams(input_path)
    if not streams:
        raise RuntimeError("No subtitle streams found")
    best = find_usable_subtitle_stream(streams)
    if not best:
        raise RuntimeError("No usable (non-forced) subtitle stream found")
    out = output_path or f"{Path(input_path).stem}.usable.srt"
    extract_subtitle_stream_to_srt(input_path, out, best["sub_index"])
    return out
