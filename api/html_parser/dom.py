"""Bulk DOM edits that stay linear where bs4's per-element versions rescan the parent."""
from __future__ import annotations

from bs4.element import PageElement, Tag


def remove_elements(elements: list[PageElement]) -> None:
    """Detach elements from the tree, rebuilding each parent's child list once instead of once per removal."""
    doomed_by_parent: dict[int, tuple[Tag, set[int]]] = {}
    attached: list[PageElement] = []
    for element in elements:
        if element.parent is None:
            continue
        _, doomed_ids = doomed_by_parent.setdefault(id(element.parent), (element.parent, set()))
        if id(element) not in doomed_ids:
            doomed_ids.add(id(element))
            attached.append(element)
    for parent, doomed_ids in doomed_by_parent.values():
        parent.contents = [child for child in parent.contents if id(child) not in doomed_ids]
    for element in attached:
        # With no parent, extract() skips its O(n) index lookup and only relinks siblings and the element chain.
        element.parent = None
        element.extract()
