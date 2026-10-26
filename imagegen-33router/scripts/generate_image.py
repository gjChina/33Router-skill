#!/usr/bin/env python3
"""Generate images through the active cc-switch Codex provider."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-image-2"
SKILL_CONFIG = Path(
    os.environ.get("IMAGEGEN_CONFIG", str(Path.home() / ".codex" / "imagegen-33router.json"))
)


def emit(payload: dict[str, Any], code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


def fail(message: str, code: int = 1) -> int:
    return emit({"ok": False, "error": message}, code)


def candidate_databases() -> list[Path]:
    home = Path.home()
    candidates = [
        Path(os.environ["CC_SWITCH_DB"]) if os.environ.get("CC_SWITCH_DB") else None,
        home / ".cc-switch" / "cc-switch.db",
        home / "AppData" / "Roaming" / "cc-switch" / "cc-switch.db",
        home / "AppData" / "Local" / "cc-switch" / "cc-switch.db",
    ]
    return [path for path in candidates if path is not None]


def find_database() -> Path | None:
    return next((path for path in candidate_databases() if path.is_file()), None)


def load_provider() -> dict[str, str]:
    db_path = find_database()
    if db_path is None:
        raise RuntimeError(
            "cc-switch database was not found. Install cc-switch, import a provider, "
            "or set CC_SWITCH_DB to its database path."
        )

    connection = None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT name, settings_config FROM providers "
            "WHERE app_type = 'codex' AND is_current = 1 "
            "ORDER BY sort_index LIMIT 1"
        ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not read cc-switch database: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()

    if row is None:
        raise RuntimeError("cc-switch has no current Codex provider selected.")

    name, raw_settings = row
    try:
        settings = json.loads(raw_settings)
        api_key = settings.get("auth", {}).get("OPENAI_API_KEY")
        config = settings.get("config", "")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The selected cc-switch provider has invalid settings.") from exc

    match = re.search(r"^\s*base_url\s*=\s*\"([^\"]+)\"", config, re.MULTILINE)
    base_url = match.group(1).strip() if match else ""
    if not api_key or not base_url:
        raise RuntimeError(
            "The selected cc-switch provider is missing OPENAI_API_KEY or base_url."
        )

    return {
        "name": str(name),
        "api_key": str(api_key),
        "base_url": base_url,
        "db_path": str(db_path),
    }


def load_model() -> tuple[str, bool]:
    if not SKILL_CONFIG.is_file():
        return DEFAULT_MODEL, False
    try:
        data = json.loads(SKILL_CONFIG.read_text(encoding="utf-8"))
        model = data.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip(), True
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_MODEL, False


def save_model(model: str) -> None:
    SKILL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "model": model.strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    SKILL_CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(SKILL_CONFIG, 0o600)
    except OSError:
        pass


def command_status(_: argparse.Namespace) -> int:
    model, configured = load_model()
    try:
        provider = load_provider()
    except RuntimeError as exc:
        return fail(str(exc))
    return emit(
        {
            "ok": True,
            "model": model,
            "model_configured": configured,
            "provider": provider["name"],
            "base_url": provider["base_url"],
            "db_path": provider["db_path"],
            "config_path": str(SKILL_CONFIG),
        }
    )


def command_set_model(args: argparse.Namespace) -> int:
    model = args.model.strip()
    if not model:
        return fail("Model id cannot be empty.")
    try:
        save_model(model)
    except OSError as exc:
        return fail(f"Could not save model configuration: {exc}")
    return emit({"ok": True, "model": model, "config_path": str(SKILL_CONFIG)})


def download_image(url: str, api_key: str) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError:
        with urllib.request.urlopen(url, timeout=120) as response:
            return response.read()


def command_generate(args: argparse.Namespace) -> int:
    model, _ = load_model()
    if args.model:
        model = args.model.strip()
    try:
        provider = load_provider()
    except RuntimeError as exc:
        return fail(str(exc))

    output = Path(args.output).expanduser()
    if output.exists() and not args.force:
        return fail(f"Output already exists: {output}. Use --force to replace it.")

    try:
        from openai import OpenAI
    except ImportError:
        return fail("The openai package is missing. Run: python -m pip install --user openai")

    try:
        client = OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
        result = client.images.generate(
            model=model,
            prompt=args.prompt,
            size=args.size,
            quality=args.quality,
        )
        item = result.data[0]
        if getattr(item, "b64_json", None):
            raw = base64.b64decode(item.b64_json)
            response_format = "b64_json"
        elif getattr(item, "url", None):
            raw = download_image(item.url, provider["api_key"])
            response_format = "url"
        else:
            return fail("The provider returned no image data or URL.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    except Exception as exc:  # SDK errors vary across OpenAI-compatible providers.
        return fail(str(exc))

    return emit(
        {
            "ok": True,
            "path": str(output.resolve()),
            "bytes": len(raw),
            "model": model,
            "provider": provider["name"],
            "response_format": response_format,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Show provider and model status without secrets")
    status.set_defaults(func=command_status)

    set_model = commands.add_parser("set-model", help="Persist the default image model")
    set_model.add_argument("--model", required=True)
    set_model.set_defaults(func=command_set_model)

    generate = commands.add_parser("generate", help="Generate one image")
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--model")
    generate.add_argument("--size", default="1536x1024")
    generate.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="high")
    generate.add_argument("--output", required=True)
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(func=command_generate)
    return root


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(args.func(args))
