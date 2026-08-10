# chatgpt-share-md

Convert a **public ChatGPT share link** into a clean Markdown document.

```bash
chatgpt-share-md "https://chatgpt.com/share/<id>"
```

Zero dependencies. Python 3.10+.

## Why

Shared ChatGPT pages (`chatgpt.com/share/...`) are awkward to archive: the conversation is buried inside a React payload, not plain HTML text. This CLI fetches the share page, extracts the conversation, and writes readable Markdown (and optional JSON).

## Install

```bash
# From this repo
pip install -e .

# Or run without installing
python -m chatgpt_share_md "https://chatgpt.com/share/<id>"
```

## Usage

```bash
# Write <slugified-title>.md in the current directory
chatgpt-share-md "https://chatgpt.com/share/6a793ced-ed18-83ea-b2e6-66d3cf2917fb"

# Choose the output path
chatgpt-share-md "https://chatgpt.com/share/<id>" -o conversation.md

# Print to stdout
chatgpt-share-md "https://chatgpt.com/share/<id>" --stdout

# Also emit a sibling .json file
chatgpt-share-md "https://chatgpt.com/share/<id>" --json

# Convert a saved share-page HTML file (View Source → Save)
chatgpt-share-md share-page.html -o conversation.md
```

### Options

| Flag | Description |
|---|---|
| `-o`, `--output` | Output `.md` path |
| `--stdout` | Print Markdown instead of writing a file |
| `--json` | Also write structured JSON next to the Markdown |
| `--include-tools` | Keep tool/plugin messages (skipped by default) |
| `--include-system` | Keep system messages (skipped by default) |
| `--timeout` | HTTP timeout in seconds (default: `30`) |

## Output format

```markdown
# Conversation title

- Source: https://chatgpt.com/share/...
- Conversation ID: `...`
- Created: 2026-08-10T02:52:29Z
- Updated: 2026-08-10T02:52:30Z
- Messages: 13

## 1. User

...

## 2. Assistant

...
```

Interactive ChatGPT widgets (entity chips, image carousels, citations) are cleaned up so the Markdown stays readable.

## How it works

1. Fetch the public share URL with browser-like headers (or read a local HTML file).
2. Extract the React Router stream payload (`__reactRouterContext.streamController.enqueue(...)`), with a fallback for legacy `__NEXT_DATA__` shares.
3. Resolve the compact indexed JSON graph.
4. Read `linear_conversation` and render user/assistant turns as Markdown.

## Limitations

- Works with **public** share links only.
- Private `/c/...` conversations and authenticated pages are not supported.
- If a live fetch fails (bot protection, expired link), open the share URL in a private window, save the page HTML, and pass the file to the CLI.
- Generated images / attachments are not downloaded; only text content is exported.

## Development

```bash
python -m chatgpt_share_md --help
pip install -e .
```

No third-party runtime dependencies — stdlib only.

## License

MIT
