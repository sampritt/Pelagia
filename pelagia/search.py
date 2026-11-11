"""Text normalization for autocomplete matching without changing display names."""

import unicodedata


def search_text(value):
    """Return a case-insensitive, accent-insensitive search key."""
    return "".join(
        character for character in unicodedata.normalize("NFD", (value or "").casefold())
        if unicodedata.category(character) != "Mn"
    )
