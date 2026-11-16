"""Card file naming + on-disk collision avoidance.

json_base names the metadata file after the REFERENCE, not the citekey (see
hib's README).
"""
import sanitize

MAX_SUFFIX = 1000000


def json_base(reference, citekey):
    """The metadata file's base name, '<this>.json'. hib names it after the
    entry's REFERENCE -- the tool's internal identifier, fixed for the life of the
    entry, so the file never has to be renamed. The value is folded to a safe file
    name (the stored reference itself is kept verbatim). An entry with no
    reference at all falls back to its citekey, which is what hib named it
    before."""
    # collapse=False: the name must read back as the reference itself, and a
    # default reference for an author-less entry legitimately contains '__'.
    if reference and reference.strip():
        return sanitize.sanitize_base(reference, collapse=False)
    if citekey and citekey.strip():
        return sanitize.sanitize_base(citekey, collapse=False)
    return "entry"


def card_name(base):
    return base + ".html"


def numbered_name(base, n):
    return "%s_%d.html" % (base, n)


def first_free_numbered_name(base, taken):
    """First of '<base>_1.html', '<base>_2.html', ... for which taken(candidate)
    is False. `taken` receives the bare file name. Raises if none free."""
    n = 1
    while n <= MAX_SUFFIX:
        cand = numbered_name(base, n)
        if not taken(cand):
            return cand
        n += 1
    raise RuntimeError("no free numbered name")
