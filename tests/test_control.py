import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("control", Path(__file__).resolve().parents[1] / "tools/control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        state = home / ".local/state/omarchy-no-mans-sky"
        omarchy = home / "stock-omarchy"
        source = omarchy / "shell/plugins/lock"
        source.mkdir(parents=True)
        (source / "Service.qml").write_text("// Stock authentication service, kept byte for byte\n")
        (source / "FingerprintModel.js").write_text("// Stock fingerprint flow\n")
        (source / "manifest.json").write_text(json.dumps({"schemaVersion": 1,
            "id": "omarchy.lock", "kinds": ["service"], "keepLoaded": True,
            "entryPoints": {"service": "Service.qml"},
            "omarchy": {"capabilities": ["authentication"]}}))
        self.paths = patch.multiple(control, HOME=home, CONFIG=home / ".config", STATE=state,
            MANIFEST=state / "install.json", CURRENT=home / ".local/state/omarchy/current",
            OMARCHY=omarchy,
            THEME=home / ".config/omarchy/themes/no-mans-sky")
        self.paths.start()
        self.addCleanup(self.paths.stop)
        def fake_run(*args, **kwargs):
            output = json.dumps([{"id": control.LOCK_ID}]) if args == ("omarchy-shell", "shell", "listPlugins") else ""
            return types.SimpleNamespace(stdout=output, stderr="")
        self.mock_run = patch.object(control, "run", side_effect=fake_run)
        self.mock_run.start()
        self.addCleanup(self.mock_run.stop)
        self.tools = patch.object(control.shutil, "which", return_value="/usr/bin/tool")
        self.tools.start()
        self.addCleanup(self.tools.stop)
        theme_lock = patch.object(control, "theme_lock_path", return_value=home / "theme-set.lock")
        theme_lock.start()
        self.addCleanup(theme_lock.stop)

    def test_install_twice_then_rollback_preserves_later_bindings(self):
        bindings = control.CONFIG / "hypr/bindings.lua"
        bindings.parent.mkdir(parents=True)
        bindings.write_text('-- Personal keybindings\n')
        original_module = control.CONFIG / "hypr/no-mans-sky.lua"
        original_module.write_text('-- Existing user module\n')
        control.CURRENT.mkdir(parents=True)
        (control.CURRENT / "theme.name").write_text("abyssal-cartographer\n")
        control.install()
        control.install()
        self.assertEqual(bindings.read_text().count(control.MARKER), 1)
        preview = control.THEME / "preview.png"
        self.assertTrue(preview.is_file())
        self.assertEqual(preview.resolve(), control.ROOT / "preview.png")
        bindings.write_text(bindings.read_text() + '-- Added after installation\n')
        (control.CURRENT / "theme.name").write_text("no-mans-sky\n")
        with patch.object(control, "apply_theme") as apply:
            control.uninstall()
            apply.assert_called_once_with("abyssal-cartographer")
        self.assertEqual(bindings.read_text(), '-- Personal keybindings\n-- Added after installation\n')
        self.assertEqual(original_module.read_text(), '-- Existing user module\n')
        self.assertFalse((control.CONFIG / "systemd/user" / control.UNIT).exists())
        self.assertFalse((control.HOME / ".local/bin/omarchy-nms").is_symlink())
        self.assertFalse(preview.is_symlink())

    def test_rollback_preserves_edits_to_installed_files(self):
        control.install()
        module = control.CONFIG / "hypr/no-mans-sky.lua"
        module.write_text('-- User modified the module\n')
        control.uninstall()
        self.assertEqual(module.read_text(), '-- User modified the module\n')

    def test_reinstall_refuses_to_overwrite_user_changes(self):
        control.install()
        module = control.CONFIG / "hypr/no-mans-sky.lua"
        module.write_text('-- My changes\n')
        with self.assertRaisesRegex(ValueError, "Preserving edits"):
            control.install()
        self.assertEqual(module.read_text(), '-- My changes\n')

    def test_palette_validation_and_color_mapping(self):
        palette = {"special": {"background": "#101820", "foreground": "#e2e8ef"},
            "colors": {f"color{i}": f"#{i:02x}aabb" for i in range(16)}}
        tokens = control.palette_tokens(palette)
        self.assertEqual(tokens["accent"], "#09aabb")
        self.assertEqual(tokens["bright_cyan"], "#0eaabb")
        self.assertEqual(tokens["background"], "#101820")
        palette["colors"]["color9"] = '$(malicious command)'
        with self.assertRaises(ValueError):
            control.palette_tokens(palette)

    def test_uninstall_does_not_switch_a_subsequently_selected_theme(self):
        control.install()
        control.CURRENT.mkdir(parents=True)
        (control.CURRENT / "theme.name").write_text("nord\n")
        with patch.object(control, "apply_theme") as apply:
            control.uninstall()
            apply.assert_not_called()
    def test_lock_clone_preserves_stock_authentication_and_rolls_back(self):
        control.install()
        destination = control.CONFIG / "omarchy/plugins" / control.LOCK_ID
        source = control.OMARCHY / "shell/plugins/lock"
        for name in ("Service.qml", "FingerprintModel.js"):
            self.assertEqual((destination / name).read_bytes(), (source / name).read_bytes())
        metadata = json.loads((destination / "manifest.json").read_text())
        self.assertEqual(metadata["omarchy"]["clonedFrom"], "omarchy.lock")
        self.assertEqual(metadata["omarchy"]["capabilities"], ["authentication"])
        self.assertTrue((destination / "landscape.png").is_file())
        self.assertTrue((destination / "i18n/en.json").is_file())
        with patch.object(control, "run", return_value=types.SimpleNamespace(stdout="")) as run:
            control.uninstall()
            run.assert_any_call("omarchy", "plugin", "disable", control.LOCK_ID)
        self.assertFalse(destination.exists())

    def test_lock_install_and_uninstall_refuse_a_locked_session(self):
        control.install()
        manifest = control.read_manifest()
        with patch.object(control, "run", return_value=types.SimpleNamespace(stdout="true\n")):
            with self.assertRaisesRegex(ValueError, "Unlock the session"):
                control.install_lock(manifest)
            with self.assertRaisesRegex(ValueError, "Unlock the session"):
                control.uninstall()
        self.assertEqual(control.read_manifest(), manifest)

    def test_lock_install_preserves_a_personal_clone(self):
        destination = control.CONFIG / "omarchy/plugins/personal.lock"
        destination.mkdir(parents=True)
        metadata = json.dumps({"omarchy": {"clonedFrom": "omarchy.lock"}})
        (destination / "manifest.json").write_text(metadata)
        with self.assertRaisesRegex(ValueError, "Preserving another lock-screen clone"):
            control.install()
        self.assertEqual((destination / "manifest.json").read_text(), metadata)
        self.assertFalse((destination.parent / control.LOCK_ID).exists())

    def test_lock_rollback_preserves_later_view_edits(self):
        control.install()
        view = control.CONFIG / "omarchy/plugins" / control.LOCK_ID / "LockView.qml"
        view.write_text("// My lock screen\n")
        control.uninstall()
        self.assertEqual(view.read_text(), "// My lock screen\n")

    def prepare_palette_sync(self):
        control.install()
        control.CURRENT.mkdir(parents=True)
        (control.CURRENT / "theme.name").write_text("no-mans-sky\n")
        palette = {"special": {"background": "#101820", "foreground": "#e2e8ef"},
            "colors": {f"color{i}": f"#{i:02x}aabb" for i in range(16)}}
        (control.STATE / "palette.json").write_text(json.dumps(palette))

    def test_palette_refresh_keeps_theme_selection_and_background(self):
        self.prepare_palette_sync()
        current = control.CURRENT / "theme"
        current.mkdir()
        (current / "old-generated-file").write_text("previous palette")
        (control.CURRENT / "background").symlink_to("/wallpapers/personal.png")
        with patch.object(control, "run", return_value=types.SimpleNamespace(stdout="")) as run:
            control.sync_palette()
            run.assert_any_call("omarchy", "theme", "set", "templates")
            self.assertFalse(any(call.args == ("omarchy", "theme", "set", "no-mans-sky") for call in run.call_args_list))
        self.assertEqual(control.selected_theme(), "no-mans-sky")
        self.assertEqual((current / "colors.toml").read_bytes(), (control.THEME / "colors.toml").read_bytes())
        self.assertEqual((current / "shell.toml").read_bytes(), (control.THEME / "shell.toml").read_bytes())
        self.assertEqual((control.CURRENT / "background").readlink(), Path("/wallpapers/personal.png"))
        self.assertFalse((control.CURRENT / "next-theme").exists())

    def test_theme_changed_while_sync_waited_is_preserved(self):
        self.prepare_palette_sync()
        original = (control.THEME / "colors.toml").read_bytes()
        with patch.object(control, "selected_theme", side_effect=["no-mans-sky", "nord"]), \
                patch.object(control, "refresh_current_palette") as refresh:
            control.sync_palette()
            refresh.assert_not_called()
        self.assertEqual((control.THEME / "colors.toml").read_bytes(), original)

    def test_template_failure_keeps_current_generated_theme(self):
        self.prepare_palette_sync()
        current = control.CURRENT / "theme"
        current.mkdir()
        (current / "colors.toml").write_text("previous palette")
        error = control.subprocess.CalledProcessError(1, ["omarchy", "theme", "set", "templates"])
        with patch.object(control, "run", side_effect=error):
            with self.assertRaises(control.subprocess.CalledProcessError):
                control.refresh_current_palette()
        self.assertEqual((current / "colors.toml").read_text(), "previous palette")
        self.assertFalse((control.CURRENT / "next-theme").exists())


if __name__ == "__main__":
    unittest.main()
