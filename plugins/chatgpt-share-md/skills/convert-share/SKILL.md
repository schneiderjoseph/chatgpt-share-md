---
name: convert-share
description: >
  ALWAYS use this skill whenever the user pastes, mentions, or shares a public
  ChatGPT conversation link (chatgpt.com/share/..., chat.openai.com/share/...,
  or a saved ChatGPT share HTML page). Converts the shared chat into a clean
  Markdown (.md) document using the bundled converter. Also use when the user
  asks to export, save, archive, or convert a ChatGPT share to Markdown.
---

# Convert ChatGPT share → Markdown

When the user provides a **ChatGPT share URL** or a saved share-page HTML file, convert it to Markdown immediately. Do not ask whether to convert — just do it.

## Trigger patterns

Use this skill for any of:

- `https://chatgpt.com/share/<id>`
- `https://chat.openai.com/share/<id>`
- A local HTML file saved from a ChatGPT share page
- Requests like “export this chat”, “save as md”, “convert this share link”

Do **not** use this for private `/c/<id>` conversation URLs (those require login and will fail).

## Steps

1. Extract the share URL (or HTML file path) from the user message.
2. Choose an output path:
   - If the user specified a path, use it.
   - Otherwise write `./<slug-or-chatgpt-share>.md` in the current project directory.
3. Run the bundled converter:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/chatgpt_share_md.py" "<SHARE_URL_OR_HTML>" -o "<OUTPUT.md>"
```

On Windows PowerShell, if `${CLAUDE_PLUGIN_ROOT}` is unavailable in the shell, resolve the plugin script path from the installed plugin cache, or run:

```powershell
python "$env:CLAUDE_PLUGIN_ROOT\bin\chatgpt_share_md.py" "<SHARE_URL_OR_HTML>" -o "<OUTPUT.md>"
```

If the package is installed in the environment, this equivalent works too:

```bash
chatgpt-share-md "<SHARE_URL_OR_HTML>" -o "<OUTPUT.md>"
# or
python -m chatgpt_share_md "<SHARE_URL_OR_HTML>" -o "<OUTPUT.md>"
```

4. Confirm success by reporting:
   - Output file path
   - Message count (from the CLI stdout)
   - Title if available
5. Optionally open or summarize the Markdown if the user asks.

## Failure recovery

If the live fetch fails (HTTP error, bot protection, expired share):

1. Tell the user to open the share link in a private/incognito window.
2. Ask them to save the page HTML (View Source → Save, or browser Save Page).
3. Re-run the converter on that HTML file:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/chatgpt_share_md.py" "path/to/share.html" -o "<OUTPUT.md>"
```

## Output expectations

- Produce a `.md` file with title, source metadata, and `## N. User` / `## N. Assistant` sections.
- Prefer writing a file over dumping the whole transcript into chat unless the user asked for `--stdout` / inline output.
- Do not invent conversation content. Only use what the converter extracts.
