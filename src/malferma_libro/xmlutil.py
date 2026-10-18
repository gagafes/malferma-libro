"""Build XML trees with limits checked before each element is allocated."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .i18n import _


class XMLLimitError(ValueError):
    """The document exceeds a tree complexity limit."""


class _BoundedTreeBuilder(ET.TreeBuilder):
    def __init__(self, max_nodes: int, max_depth: int) -> None:
        super().__init__()
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.nodes = 0
        self.depth = 0

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        self.nodes += 1
        self.depth += 1
        if self.nodes > self.max_nodes:
            raise XMLLimitError(_("слишком много элементов XML"))
        if self.depth > self.max_depth:
            raise XMLLimitError(_("слишком большая вложенность XML"))
        return super().start(tag, attrs)

    def end(self, tag: str) -> ET.Element:
        element = super().end(tag)
        self.depth -= 1
        return element


def parse_xml(data: bytes, *, max_nodes: int, max_depth: int) -> ET.Element:
    """Parse without first allocating an unrestricted tree for later inspection."""
    parser = ET.XMLParser(target=_BoundedTreeBuilder(max_nodes, max_depth))
    return ET.fromstring(data, parser=parser)
