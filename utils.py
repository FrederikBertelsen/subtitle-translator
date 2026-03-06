import json
from pathlib import Path
from typing import Dict, Optional


_LANGUAGE_ALIASES: Optional[Dict[str, set]] = None
_LANGUAGE_NAMES: Optional[Dict[str, str]] = None


def _normalize_lang_tag(tag: str) -> str:
    """Normalize a language tag or alias for comparison.

    Normalization: lower-case, strip surrounding whitespace, and convert
    underscores to hyphens (e.g. `en_US` -> `en-us`).
    """
    return str(tag).lower().strip().replace("_", "-")


def _get_language_aliases() -> Dict[str, set]:
    """Load language aliases from `languages.json` in the same directory.

    This function will raise a `RuntimeError` if `languages.json` is not found
    or cannot be parsed. Callers should allow that to surface rather than
    falling back silently.
    """
    global _LANGUAGE_ALIASES
    if _LANGUAGE_ALIASES is not None:
        return _LANGUAGE_ALIASES
    p = Path(__file__).parent / "languages.json"
    if not p.exists():
        raise RuntimeError(f"languages.json not found at {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    global _LANGUAGE_NAMES
    aliases: Dict[str, set] = {}
    names: Dict[str, str] = {}
    for item in data:
        val_raw = item.get("value") or ""
        val = _normalize_lang_tag(val_raw)
        if not val:
            continue
        s = {val}
        # include primary subtag (e.g. 'en' for 'en-us') to allow matching
        primary = val.split("-", 1)[0]
        s.add(primary)
        name = item.get("name")
        native = item.get("native")
        if name:
            s.add(_normalize_lang_tag(name))
        if native:
            s.add(_normalize_lang_tag(native))
        for alias in item.get("aliases") or []:
            s.add(_normalize_lang_tag(alias))
        aliases[val] = s
        if name:
            # map the canonical value, normalized name, and native to the display name
            names[val] = name
            names[_normalize_lang_tag(name)] = name
            if native:
                names[_normalize_lang_tag(native)] = name

    _LANGUAGE_ALIASES = aliases
    _LANGUAGE_NAMES = names
    return aliases


def get_lang_name(lang: str) -> Optional[str]:
    """Return the canonical English name for a language.

    Accepts the value (e.g. ``'en'``), the English name (e.g. ``'English'``),
    or the native name (e.g. ``'Deutsch'``) from ``languages.json``.
    Returns ``None`` if no match is found.
    """
    if not lang:
        return None
    _get_language_aliases()  # ensure _LANGUAGE_NAMES is populated
    names: Dict[str, str] = _LANGUAGE_NAMES  # type: ignore[assignment]
    normalized = _normalize_lang_tag(lang)
    if normalized in names:
        return names[normalized]
    # primary-subtag fallback: 'en-us' -> try 'en'
    primary = normalized.split("-", 1)[0]
    return names.get(primary)


def lang_matches(lang_field: Optional[str], desired: str) -> bool:
    """Return True if `lang_field` matches the `desired` language.

    Matching rules (simple and predictable):
    - Inputs are normalized (lowercased, trimmed, underscores -> hyphens).
    - Exact matches succeed.
    - Primary-subtag matches succeed (e.g. 'en-us' == 'en').
    - Known aliases and native names from `languages.json` are considered.
    """
    if not lang_field or not desired:
        return False

    lf = _normalize_lang_tag(lang_field)
    d = _normalize_lang_tag(desired)

    if lf == d:
        return True

    # primary subtag match (e.g. 'en' and 'en-us')
    if lf.split("-", 1)[0] == d.split("-", 1)[0]:
        return True

    aliases = _get_language_aliases()

    for key, vals in aliases.items():
        items = set(vals)
        items.add(key)
        if lf in items and d in items:
            return True

    return False