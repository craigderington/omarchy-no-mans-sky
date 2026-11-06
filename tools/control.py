"""Install and control the Omarchy No Man's Sky companion, without root."""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "omarchy-no-mans-sky"
MANIFEST = STATE / "install.json"
UNIT = "omarchy-no-mans-sky.service"
THEME = CONFIG / "omarchy/themes/no-mans-sky"
CURRENT = HOME / ".local/state/omarchy/current"
MARKER = '\n-- BEGIN omarchy-no-mans-sky\nrequire("hypr.no-mans-sky")\n-- END omarchy-no-mans-sky\n'


def run(*args, check=True, env=None):
    return subprocess.run(args, check=check, text=True, capture_output=True, env=env)


def atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".nms-tmp")
    tmp.write_text(text)
    tmp.replace(path)


def fingerprint(path: Path):
    if path.is_symlink():
        return {"kind": "link", "target": os.readlink(path)}
    if path.is_file():
        return {"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if path.exists():
        raise ValueError(f"Refusing to replace a directory or special file: {path}")
    return {"kind": "absent"}


def read_manifest():
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None


def save_manifest(manifest):
    atomic(MANIFEST, json.dumps(manifest, indent=2) + "\n")


def remember(manifest, path):
    key = str(path)
    if key not in manifest["files"]:
        original = fingerprint(path)
        if original["kind"] == "file":
            backup = STATE / "backups" / str(len(manifest["files"]))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            original["backup"] = str(backup)
        manifest["files"][key] = {"original": original}
        save_manifest(manifest)


def managed_write(manifest, path, text):
    remember(manifest, path)
    installed = manifest["files"][str(path)].get("installed")
    if installed and fingerprint(path) != installed:
        raise ValueError(f"Preserving edits to managed file: {path}; review before updating.")
    if path.is_symlink():
        path.unlink()
    atomic(path, text)
    manifest["files"][str(path)]["installed"] = fingerprint(path)
    save_manifest(manifest)


def managed_link(manifest, path, target):
    remember(manifest, path)
    if path.is_symlink() or path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    manifest["files"][str(path)]["installed"] = fingerprint(path)
    save_manifest(manifest)


def install():
    manifest = read_manifest()
    if manifest and manifest["repository"] != str(ROOT):
        raise ValueError("Another checkout owns this installation; uninstall it first.")
    if manifest is None:
        previous = (CURRENT / "theme.name").read_text().strip() if (CURRENT / "theme.name").exists() else ""
        manifest = {"repository": str(ROOT), "previous_theme": previous, "files": {}}
        save_manifest(manifest)
    for tool in ("qs", "hyprctl", "omarchy", "omarchy-shell"):
        if not shutil.which(tool):
            raise ValueError(f"Missing dependency: {tool}")
    # No whole Hyprland or shell configuration is replaced.
    bindings = CONFIG / "hypr/bindings.lua"
    remember(manifest, bindings)
    current = bindings.read_text() if bindings.exists() else ""
    if MARKER not in current:
        if "-- BEGIN omarchy-no-mans-sky" in current:
            raise ValueError("The No Man's Sky binding block was edited; review it before reinstalling.")
        managed_write(manifest, bindings, current + MARKER)
    managed_write(manifest, CONFIG / "hypr/no-mans-sky.lua", (ROOT / "hypr/no-mans-sky.lua").read_text())
    managed_link(manifest, HOME / ".local/bin/omarchy-nms", ROOT / "bin/omarchy-nms")
    managed_write(manifest, THEME / "colors.toml", (ROOT / "colors.toml").read_text())
    managed_write(manifest, THEME / "shell.toml", (ROOT / "theme/shell.toml").read_text())
    executable = str(ROOT / "quickshell").replace("%", "%%").replace('"', '\\"')
    unit = f'''[Unit]
Description=No Man's Sky interactive landscape and star map
Documentation=file://{ROOT}/README.md
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/qs --path "{executable}" --no-duplicate
Restart=on-failure
RestartSec=3
Environment=QT_QPA_PLATFORM=wayland
Environment=NMS_SYNC_PALETTE=1

[Install]
WantedBy=graphical-session.target
'''
    managed_write(manifest, CONFIG / "systemd/user" / UNIT, unit)
    run("hyprctl", "reload")
    errors = run("hyprctl", "configerrors").stdout.strip()
    if errors:
        raise ValueError(errors)
    print(f"Installed from {ROOT}; backups and manifest: {STATE}")


def apply_theme(name):
    # Generate Omarchy's normal app templates without invoking the user's
    # remote-machine sync hook or replacing the existing fallback wallpaper.
    env = dict(os.environ, OMARCHY_THEME_HEADLESS="1", OMARCHY_THEME_SKIP_BACKGROUND="1")
    run("omarchy", "theme", "set", name, env=env)
    payloads = [base64.b64encode((CURRENT / "theme" / file).read_bytes()).decode() if (CURRENT / "theme" / file).exists() else "" for file in ("colors.toml", "shell.toml")]
    run("omarchy-shell", "shell", "applyTheme", *payloads)
    run("hyprctl", "reload")
    errors = run("hyprctl", "configerrors").stdout.strip()
    if errors:
        raise ValueError(errors)
    run("omarchy", "restart", "terminal")


def start():
    # Stop only a development instance of this exact config before systemd
    # takes ownership; Omarchy's own Quickshell process is never touched.
    run("qs", "kill", "-p", str(ROOT / "quickshell"), check=False)
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", UNIT)
    print(run("systemctl", "--user", "is-active", UNIT).stdout.strip())


def palette_tokens(palette):
    colors = palette["colors"]
    values = [colors[f"color{i}"] for i in range(16)]
    values += [palette["special"][key] for key in ("background", "foreground")]
    if not all(isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in values):
        raise ValueError("Palette must contain sixteen RGB hex colors and a background/foreground.")
    tokens = tomllib.loads((ROOT / "colors.toml").read_text())
    tokens.update(background=palette["special"]["background"], foreground=palette["special"]["foreground"], accent=colors["color9"], selection=colors["color8"], muted=colors["color8"], dark_foreground=colors["color8"], light_foreground=colors["color7"], bright_foreground=colors["color15"])
    for i, name in enumerate(("red", "green", "yellow", "blue", "magenta", "cyan"), 1):
        tokens[name] = colors[f"color{i}"]
        tokens["bright_" + name] = colors[f"color{i+8}"]
    def dim(hexcolor, factor):
        return "#" + "".join(f"{round(int(hexcolor[i:i+2],16)*factor):02x}" for i in (1,3,5))
    tokens.update(dark_background=dim(tokens["background"], 0.78), darker_background=dim(tokens["background"], 0.6), lighter_background=colors["color8"], orange=colors["color3"], brown=dim(colors["color3"], 0.6))
    return tokens


def sync_palette():
    if not (CURRENT / "theme.name").exists() or (CURRENT / "theme.name").read_text().strip() != "no-mans-sky":
        return
    manifest = read_manifest()
    if not manifest:
        return
    palette_file = STATE / "palette.json"
    if not palette_file.exists():
        return
    if palette_file.stat().st_size > 16384:
        raise ValueError("Palette file is too large.")
    tokens = palette_tokens(json.loads(palette_file.read_text()))
    content = "\n".join(f'{key} = {json.dumps(value)}' for key, value in tokens.items()) + "\n"
    if (THEME / "colors.toml").read_text() == content:
        return
    managed_write(manifest, THEME / "colors.toml", content)
    shell = (ROOT / "theme/shell.toml").read_text()
    base = tomllib.loads((ROOT / "colors.toml").read_text())
    for key in ("background", "foreground", "accent"):
        shell = shell.replace(base[key], tokens[key])
    managed_write(manifest, THEME / "shell.toml", shell)
    apply_theme("no-mans-sky")


def restore(path, record):
    if fingerprint(path) != record.get("installed"):
        print(f"Preserved subsequent edits: {path}")
        return False
    original = record["original"]
    path.unlink(missing_ok=True)
    if original["kind"] == "file":
        shutil.copy2(original["backup"], path)
    elif original["kind"] == "link":
        path.symlink_to(original["target"])
    return True


def uninstall():
    manifest = read_manifest()
    if not manifest:
        print("Nothing installed.")
        return
    run("systemctl", "--user", "disable", "--now", UNIT)
    run("qs", "kill", "-p", str(ROOT / "quickshell"), check=False)
    bindings = CONFIG / "hypr/bindings.lua"
    # Remove only our block, retaining any user changes made since install.
    if bindings.exists():
        original_text = bindings.read_text()
        if MARKER in original_text:
            atomic(bindings, original_text.replace(MARKER, ""))
    if (CURRENT / "theme.name").exists() and (CURRENT / "theme.name").read_text().strip() == "no-mans-sky":
        if manifest["previous_theme"] and manifest["previous_theme"] != "no-mans-sky":
            apply_theme(manifest["previous_theme"])
    for name, record in reversed(list(manifest["files"].items())):
        if name != str(bindings):
            restore(Path(name), record)
    run("systemctl", "--user", "daemon-reload")
    run("hyprctl", "reload")
    MANIFEST.rename(STATE / "last-uninstall.json")
    print("Uninstalled. Original files restored; world state and backups retained.")


def ipc(action):
    return run("qs", "ipc", "-p", str(ROOT / "quickshell"), "call", "nms", action)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "activate", "start", "stop", "map", "world", "close", "abort", "status", "doctor", "sync-palette", "uninstall"])
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--no-theme", action="store_true")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    # Palette saves can coincide with startup/install; serialize all mutations.
    with (STATE / "control.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "install":
            install()
            if not args.no_theme:
                apply_theme("no-mans-sky")
            if not args.no_start:
                start()
        elif args.command == "activate":
            if not read_manifest():
                raise ValueError("Run install first.")
            apply_theme("no-mans-sky")
            start()
        elif args.command == "start":
            start()
        elif args.command == "stop":
            run("systemctl", "--user", "stop", UNIT)
        elif args.command == "doctor":
            print("Service:", run("systemctl", "--user", "is-active", UNIT).stdout.strip())
            print("Startup:", run("systemctl", "--user", "is-enabled", UNIT).stdout.strip())
            print("Renderer:", ipc("status").stdout.strip())
            errors = run("hyprctl", "configerrors").stdout.strip()
            if errors:
                raise ValueError(errors)
            print("Hyprland configuration: clean")
        elif args.command == "sync-palette":
            sync_palette()
        elif args.command == "uninstall":
            uninstall()
        else:
            action = "toggle" if args.command == "map" else args.command
            print(ipc(action).stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        print(f"omarchy-nms: {detail.strip()}", file=sys.stderr)
        sys.exit(1)
