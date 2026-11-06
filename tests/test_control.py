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
        self.paths = patch.multiple(control, HOME=home, CONFIG=home / ".config", STATE=state,
            MANIFEST=state / "install.json", CURRENT=home / ".local/state/omarchy/current",
            THEME=home / ".config/omarchy/themes/no-mans-sky")
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.mock_run = patch.object(control, "run", return_value=types.SimpleNamespace(stdout="", stderr=""))
        self.mock_run.start()
        self.addCleanup(self.mock_run.stop)
        self.tools = patch.object(control.shutil, "which", return_value="/usr/bin/tool")
        self.tools.start()
        self.addCleanup(self.tools.stop)

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
        bindings.write_text(bindings.read_text() + '-- Added after installation\n')
        (control.CURRENT / "theme.name").write_text("no-mans-sky\n")
        with patch.object(control, "apply_theme") as apply:
            control.uninstall()
            apply.assert_called_once_with("abyssal-cartographer")
        self.assertEqual(bindings.read_text(), '-- Personal keybindings\n-- Added after installation\n')
        self.assertEqual(original_module.read_text(), '-- Existing user module\n')
        self.assertFalse((control.CONFIG / "systemd/user" / control.UNIT).exists())
        self.assertFalse((control.HOME / ".local/bin/omarchy-nms").is_symlink())

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


if __name__ == "__main__":
    unittest.main()
