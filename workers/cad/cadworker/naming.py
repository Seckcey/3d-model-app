import re

DEFAULT_PATTERN = "{part}_REV{rev}_{kind}"
VARIANT_TAGS = {"nominal": "NOMINAL", "mid_tolerance": "MIDTOL"}
UNIT_TAGS = {"in": "IN", "mm": "MM"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def filename(pattern: str | None, *, part: str, rev: str, variant: str, units: str,
             customer: str = "", seq: int | str = "") -> str:
    """Build a download name. Units are always stamped so files are never ambiguous."""
    kind = f"{VARIANT_TAGS[variant]}-{UNIT_TAGS[units]}"
    name = (pattern or DEFAULT_PATTERN)
    for token, value in (("{part}", part), ("{rev}", rev or "-"), ("{kind}", kind),
                         ("{customer}", customer), ("{seq}", str(seq))):
        name = name.replace(token, str(value))
    if kind not in name:
        name = f"{name}_{kind}"
    name = _UNSAFE.sub("_", name).strip("._-")
    return name[:120] or f"part_{kind}"
