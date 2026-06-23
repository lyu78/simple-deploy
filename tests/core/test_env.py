import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.env import (  # noqa: E402
    load_dotenv_file,
    load_env,
    require_value,
    to_git_bash_path,
    windows_release_root,
    wsl_to_windows_path,
)


class EnvTests(unittest.TestCase):
    def test_load_dotenv_file_strips_bom_and_ignores_valueless_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\ufeffKEY=value\nEMPTY\nQUOTED=\"hello world\"\n",
                encoding="utf-8",
            )

            values = load_dotenv_file(env_file, required=True)

        self.assertEqual(values, {"KEY": "value", "QUOTED": "hello world"})

    def test_load_dotenv_file_handles_missing_required_and_optional_files(self):
        missing = Path("missing.env")

        self.assertEqual(load_dotenv_file(missing, required=False), {})
        with self.assertRaisesRegex(RuntimeError, "Файл не найден"):
            load_dotenv_file(missing, required=True)

    def test_load_env_merges_secrets_over_config_and_applies_db_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            secrets_file = root / "local.secrets.env"
            env_file.write_text(
                "DB_LOGIN_USER=public\nDEV_DOMAIN=dev.example.local\n",
                encoding="utf-8",
            )
            secrets_file.write_text("DB_LOGIN_USER=secret\n", encoding="utf-8")

            env = load_env(env_file, secrets_file, require_secrets=False)

        self.assertEqual(env["DB_LOGIN_USER"], "secret")
        self.assertEqual(env["DB_LOGIN_PASSWORD"], "")
        self.assertEqual(env["DEV_DOMAIN"], "dev.example.local")

    def test_load_env_requires_db_credentials_when_secrets_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            secrets_file = root / "local.secrets.env"
            env_file.write_text("DEV_DOMAIN=dev.example.local\n", encoding="utf-8")
            secrets_file.write_text(
                "DB_LOGIN_USER=\nDB_LOGIN_PASSWORD=change-me\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "DB_LOGIN_USER"):
                load_env(env_file, secrets_file, require_secrets=True)

            secrets_file.write_text(
                "DB_LOGIN_USER=postgres\nDB_LOGIN_PASSWORD=change-me\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "DB_LOGIN_PASSWORD"):
                load_env(env_file, secrets_file, require_secrets=True)

    def test_require_value_trims_and_rejects_empty_values(self):
        self.assertEqual(require_value({"KEY": " value "}, "KEY"), "value")

        with self.assertRaisesRegex(RuntimeError, "KEY"):
            require_value({"KEY": " "}, "KEY")

    def test_path_helpers_convert_wsl_windows_and_git_bash_paths(self):
        self.assertEqual(
            wsl_to_windows_path("/mnt/c/releases/app"),
            r"C:\releases\app",
        )
        self.assertEqual(wsl_to_windows_path("/opt/app"), "")
        self.assertEqual(to_git_bash_path(r"C:\repos\backend"), "/c/repos/backend")
        self.assertEqual(to_git_bash_path("/opt/app"), "/opt/app")

    def test_windows_release_root_prefers_explicit_then_wsl_then_default(self):
        self.assertEqual(
            windows_release_root({"RELEASE_ROOT_WINDOWS": r"D:\releases"}),
            Path(r"D:\releases"),
        )
        self.assertEqual(
            windows_release_root({"RELEASE_ROOT_WSL": "/mnt/c/releases"}),
            Path(r"C:\releases"),
        )
        self.assertTrue(str(windows_release_root({})).endswith("releases"))


if __name__ == "__main__":
    unittest.main()
