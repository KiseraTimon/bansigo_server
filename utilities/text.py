# utilities/text.py

import re

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_length: int = 120) -> str:
    """
    url-safe slug: 'Brookside Milk 500ml' -> 'brookside-milk-500ml'
    :param value: str
    :param max_length: int
    :return: str
    """
    slug = _NON_SLUG.sub("-", value.lower()).strip("-")[:max_length].strip("-")
    return slug or "item"
