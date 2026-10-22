"""Validate shortcut paths without creating startup entries (Windows only)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "win32", "PowerShell/Windows shortcut-path validation")
class AutostartPaths(unittest.TestCase):
    def inspect(self, script):
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Inspect"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return json.loads(result.stdout)

    def test_packaged_script_targets_adjacent_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            script = folder / "install_autostart.ps1"
            shutil.copyfile(Path(__file__).resolve().parents[1] / "tools" / script.name, script)
            (folder / "NetcheckCenter.exe").touch()
            result = self.inspect(script)
            # PowerShell expands Windows 8.3 aliases (RUNNER~1); compare the
            # actual files/directories instead of their textual spelling.
            self.assertTrue(Path(result["TargetPath"]).samefile(folder / "NetcheckCenter.exe"))
            self.assertTrue(Path(result["WorkingDirectory"]).samefile(folder))
            self.assertEqual(result["Arguments"], "--minimized")
            self.assertEqual(Path(result["LinkPath"]).name, "AutoNetwork NetcheckCenter.lnk")

    def test_source_script_targets_repository_app(self):
        root = Path(__file__).resolve().parents[1]
        result = self.inspect(root / "tools" / "install_autostart.ps1")
        self.assertEqual(Path(result["WorkingDirectory"]), root)
        self.assertIn(str(root / "app.py"), result["Arguments"])
        self.assertEqual(Path(result["TargetPath"]).name.lower(), "pythonw.exe")
