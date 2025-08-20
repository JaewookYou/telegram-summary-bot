from __future__ import annotations

import re
from typing import Iterable

from simhash import Simhash


WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = text.strip()
    text = text.replace("\u200b", "")  # zero-width space
    text = text.replace("\uFEFF", "")  # BOM
    text = WHITESPACE_RE.sub(" ", text)
    return text


def tokenize(text: str) -> list[str]:
    # very light tokenization: lowercase words and numbers, drop punctuation
    tokens = re.findall(r"[\w$#@]{2,}", text.lower())
    return tokens


def compute_simhash(text: str) -> int:
    norm = normalize_text(text)
    return Simhash(tokenize(norm)).value


