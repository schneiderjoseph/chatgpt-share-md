"""Convert public ChatGPT share links into Markdown documents."""

from .converter import (
    ConvertError,
    build_markdown,
    extract_messages,
    find_shared_conversation,
    main,
    read_source,
)

__all__ = [
    "ConvertError",
    "build_markdown",
    "extract_messages",
    "find_shared_conversation",
    "main",
    "read_source",
]

__version__ = "0.1.0"
