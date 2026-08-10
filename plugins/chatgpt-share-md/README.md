# chatgpt-share-md (Claude Code plugin)

Converts public ChatGPT share links into Markdown.

## Install from this marketplace

```shell
/plugin marketplace add schneiderjoseph/chatgpt-share-md
/plugin install chatgpt-share-md@chatgpt-share-md
```

If prompted, run `/reload-plugins`.

## Behavior

Whenever the user pastes a ChatGPT share URL (`chatgpt.com/share/...`), the `convert-share` skill should run automatically and write a `.md` file.

Manual invoke:

```shell
/chatgpt-share-md:convert-share https://chatgpt.com/share/<id>
```

## Local test

```bash
claude --plugin-dir ./plugins/chatgpt-share-md
```
