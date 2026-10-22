from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bs4.element import Tag

FormElementType = Literal["input", "button", "select", "textarea"]


@dataclass
class FormElement:
    type: FormElementType
    name: str = ""
    label: str = ""
    value: str = ""
    options: list[str] = field(default_factory=list)


class FormExtractor:

    def __init__(self):
        self.elements: list[FormElement] = []

    @staticmethod
    def form_header(node: Tag) -> str:
        action = node.get("action", "")
        method = (node.get("method") or "GET").upper()
        return f"[Form: {method} {action}]" if action else "[Form]"

    def process_input(self, node: Tag) -> str:
        input_type = (node.get("type") or "text").lower()
        if input_type in ("hidden", "submit"):
            value = node.get("value", "")
            if input_type == "submit" and value:
                return f"[{value}]"
            return ""

        name = node.get("name", "")
        placeholder = node.get("placeholder", "")
        label = placeholder or name
        self.elements.append(FormElement(type="input", name=name, label=label))

        if label:
            return f"[{label}]"
        return ""

    def process_button(self, node: Tag) -> str:
        text = node.get_text(strip=True)
        if text:
            self.elements.append(FormElement(type="button", label=text))
            return f"[{text}]"
        return ""

    def process_select(self, node: Tag) -> str:
        name = node.get("name", "")
        options = []
        for opt in node.find_all("option"):
            opt_text = opt.get_text(strip=True)
            if opt_text:
                options.append(opt_text)

        self.elements.append(FormElement(
            type="select", name=name, options=options,
        ))

        if options:
            return f"[{options[0]}]"
        return ""

    def process_textarea(self, node: Tag) -> str:
        name = node.get("name", "")
        placeholder = node.get("placeholder", "")
        label = placeholder or name
        self.elements.append(FormElement(type="textarea", name=name, label=label))

        if label:
            return f"[{label}]"
        return ""
