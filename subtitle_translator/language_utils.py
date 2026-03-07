import json
from pathlib import Path
from typing import Dict, Optional

_LANGUAGE_ALIASES: Optional[Dict[str, str]] = None
_LANGUAGE_NAMES: Optional[Dict[str, str]] = None


def _normalize_lang_tag(tag: str) -> str:
    return str(tag).lower().strip().replace("_", "-")


def _get_language_aliases() -> Dict[str, str]:
    global _LANGUAGE_ALIASES, _LANGUAGE_NAMES
    if _LANGUAGE_ALIASES is not None:
        return _LANGUAGE_ALIASES
    
    p = Path(__file__).parent.parent / "languages.json"
    if not p.exists():
        raise RuntimeError(f"languages.json not found at {p}")
    
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    alias_to_code: Dict[str, str] = {}
    code_to_name: Dict[str, str] = {}
    
    for item in data:
        code = _normalize_lang_tag(item.get("value", ""))
        if not code:
            continue
        
        name = item.get("name")
        if name:
            code_to_name[code] = name
        
        alias_to_code[code] = code
        primary = code.split("-", 1)[0]
        alias_to_code[primary] = code
        
        for variant in [name, item.get("native")] + item.get("aliases", []):
            if variant:
                alias_to_code[_normalize_lang_tag(variant)] = code

    _LANGUAGE_ALIASES = alias_to_code
    _LANGUAGE_NAMES = code_to_name
    return alias_to_code


def get_lang_name(lang: str) -> Optional[str]:
    if not lang:
        return None
    alias_map = _get_language_aliases()
    
    normalized = _normalize_lang_tag(lang)
    code = alias_map.get(normalized)
    if code and _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES.get(code)
    return None


def lang_matches(lang_field: Optional[str], desired: str) -> bool:
    if not lang_field or not desired:
        return False
    
    alias_map = _get_language_aliases()
    code1 = alias_map.get(_normalize_lang_tag(lang_field))
    code2 = alias_map.get(_normalize_lang_tag(desired))
    
    return code1 is not None and code1 == code2
