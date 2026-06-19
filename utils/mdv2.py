import re

_ESCAPE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')


def esc(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    return _ESCAPE.sub(r'\\\1', str(text))


def bold(text: str) -> str:
    return f"*{esc(text)}*"


def italic(text: str) -> str:
    return f"_{esc(text)}_"


def code(text: str) -> str:
    return f"`{esc(text)}`"


def pre(text: str) -> str:
    return f"```\n{text}\n```"


def link(label: str, url: str) -> str:
    return f"[{esc(label)}]({url})"
