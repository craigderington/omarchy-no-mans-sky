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
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "omarchy-no-mans-sky"
MANIFEST = STATE / "install.json"
UNIT = "omarchy-no-mans-sky.service"
THEME = CONFIG / "omarchy/themes/no-mans-sky"
CURRENT = HOME / ".local/state/omarchy/current"
OMARCHY = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"))
LOCK_ID = "nms.lock"
MARKER = '\n-- BEGIN omarchy-no-mans-sky\nrequire("hypr.no-mans-sky")\n-- END omarchy-no-mans-sky\n'


def run(*args, check=True, env=None):
    return subprocess.run(args, check=check, text=True, capture_output=True, env=env)


def atomic(path: Path, text: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".nms-tmp")
    if isinstance(text, bytes):
        tmp.write_bytes(text)
    else:
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


def install_lock(manifest):
    """Clone the installed lock service, replacing only its presentation."""
    if run("omarchy-shell", "lock", "isLocked").stdout.strip() == "true":
        raise ValueError("Unlock the session before installing the lock screen.")
    source = OMARCHY / "shell/plugins/lock"
    if not (source / "Service.qml").is_file():
        raise ValueError("The Omarchy 4.5 lock plugin is required.")
    plugins = CONFIG / "omarchy/plugins"
    destination = plugins / LOCK_ID
    # A personal lock clone may contain functional changes. Leave it in place.
    for candidate in plugins.glob("*/manifest.json"):
        metadata = json.loads(candidate.read_text())
        if metadata.get("omarchy", {}).get("clonedFrom") == "omarchy.lock" and candidate.parent != destination:
            raise ValueError(f"Preserving another lock-screen clone: {candidate.parent}")
    owns_files = any(Path(name).is_relative_to(destination) for name in manifest["files"])
    if destination.exists() and not owns_files:
        raise ValueError(f"Preserving an existing plugin directory: {destination}")
    # Publish the manifest last so first discovery sees a complete plugin.
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "LockView.qml"):
            managed_write(manifest, destination / path.relative_to(source), path.read_bytes())
    for path in sorted((ROOT / "lockscreen").rglob("*")):
        if path.is_file():
            managed_write(manifest, destination / path.relative_to(ROOT / "lockscreen"), path.read_bytes())
    managed_write(manifest, destination / "landscape.png", (ROOT / "docs/assets/landscape.png").read_bytes())
    metadata = json.loads((source / "manifest.json").read_text())
    metadata.update(id=LOCK_ID, name="No Man’s Sky Lock Screen",
        description="No Man’s Sky presentation with Omarchy password and fingerprint authentication.")
    metadata.setdefault("omarchy", {})["clonedFrom"] = "omarchy.lock"
    managed_write(manifest, destination / "manifest.json", json.dumps(metadata, indent=2) + "\n")
    was_installed = manifest.get("lock_plugin", False)
    manifest["lock_plugin"] = True
    save_manifest(manifest)
    run("omarchy-shell", "shell", "rescanPlugins")
    # Discovery runs asynchronously in the shell, as in `plugin clone`.
    for attempt in range(40):
        catalog = json.loads(run("omarchy-shell", "shell", "listPlugins").stdout)
        if any(plugin["id"] == LOCK_ID for plugin in catalog):
            break
        time.sleep(0.05)
    else:
        raise ValueError("The shell did not discover the lock-screen clone.")
    # keepLoaded services survive a code rescan. Re-enable our clone while
    # unlocked to pick up an updated view/service without restarting the shell.
    if was_installed:
        run("omarchy", "plugin", "disable", LOCK_ID)
    try:
        run("omarchy", "plugin", "enable", LOCK_ID)
        run("omarchy-shell", "lock", "isLocked")
    except subprocess.CalledProcessError:
        run("omarchy", "plugin", "disable", LOCK_ID, check=False)
        raise
    print("Installed No Man’s Sky lock screen; preview with omarchy-nms preview-lock.")


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
    managed_link(manifest, THEME / "preview.png", ROOT / "preview.png")
    install_lock(manifest)
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


def refresh_current_palette():
    """Regenerate app colors without selecting a theme or running its hooks.

    The caller holds Omarchy's theme-set lock and has checked the selected name.
    """
    stage = CURRENT / "next-theme"
    if stage.exists():
        raise ValueError(f"Theme staging directory already exists: {stage}")
    try:
        shutil.copytree(THEME, stage, symlinks=True)
        run("omarchy", "theme", "set", "templates")
        # Keep the old generated theme until replacement succeeds. The shared
        # lock prevents Omarchy's own switcher from staging another theme here.
        with tempfile.TemporaryDirectory(prefix=".nms-palette-", dir=CURRENT) as temporary:
            previous = Path(temporary) / "theme"
            (CURRENT / "theme").rename(previous)
            try:
                stage.rename(CURRENT / "theme")
            except OSError:
                previous.rename(CURRENT / "theme")
                raise
        payloads = [base64.b64encode((CURRENT / "theme" / file).read_bytes()).decode()
            for file in ("colors.toml", "shell.toml")]
        run("omarchy-shell", "shell", "applyTheme", *payloads)
        run("hyprctl", "reload")
        errors = run("hyprctl", "configerrors").stdout.strip()
        if errors:
            raise ValueError(errors)
        run("omarchy", "restart", "terminal")
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def selected_theme():
    name = CURRENT / "theme.name"
    return name.read_text().strip() if name.exists() else ""


def theme_lock_path():
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "omarchy-theme-set.lock"


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
    if selected_theme() != "no-mans-sky":
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
    with theme_lock_path().open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # A user selection may have completed while palette generation waited.
        if selected_theme() != "no-mans-sky":
            return
        shell = (ROOT / "theme/shell.toml").read_text()
        base = tomllib.loads((ROOT / "colors.toml").read_text())
        for key in ("background", "foreground", "accent"):
            shell = shell.replace(base[key], tokens[key])
        if ((THEME / "colors.toml").read_text() == content
                and (CURRENT / "theme/colors.toml").exists()
                and (CURRENT / "theme/colors.toml").read_text() == content
                and (CURRENT / "theme/shell.toml").exists()
                and (CURRENT / "theme/shell.toml").read_text() == shell):
            return
        managed_write(manifest, THEME / "colors.toml", content)
        managed_write(manifest, THEME / "shell.toml", shell)
        refresh_current_palette()


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
    if manifest.get("lock_plugin"):
        if run("omarchy-shell", "lock", "isLocked").stdout.strip() == "true":
            raise ValueError("Unlock the session before uninstalling the lock screen.")
        # Disabling a clone restores Omarchy's original lock through the
        # shell's own plugin API, without restoring an old shell.json.
        run("omarchy", "plugin", "disable", LOCK_ID)
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
    if manifest.get("lock_plugin"):
        run("omarchy-shell", "shell", "rescanPlugins")
        destination = CONFIG / "omarchy/plugins" / LOCK_ID
        if destination.is_dir():
            for directory in sorted((p for p in destination.rglob("*") if p.is_dir()), reverse=True):
                if not any(directory.iterdir()):
                    directory.rmdir()
            if not any(destination.iterdir()):
                destination.rmdir()
    run("systemctl", "--user", "daemon-reload")
    run("hyprctl", "reload")
    MANIFEST.rename(STATE / "last-uninstall.json")
    print("Uninstalled. Original files restored; world state and backups retained.")


def ipc(action):
    return run("qs", "ipc", "-p", str(ROOT / "quickshell"), "call", "nms", action)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "install-lock", "preview-lock", "activate", "start", "stop", "map", "world", "close", "abort", "status", "doctor", "sync-palette", "uninstall"])
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
        elif args.command == "install-lock":
            manifest = read_manifest()
            if not manifest or manifest["repository"] != str(ROOT):
                raise ValueError("Run install from this checkout first.")
            shell = (ROOT / "theme/shell.toml").read_text()
            base = tomllib.loads((ROOT / "colors.toml").read_text())
            palette = tomllib.loads((THEME / "colors.toml").read_text())
            for key in ("background", "foreground", "accent"):
                shell = shell.replace(base[key], palette[key])
            install_lock(manifest)
            managed_write(manifest, THEME / "shell.toml", shell)
            with theme_lock_path().open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if selected_theme() == "no-mans-sky":
                    refresh_current_palette()
        elif args.command == "preview-lock":
            print(run("omarchy-shell", "lock", "preview").stdout.strip())
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
