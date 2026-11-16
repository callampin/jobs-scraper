"""Normalización de contenido HTML a texto legible."""

import re

from bs4 import BeautifulSoup


def html_to_text(value: object) -> str:
    """Elimina etiquetas HTML conservando párrafos y elementos de lista."""
    if not isinstance(value, str) or not value.strip():
        return ""

    soup = BeautifulSoup(value, "html.parser")
    for unwanted in soup.find_all(["script", "style"]):
        unwanted.decompose()
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")
    for item in soup.find_all("li"):
        item.insert(0, "- ")
    for block in soup.find_all(
        ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"]
    ):
        block.append("\n")

    raw_text = soup.get_text()
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    return "\n".join(line for line in lines if line).strip()
