"""Tool icon registry — 2-letter monograms + colors for the dashboard.

Keyed by the canonical tool name from ``upbox/rules/tools.yaml``. The CSS
classes ``tool-icon tool-icon-<code>`` are defined in
``upbox/dashboard/static/dashboard.css``; new entries here MUST add a
matching class there (or fall back to the default grey).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolIcon:
    """How a tool is rendered in the sidebar and feed rows."""

    monogram: str
    code: str  # lowercase, used as the CSS class suffix


_UNKNOWN_ICON = ToolIcon(monogram="??", code="default")


TOOL_ICONS: dict[str, ToolIcon] = {
    "Cursor": ToolIcon("Cs", "cs"),
    "Claude Desktop": ToolIcon("Cl", "cl"),
    "Claude Code": ToolIcon("Cl", "cl"),
    "GitHub Copilot": ToolIcon("Co", "co"),
    "ChatGPT": ToolIcon("Gp", "gp"),
    "Codeium": ToolIcon("Cd", "cd"),
    "Windsurf": ToolIcon("Ws", "ws"),
    "Google Gemini": ToolIcon("Gm", "gm"),
    "OpenAI API": ToolIcon("Oa", "oa"),
    "Anthropic API": ToolIcon("An", "an"),
    "Continue": ToolIcon("Cn", "cn"),
    "Cody": ToolIcon("Cy", "cy"),
    "Perplexity": ToolIcon("Px", "px"),
    "Tabnine": ToolIcon("Tn", "tn"),
    "Replit AI": ToolIcon("Rp", "rp"),
}


def icon_for(tool: str | None) -> ToolIcon:
    """Return the icon for a tool, or a default placeholder if unmapped."""
    if not tool:
        return _UNKNOWN_ICON
    return TOOL_ICONS.get(tool, _UNKNOWN_ICON)
