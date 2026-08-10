#!/usr/bin/env python3
"""Convert a public ChatGPT share link (or saved share HTML) into Markdown."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

ROLE_HEADINGS = {
    "user": "User",
    "assistant": "Assistant",
    "system": "System",
    "tool": "Tool",
}

# ChatGPT embeds interactive widgets with private-use Unicode delimiters.
WIDGET_RE = re.compile(
    "\ue200(?P<kind>[^\ue202]+)\ue202(?P<payload>.*?)\ue201",
    re.DOTALL,
)


class ConvertError(RuntimeError):
    """Raised when a share page cannot be converted."""


def is_url(source: str) -> bool:
    return urllib.parse.urlparse(source).scheme in {"http", "https"}


def normalize_share_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if host in {"chatgpt.com", "www.chatgpt.com", "chat.openai.com", "www.chat.openai.com"}:
        if "/share/" in path:
            return urllib.parse.urlunparse(
                ("https", host.removeprefix("www."), path, "", "", "")
            )

    raise ConvertError(
        "Expected a public ChatGPT share URL like "
        "https://chatgpt.com/share/<id>"
    )


def fetch_html(url: str, timeout: int) -> str:
    url = normalize_share_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise ConvertError(f"HTTP {exc.code} while fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise ConvertError(f"Could not fetch URL: {exc.reason}") from exc


def read_source(source: str, timeout: int) -> tuple[str, str | None]:
    if is_url(source):
        url = normalize_share_url(source)
        return fetch_html(url, timeout), url

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ConvertError(f"File not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace"), None


def extract_stream_chunks(html: str) -> list[str]:
    pattern = re.compile(
        r"window\.__reactRouterContext\.streamController\.enqueue\("
        r"(?P<literal>\"(?:\\.|[^\"\\])*\")"
        r"\);",
        re.DOTALL,
    )
    chunks: list[str] = []
    for match in pattern.finditer(html):
        literal = match.group("literal")
        try:
            chunks.append(json.loads(literal))
        except json.JSONDecodeError:
            try:
                chunks.append(ast.literal_eval(literal))
            except (SyntaxError, ValueError) as exc:
                raise ConvertError("Could not decode a React stream chunk.") from exc

    if chunks:
        return chunks

    # Legacy Next.js shares
    next_data = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
        html,
        re.DOTALL,
    )
    if next_data:
        return [next_data.group("data")]

    raise ConvertError(
        "No ChatGPT conversation payload found. "
        "The share may be private, expired, blocked, or require login. "
        "Tip: open the share link in a private window, save the page as HTML, "
        "then pass that file to this tool."
    )


def load_indexed_payload(chunks: list[str]) -> list[Any] | dict[str, Any]:
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and payload:
            return payload
        if isinstance(payload, dict):
            return payload
    raise ConvertError("No JSON conversation payload found in the page.")


def resolve_indexed_payload(payload: list[Any]) -> Any:
    resolving: set[int] = set()

    @lru_cache(maxsize=None)
    def resolve_index(index: int) -> Any:
        if index < 0:
            return None
        if index >= len(payload):
            raise ConvertError(f"Payload reference out of range: {index}")
        if index in resolving:
            return "…"
        resolving.add(index)
        try:
            return resolve_value(payload[index])
        finally:
            resolving.remove(index)

    def resolve_value(value: Any) -> Any:
        if isinstance(value, dict):
            resolved: dict[Any, Any] = {}
            for raw_key, raw_value in value.items():
                if (
                    isinstance(raw_key, str)
                    and raw_key.startswith("_")
                    and raw_key[1:].lstrip("-").isdigit()
                ):
                    key = resolve_index(int(raw_key[1:]))
                else:
                    key = raw_key
                val = (
                    resolve_index(raw_value)
                    if isinstance(raw_value, int)
                    else resolve_value(raw_value)
                )
                resolved[key] = val
            return resolved

        if isinstance(value, list):
            return [
                resolve_index(item) if isinstance(item, int) else resolve_value(item)
                for item in value
            ]
        return value

    return resolve_index(0)


def find_shared_conversation(root: Any) -> dict[str, Any]:
    # Modern React Router share pages
    if isinstance(root, dict) and "loaderData" in root:
        loader_data = root["loaderData"]
        if isinstance(loader_data, dict):
            for route_data in loader_data.values():
                if not isinstance(route_data, dict):
                    continue
                response = route_data.get("serverResponse")
                if not isinstance(response, dict):
                    continue
                data = response.get("data")
                if isinstance(data, dict) and "linear_conversation" in data:
                    return data

    # Legacy __NEXT_DATA__
    if isinstance(root, dict):
        props = root.get("props", {})
        page_props = props.get("pageProps", {}) if isinstance(props, dict) else {}
        server_response = (
            page_props.get("serverResponse", {})
            if isinstance(page_props, dict)
            else {}
        )
        data = (
            server_response.get("data")
            if isinstance(server_response, dict)
            else None
        )
        if isinstance(data, dict) and "linear_conversation" in data:
            return data

    raise ConvertError("Could not find linear_conversation in the share payload.")


def clean_widget(kind: str, payload: str) -> str:
    kind = kind.strip()
    payload = payload.strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None

    if kind == "entity" and isinstance(data, list) and len(data) >= 2:
        return str(data[1])

    if kind == "image_group":
        # Visual carousels are not downloadable from the share payload alone.
        return ""

    if kind in {"cite", "citation", "tether", "navigation"}:
        return ""

    return ""


def sanitize_text(text: str) -> str:
    cleaned = WIDGET_RE.sub(
        lambda match: clean_widget(match.group("kind"), match.group("payload")),
        text,
    )
    # Remove any leftover private-use markers.
    cleaned = re.sub("[\ue200-\ue202]", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def render_part(part: Any) -> str:
    if part is None:
        return ""
    if isinstance(part, str):
        return sanitize_text(part)
    if isinstance(part, dict):
        for key in ("text", "content", "transcript"):
            value = part.get(key)
            if isinstance(value, str):
                return sanitize_text(value)
        # Image / file references
        asset_pointer = part.get("asset_pointer") or part.get("url")
        if isinstance(asset_pointer, str):
            filename = part.get("metadata", {})
            name = ""
            if isinstance(filename, dict):
                name = filename.get("name") or ""
            label = name or "attachment"
            return f"![{label}]({asset_pointer})"
        return ""
    return str(part)


def extract_messages(
    conversation: dict[str, Any],
    *,
    include_tools: bool,
    include_system: bool,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    nodes = conversation.get("linear_conversation") or []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue

        author = message.get("author") or {}
        role = author.get("role") or author.get("name") or "unknown"
        if role == "tool" and not include_tools:
            continue
        if role == "system" and not include_system:
            continue

        content = message.get("content") or {}
        parts = content.get("parts") or []
        text = "\n".join(
            rendered
            for rendered in (render_part(part).strip() for part in parts)
            if rendered
        ).strip()
        if not text:
            continue

        messages.append(
            {
                "role": role,
                "content": text,
                "created_at": message.get("create_time"),
            }
        )

    return messages


def format_timestamp(timestamp: Any) -> str | None:
    if not isinstance(timestamp, (int, float)):
        return None
    return (
        dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "-", slug).strip("-").lower()
    return slug[:80] or "chatgpt-conversation"


def role_heading(role: str) -> str:
    return ROLE_HEADINGS.get(role, role.replace("_", " ").title())


def build_markdown(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    source: str | None,
) -> str:
    title = conversation.get("title") or "ChatGPT conversation"
    lines: list[str] = [f"# {title}", ""]

    meta: list[str] = []
    if source:
        meta.append(f"- Source: {source}")
    conversation_id = conversation.get("conversation_id")
    if conversation_id:
        meta.append(f"- Conversation ID: `{conversation_id}`")
    created = format_timestamp(conversation.get("create_time"))
    updated = format_timestamp(conversation.get("update_time"))
    if created:
        meta.append(f"- Created: {created}")
    if updated:
        meta.append(f"- Updated: {updated}")
    meta.append(f"- Messages: {len(messages)}")
    lines.extend(meta)
    lines.append("")

    for index, message in enumerate(messages, start=1):
        lines.append(f"## {index}. {role_heading(message['role'])}")
        lines.append("")
        lines.append(message["content"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def default_output_path(conversation: dict[str, Any], output_dir: Path) -> Path:
    title = conversation.get("title") or "chatgpt-conversation"
    return output_dir / f"{slugify(title)}.md"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a public ChatGPT share URL (or saved share HTML) "
            "into a Markdown document."
        )
    )
    parser.add_argument(
        "source",
        help="ChatGPT share URL or path to a saved share-page HTML file",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output .md path (default: <slugified-title>.md in the current directory)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print Markdown to stdout instead of writing a file",
    )
    parser.add_argument(
        "--include-tools",
        action="store_true",
        help="Include tool/plugin messages (skipped by default)",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system messages (skipped by default)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write a sibling .json file with structured messages",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        html, source_url = read_source(args.source, args.timeout)
        chunks = extract_stream_chunks(html)
        payload = load_indexed_payload(chunks)
        root = (
            resolve_indexed_payload(payload)
            if isinstance(payload, list)
            else payload
        )
        conversation = find_shared_conversation(root)
        messages = extract_messages(
            conversation,
            include_tools=args.include_tools,
            include_system=args.include_system,
        )
        if not messages:
            raise ConvertError("Conversation payload found, but it contained no messages.")

        markdown = build_markdown(conversation, messages, source_url or args.source)

        if args.stdout:
            sys.stdout.write(markdown)
            return 0

        if args.output:
            out_path = Path(args.output).expanduser().resolve()
        else:
            out_path = default_output_path(conversation, Path.cwd())

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote {out_path} ({len(messages)} messages)")

        if args.json:
            json_path = out_path.with_suffix(".json")
            document = {
                "title": conversation.get("title"),
                "source": source_url or args.source,
                "conversation_id": conversation.get("conversation_id"),
                "created_at": format_timestamp(conversation.get("create_time")),
                "updated_at": format_timestamp(conversation.get("update_time")),
                "messages": messages,
            }
            json_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote {json_path}")

        return 0
    except ConvertError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def run() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
