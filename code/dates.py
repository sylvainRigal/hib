"""Date helpers. `today` is UTC."""
import time


def today():
    """Current UTC date as (year, month, day)."""
    t = time.gmtime()
    return (t.tm_year, t.tm_mon, t.tm_mday)


def format_dmy(year, month, day):
    return "%02d/%02d/%04d" % (day % 100, month % 100, year % 10000)


def _digits_only(s):
    return "".join(c for c in s if "0" <= c <= "9")


def _parse_u16(part):
    # Strict unsigned 16-bit parse: trim ONLY ASCII
    # space (not tab/other ws), accept only ASCII digits (no '-'/'+'/Unicode
    # digits), reject u16 overflow. Anything else -> None -> digits-only fallback.
    s = part.strip(" ")
    if not s or not s.isascii() or not s.isdigit():
        return None
    v = int(s)
    return v if v <= 65535 else None


def _three_nums(dmy):
    parts = dmy.split("/")
    if len(parts) != 3:
        return None
    d, m, y = _parse_u16(parts[0]), _parse_u16(parts[1]), _parse_u16(parts[2])
    if d is None or m is None or y is None:
        return None
    return (d, m, y)


def compact_dmy(dmy):
    """'DD/MM/YYYY' -> 'YYYYMMDD'; digits-only fallback when it does not parse."""
    nums = _three_nums(dmy)
    if nums is not None:
        d, m, y = nums
        return "%04d%02d%02d" % (y % 10000, m % 100, d % 100)
    return _digits_only(dmy)


def compact_ymd(year, month, day):
    """year/month/day -> 'YYYYMMDD'."""
    return "%04d%02d%02d" % (year % 10000, month % 100, day % 100)


def short_dmy(dmy):
    """'DD/MM/YYYY' -> 'ddmmyy' (2-digit year); digits-only fallback."""
    nums = _three_nums(dmy)
    if nums is not None:
        d, m, y = nums
        return "%02d%02d%02d" % (d % 100, m % 100, y % 100)
    return _digits_only(dmy)
