import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[2]
BUILDER_ROOT = ROOT / "tools-ci" / "builder"

sys.path.insert(0, str(BUILDER_ROOT))

os.environ.setdefault("FRONTEND_DEV_SERVER_NAME", "dev")
os.environ.setdefault("FRONTEND_TEST_SERVER_NAME", "test")
os.environ.setdefault("FRONTEND_PROD_SERVER_NAME", "prod")

import src.build as build_mod  # noqa: E402
import src.infra as infra  # noqa: E402


class BuilderInfraTests(unittest.TestCase):
    def test_build_version_and_branch_name_use_env_base_and_timestamp(self):
        class FakeDateTime:
            @classmethod
            def now(cls):
                return cls()

            def strftime(self, fmt):
                values = {
                    "%d%m%Y_%H%M": "23062026_1540",
                    "%Y-%m-%d-%H-%M-%S": "2026-06-23-15-40-30",
                }
                return values[fmt]

        with patch("src.infra.get_required_env", return_value="1.2"):
            with patch("src.infra.datetime", FakeDateTime):
                self.assertEqual(
                    infra.get_new_build_version(),
                    "1.2.23062026_1540",
                )
                self.assertEqual(
                    infra.get_new_branch_name("1.2.3"),
                    "feature/works-sync-1.2.3-2026-06-23-15-40-30",
                )

    def test_git_simple_commands_delegate_to_run_command(self):
        with patch("src.infra.run_command", return_value=True) as run_mock:
            self.assertTrue(infra.git_pull("repo"))
            self.assertTrue(infra.git_checkout_dev("repo"))
            self.assertTrue(infra.git_checkout_new_branch("repo", "release/1.2.3"))
            self.assertTrue(infra.git_npm_i("repo"))

        self.assertEqual(
            run_mock.call_args_list,
            [
                call("git stash && git pull", cwd="repo"),
                call("git stash && git checkout dev", cwd="repo"),
                call("git checkout -b release/1.2.3", cwd="repo"),
                call("npm i", cwd="repo"),
            ],
        )

    def test_git_add_commit_push_short_circuits_and_falls_back_to_plain_push(self):
        with patch("src.infra.run_command", side_effect=[False]) as run_mock:
            self.assertFalse(infra.git_add_commit_push("repo", "msg"))
        run_mock.assert_called_once_with("git add .", cwd="repo")

        with patch("src.infra.run_command", side_effect=[True, False]) as run_mock:
            self.assertFalse(infra.git_add_commit_push("repo", "msg"))
        self.assertEqual(run_mock.call_args_list[-1], call('git commit -m "msg"', cwd="repo"))

        with patch("src.infra.run_command", side_effect=[True, True, False, True]) as run_mock:
            self.assertTrue(infra.git_add_commit_push("repo", "msg"))
        self.assertEqual(
            run_mock.call_args_list,
            [
                call("git add .", cwd="repo"),
                call('git commit -m "msg"', cwd="repo"),
                call("git push --set-upstream origin HEAD", cwd="repo"),
                call("git push", cwd="repo"),
            ],
        )

        with patch("src.infra.run_command", side_effect=[True, True, False, False]):
            self.assertFalse(infra.git_add_commit_push("repo", "msg"))


class BuilderFrontendBuildTests(unittest.TestCase):
    def test_update_vite_build_version_validates_env_file_and_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            self.assertFalse(build_mod._update_vite_build_version(str(repo), "1.2.3"))

            (repo / ".env").write_text("OTHER=1\n", encoding="utf-8")
            self.assertFalse(build_mod._update_vite_build_version(str(repo), "1.2.3"))

            (repo / ".env").write_text("VITE_BUILD_VERSION=old\n", encoding="utf-8")
            with patch("src.build.set_key", return_value=(False, "key", "value")):
                self.assertFalse(build_mod._update_vite_build_version(str(repo), "1.2.3"))
            with patch("src.build.set_key", side_effect=RuntimeError("boom")):
                self.assertFalse(build_mod._update_vite_build_version(str(repo), "1.2.3"))
            with patch("src.build.set_key", return_value=(True, "key", "value")):
                self.assertTrue(build_mod._update_vite_build_version(str(repo), "1.2.3"))

    def test_create_frontend_build_uses_vite_mode_archive_script_and_server(self):
        with patch("src.build.run_command", return_value=True) as run_mock:
            self.assertTrue(
                build_mod._create_frontend_build(
                    "repo",
                    "1.2.3",
                    build_mod.frontend_building_dev,
                )
            )

        command = run_mock.call_args.args[0]
        self.assertIn("npx vite build --mode development", command)
        self.assertIn("sh archive_script_frontend.sh dev 1.2.3 dev", command)
        self.assertEqual(run_mock.call_args.kwargs["cwd"], "repo")

    def test_get_building_archive_exits_false_on_each_failed_step(self):
        scenarios = [
            (
                "env copy",
                lambda mocks: setattr(mocks["copy_file_to_repo2"], "side_effect", [False]),
            ),
            (
                "script copy",
                lambda mocks: setattr(mocks["copy_file_to_repo2"], "side_effect", [True, False]),
            ),
            (
                "version update",
                lambda mocks: setattr(mocks["_update_vite_build_version"], "return_value", False),
            ),
            (
                "frontend build",
                lambda mocks: setattr(mocks["_create_frontend_build"], "return_value", False),
            ),
        ]
        for name, setup_failure in scenarios:
            with self.subTest(name=name):
                patchers = {
                    "copy_file_to_repo2": patch("src.build.copy_file_to_repo2", return_value=True),
                    "_update_vite_build_version": patch(
                        "src.build._update_vite_build_version",
                        return_value=True,
                    ),
                    "_create_frontend_build": patch(
                        "src.build._create_frontend_build",
                        return_value=True,
                    ),
                }
                mocks = {key: patcher.start() for key, patcher in patchers.items()}
                try:
                    setup_failure(mocks)
                    self.assertFalse(
                        build_mod._get_building_archive(
                            "repo",
                            "1.2.3",
                            build_mod.frontend_building_prod,
                        )
                    )
                finally:
                    for patcher in reversed(list(patchers.values())):
                        patcher.stop()

    def test_get_building_archive_success_and_dev_gitignore_step(self):
        with patch("src.build.copy_file_to_repo2", return_value=True) as copy_mock:
            with patch("src.build._update_vite_build_version", return_value=True):
                with patch("src.build._create_frontend_build", return_value=True):
                    self.assertTrue(
                        build_mod.get_building_archive_prod("repo", "1.2.3")
                    )

        self.assertEqual(copy_mock.call_count, 2)

        with patch("src.build.copy_file_to_repo2", return_value=False):
            self.assertFalse(build_mod.get_building_archive_dev("repo", "1.2.3"))

        with patch("src.build.copy_file_to_repo2", return_value=True):
            with patch("src.build._get_building_archive", return_value=True) as archive_mock:
                self.assertTrue(build_mod.get_building_archive_dev("repo", "1.2.3"))

        archive_mock.assert_called_once_with(
            repo2_path="repo",
            build_version="1.2.3",
            frontend_building=build_mod.frontend_building_dev,
        )


if __name__ == "__main__":
    unittest.main()
