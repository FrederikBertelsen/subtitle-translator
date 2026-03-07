from dataclasses import dataclass
import re
from typing import List, Optional
import argparse
import json
import sys


def _time_to_ms(time_str: str) -> int:
	parts = time_str.split(",")
	if len(parts) != 2:
		raise ValueError(f"Invalid time format (missing milliseconds): {time_str!r}")
	hms, ms = parts[0], parts[1]
	h, m, s = hms.split(":")
	return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


@dataclass
class SubtitleLine:
	index: int
	time_str: str
	text: str

	def to_dict(self) -> dict:
		return {"index": self.index, "time_str": self.time_str, "text": self.text}


class Subtitle:
	def __init__(self, srt_text: str, validate: bool = True, strict: bool = True):
		self.raw = srt_text or ""
		self.lines: List[SubtitleLine] = self._parse(self.raw)
		self.errors: List[str] = []
		if validate:
			self.errors = self.validate()
			if strict and self.errors:
				raise ValueError("Subtitle validation failed:\n{}".format("\n".join(self.errors)))

	@classmethod
	def from_file(cls, path: str) -> "Subtitle":
		with open(path, "r", encoding="utf-8") as f:
			return cls(f.read())

	def to_srt_file(self, path: str):
		with open(path, "w", encoding="utf-8") as f:
			for ln in self.lines:
				f.write(f"{ln.index}\n{ln.time_str}\n{ln.text}\n\n")

	def _parse(self, srt_text: str) -> List[SubtitleLine]:
		if not srt_text:
			return []

		text = srt_text.replace("\r\n", "\n").strip()
		if not text:
			return []

		blocks = re.split(r"\n{2,}", text)
		time_pattern = re.compile(r"\d{2}:\d{2}:\d{2},\d{3}\s*--?>\s*\d{2}:\d{2}:\d{2},\d{3}")

		result: List[SubtitleLine] = []
		next_index = 1

		for block in blocks:
			lines = [ln for ln in block.splitlines() if ln is not None]
			if not lines:
				raise ValueError(f"Empty block found in subtitle text: {block!r}")

			idx = None
			time_str = None
			text_lines: List[str] = []

			if len(lines) >= 2 and time_pattern.search(lines[1]):
				try:
					idx = int(lines[0].strip())
				except Exception:
					idx = None
				time_str = lines[1].strip()
				text_lines = [ln.rstrip() for ln in lines[2:]]
			elif time_pattern.search(lines[0]):
				time_str = lines[0].strip()
				text_lines = [ln.rstrip() for ln in lines[1:]]
			else:
				for i, ln in enumerate(lines):
					if time_pattern.search(ln):
						time_str = ln.strip()
						try:
							idx = int(lines[0].strip())
						except Exception:
							idx = None
						text_lines = [l.rstrip() for l in lines[i + 1 :]]
						break

			if idx is None:
				idx = next_index

			next_index = idx + 1
			txt = "\n".join(text_lines).strip()
			result.append(SubtitleLine(index=idx, time_str=time_str or "", text=txt))

		return result

	def encode(self) -> List[str]:
		out = []
		for ln in self.lines:
			text = ln.text.replace("\n", "<br>")
			out.append(f"{ln.index}|{text}".strip())
		return out
	
	def decode(self, encoded_lines: List[str]) -> "Subtitle":
		if len(encoded_lines) != len(self.lines):
			raise ValueError(f"Encoded lines count {len(encoded_lines)} does not match original lines count {len(self.lines)}")

		new_subtitle = Subtitle("", validate=False)
		
		lines: List[SubtitleLine] = []
		for i, ln in enumerate(encoded_lines):
			parts = ln.split("|", 1)
			if len(parts) != 2:
				raise ValueError(f"Invalid encoded line (missing '|'): {ln!r}")
			idx_str, text = parts
			try:
				idx = int(idx_str.strip())
			except Exception:
				raise ValueError(f"Invalid index in encoded line: {idx_str!r}")

			if idx != self.lines[i].index:
				raise ValueError(f"Index mismatch at line {i}: expected {self.lines[i].index}, got {idx}")
			
			text_decoded = text.replace("<br>", "\n")
			lines.append(SubtitleLine(index=idx, time_str=self.lines[i].time_str, text=text_decoded))

		new_subtitle.lines = lines
		new_subtitle.errors = new_subtitle.validate()
		if new_subtitle.errors:
			raise ValueError("Decoded subtitle validation failed:\n{}".format("\n".join(new_subtitle.errors)))
		
		return new_subtitle

	def __iter__(self):
		return iter(self.lines)

	def __len__(self):
		return len(self.lines)

	def to_dicts(self) -> List[dict]:
		return [ln.to_dict() for ln in self.lines]

	def validate(self) -> List[str]:
		errors: List[str] = []
		time_re = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*--?>\s*(\d{2}:\d{2}:\d{2},\d{3})")
		seen = set()
		
		for ln in self.lines:
			if ln.index in seen:
				errors.append(f"Duplicate index {ln.index}")
			seen.add(ln.index)

			if not ln.time_str:
				errors.append(f"Missing time for index {ln.index}")
				continue

			m = time_re.search(ln.time_str)
			if not m:
				errors.append(f"Invalid time format for index {ln.index}: {ln.time_str}")
				continue

			if ln.text == "":
				errors.append(f"Empty text for index {ln.index}")

		if seen:
			min_idx, max_idx = min(seen), max(seen)
			missing = [i for i in range(min_idx, max_idx + 1) if i not in seen]
			if missing:
				errors.append(f"Missing indexes: {missing}")

		return errors

	def is_valid(self) -> bool:
		return len(self.errors) == 0

	def analyze(self) -> dict:
		time_re = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*--?>\s*(\d{2}:\d{2}:\d{2},\d{3})")
		starts: List[int] = []
		ends: List[int] = []
		overlaps = 0
		prev_end: Optional[int] = None
		time_lines = 0

		for ln in self.lines:
			if not ln.time_str:
				continue
			m = time_re.search(ln.time_str)
			if not m:
				continue
			try:
				start_ms = _time_to_ms(m.group(1))
				end_ms = _time_to_ms(m.group(2))
			except Exception:
				continue
			time_lines += 1
			starts.append(start_ms)
			ends.append(end_ms)
			if prev_end is not None and start_ms < prev_end:
				overlaps += 1
			prev_end = max(prev_end if prev_end is not None else 0, end_ms)

		if starts and ends:
			first_start_ms = min(starts)
			last_end_ms = max(ends)
			duration_ms = last_end_ms - first_start_ms if last_end_ms > first_start_ms else 0
		else:
			first_start_ms = None
			last_end_ms = None
			duration_ms = 0

		indexes_set = {ln.index for ln in self.lines}
		if indexes_set:
			min_idx = min(indexes_set)
			max_idx = max(indexes_set)
			missing = [i for i in range(min_idx, max_idx + 1) if i not in indexes_set]
		else:
			min_idx = None
			max_idx = None
			missing = []

		return {
			"lines": len(self.lines),
			"time_lines": time_lines,
			"first_index": min_idx,
			"last_index": max_idx,
			"missing_indexes": missing,
			"first_start_ms": first_start_ms,
			"last_end_ms": last_end_ms,
			"duration_ms": duration_ms,
			"overlaps": overlaps,
		}


def analyze_subtitle(srt_text: str, validate: bool = True, strict: bool = False) -> dict:
	sub = Subtitle(srt_text, validate=False)
	errors = sub.validate() if validate else []
	if strict and errors:
		raise ValueError("Subtitle validation failed:\n{}".format("\n".join(errors)))
	info = sub.analyze()
	return {"valid": len(errors) == 0, "errors": errors, "info": info}


def main(argv=None):
	parser = argparse.ArgumentParser(description="Validate and analyze SRT subtitle file.")
	parser.add_argument("path", nargs="?", help="Subtitle file path (use '-' for stdin). If omitted, reads stdin.")
	parser.add_argument("--json", action="store_true", help="Output results as JSON")
	parser.add_argument("--no-validate", dest="validate", action="store_false", help="Skip validation")
	parser.add_argument("--strict", action="store_true", help="Raise error / exit non-zero on validation errors")
	args = parser.parse_args(argv)

	if not args.path or args.path == "-":
		srt_text = sys.stdin.read()
	else:
		try:
			with open(args.path, "r", encoding="utf-8") as f:
				srt_text = f.read()
		except Exception as e:
			print(f"Error opening {args.path}: {e}", file=sys.stderr)
			sys.exit(2)

	try:
		res = analyze_subtitle(srt_text, validate=args.validate, strict=args.strict)
	except ValueError as e:
		print(str(e), file=sys.stderr)
		sys.exit(2)

	if args.json:
		print(json.dumps(res, ensure_ascii=False, indent=2))
	else:
		print(f"Valid: {res['valid']}")
		if res["errors"]:
			print("Errors:")
			for err in res["errors"]:
				print(" -", err)
		else:
			print("Errors: None")

		print("Info:")
		for k, v in res["info"].items():
			print(f" - {k}: {v}")

	try:
		subtitle = Subtitle(srt_text)
		print(f"\nParsed {len(subtitle)} subtitle lines successfully.")

		print("\nFirst 5 decoded subtitle lines:")
		encoded_lines = subtitle.encode()
		for encoded_line in encoded_lines[:5]:
			print(f" - \"{encoded_line}\"")

		print()

		error_found = False
		encode_decode_test = subtitle.decode(encoded_lines)
		for i in range(len(subtitle.lines)):
			original = subtitle.lines[i]
			decoded = encode_decode_test.lines[i]
			if original != decoded:
				print(f"Mismatch at index {i}:")
				print(f"  Original: {original}")
				print(f"  Decoded:  {decoded}")
				error_found = True
		
		if not error_found:
			print("Encode-decode test passed: decoded lines match original lines.")
		
		with open("encoded_subtitle.txt", "w", encoding="utf-8") as f:
			for line in encoded_lines:
				f.write(line + "\n")

	except Exception as e:
		print(f"Error parsing subtitle: {e}", file=sys.stderr)
		sys.exit(2)
	
	sys.exit(0 if res["valid"] else 1)


if __name__ == "__main__":
	main()
