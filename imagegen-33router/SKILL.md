---
name: imagegen-33router
description: Generate or edit raster images through the active cc-switch provider, with a first-use model confirmation and persistent model selection. Use for requests to draw, create, generate, or edit an image.
---

# 33Router image generation

Use the bundled script for image generation. It reads the active Codex provider from cc-switch without printing or persisting the API key.

## First use

Before the first generation in a conversation, run:

```text
python <skill-dir>/scripts/generate_image.py status
```

Tell the user the current default model from the status result. The initial default is `gpt-image-2`. Ask whether to keep it or switch to another model. Do not call the image API until the user answers. Persist the choice with:

```text
python <skill-dir>/scripts/generate_image.py set-model --model <model-id>
```

If the user explicitly requests a model, still report the current default first, then use the requested model after the user confirms the switch. The saved model is reused for later image requests until the user asks to change it.

## Generation

For a normal request, use:

```text
python <skill-dir>/scripts/generate_image.py generate --prompt "<shaped prompt>" --output "<output path>"
```

Use `--model` only for a one-off override or immediately after a confirmed model change. Use `--size 1536x1024` and `--quality high` for a typical final image unless the user requests another size or quality. Keep the user's subject and constraints, and add useful photographic or composition details only when the request is generic.

The script supports both base64 and URL image responses from 33Router and saves the result locally. After success, show the image and report its saved path. Never include the API key in a prompt, response, log, or file.

## Errors

- If cc-switch cannot be found, ask the user to install it and import/select a Codex provider.
- If the provider returns `model_not_found` or says there is no available channel, tell the user that the selected 33Router channel does not support the requested model and ask whether to switch models or providers.
- If the image API succeeds but the response cannot be downloaded, report the provider error and do not claim that an image was saved.

The helper script and the one-time installer are included in this skill folder. The installer can be copied to another Windows machine together with this folder.
