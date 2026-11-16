"""Default 'reference' identifier.

Format: <itemType>_<shortTitle>_<author3>_<yyyymmdd>, where <author3> is the first
3 cite-folded letters of the FIRST author's last name (ASCII, first letter
capitalized -- same folding as the citekey, so references stay stable across
versions).
The user can always override this default at the prompt; existing entries keep
whatever reference they already stored (only the suggested default changes).
"""
import sanitize


def default_reference(item_type, short_title, authors, yyyymmdd):
    """authors: [(last, first), ...]."""
    author3 = sanitize.cite_word(authors[0][0])[:3] if authors else ""
    return "%s_%s_%s_%s" % (item_type, short_title, author3, yyyymmdd)
