# chatgpt-share-md

Convert a **public ChatGPT share link** into a clean Markdown document.

```bash
chatgpt-share-md "https://chatgpt.com/share/<id>"
```

Zero dependencies. Python 3.10+.

This repository is also a **Claude Code plugin marketplace**.

## Claude Code plugin

Install the marketplace, then the plugin:

```shell
/plugin marketplace add schneiderjoseph/chatgpt-share-md
/plugin install chatgpt-share-md@chatgpt-share-md
```

If the install summary asks for it, run `/reload-plugins`.

Once enabled, Claude Code should **always** use the plugin skill when you paste a ChatGPT share URL (`chatgpt.com/share/...` or `chat.openai.com/share/...`) and convert it to a `.md` file.

Manual skill:

```shell
/chatgpt-share-md:convert-share https://chatgpt.com/share/<id>
```

Local plugin test (no marketplace):

```bash
claude --plugin-dir ./plugins/chatgpt-share-md
```

## Why

Shared ChatGPT pages (`chatgpt.com/share/...`) are awkward to archive. This Python CLI acquires the public share conversation through JSON or embedded HTML data and writes readable Markdown (and optional JSON).

## Install (Python CLI)

```bash
# From this repo
pip install -e .

# Or run without installing
python -m chatgpt_share_md "https://chatgpt.com/share/<id>"
```

## Web Interface

Run the built-in web server with zero external dependencies:

```bash
chatgpt-share-md --serve
# Or
python -m chatgpt_share_md --serve --port 8080
# Or
chatgpt-share-md-server
```

Open `http://localhost:8080` in your browser to paste a ChatGPT share link, preview the result, copy the Markdown in one click, or download the `.md` file.

You can also call the API programmatically:

```bash
curl -X POST http://localhost:8080/api/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://chatgpt.com/share/<id>"}'
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

1. For live public share URLs, the Python CLI and web API first attempt the unauthenticated share JSON representation at `https://chatgpt.com/backend-api/share/<id>`. This undocumented endpoint is an implementation detail, not an official supported OpenAI API.
2. Expected network, JSON, or schema failures fall back to fetching the share HTML and using the existing React Router stream parser (`__reactRouterContext.streamController.enqueue(...)`), including legacy `__NEXT_DATA__` support and indexed JSON graph decoding.
3. Read `linear_conversation` through the same message extraction and Markdown renderer. Explicitly visually hidden messages are excluded even with system/tool inclusion enabled.

Saved local HTML uses the existing HTML parser and remains offline. The timeout applies to each request separately. The standalone Claude plugin converter is unchanged.

## Repository layout

```text
.claude-plugin/marketplace.json   # Claude Code marketplace catalog
plugins/chatgpt-share-md/         # Installable Claude Code plugin
chatgpt_share_md/                 # Python package / CLI
```

## Limitations

- Works with **public** share links only.
- Private `/c/...` conversations and authenticated pages are not supported.
- If a live fetch fails (bot protection, expired link), open the share URL in a private window, save the page HTML, and pass the file to the CLI.
- Generated images / attachments are not downloaded; only text content is exported.

## Development

```bash
python -m chatgpt_share_md --help
pip install -e .
claude plugin validate .
```

No third-party runtime dependencies — stdlib only.

## License

MIT
