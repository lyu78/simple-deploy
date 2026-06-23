import os
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[2]
BUILDER_ROOT = ROOT / "tools-ci" / "builder"

sys.path.insert(0, str(BUILDER_ROOT))

os.environ.setdefault("FRONTEND_DEV_SERVER_NAME", "dev")
os.environ.setdefault("FRONTEND_TEST_SERVER_NAME", "test")
os.environ.setdefault("FRONTEND_PROD_SERVER_NAME", "prod")

from src.build_frontend import build_frontend  # noqa: E402


class BuildFrontendTests(unittest.TestCase):
    def _env(self, key: str) -> str:
        values = {
            "FRONTEND_SOURCE_REPO_PATH": "source-repo",
            "FRONTEND_TARGET_REPO_PATH": "target-repo",
        }
        return values[key]

    def _success_patches(self):
        return [
            patch("src.build_frontend.get_required_env", side_effect=self._env),
            patch("src.build_frontend.check_repo", return_value=True),
            patch("src.build_frontend.git_checkout_dev", return_value=True),
            patch("src.build_frontend.git_npm_i", return_value=True),
            patch("src.build_frontend.git_pull", return_value=True),
            patch("src.build_frontend.git_checkout_new_branch", return_value=True),
            patch("src.build_frontend.clear_directory_contents", return_value=True),
            patch("src.build_frontend.copy_directory_contents", return_value=True),
            patch("src.build_frontend.get_building_archive_dev", return_value=True),
            patch("src.build_frontend.git_add_commit_push", return_value=True),
            patch("src.build_frontend.get_building_archive_preprod", return_value=True),
            patch("src.build_frontend.get_building_archive_prod", return_value=True),
        ]

    def test_build_frontend_runs_happy_path_in_order(self):
        patchers = self._success_patches()
        mocks = [patcher.start() for patcher in patchers]
        self.addCleanup(lambda: [patcher.stop() for patcher in reversed(patchers)])

        build_frontend("1.2.3", "release/1.2.3")

        check_repo = mocks[1]
        git_checkout_dev = mocks[2]
        git_npm_i = mocks[3]
        git_pull = mocks[4]
        git_checkout_new_branch = mocks[5]
        clear_directory_contents = mocks[6]
        copy_directory_contents = mocks[7]
        get_building_archive_dev = mocks[8]
        git_add_commit_push = mocks[9]
        get_building_archive_preprod = mocks[10]
        get_building_archive_prod = mocks[11]

        self.assertEqual(
            check_repo.call_args_list,
            [
                call("source-repo"),
                call("target-repo"),
            ],
        )
        self.assertEqual(git_checkout_dev.call_count, 2)
        git_npm_i.assert_any_call("source-repo")
        git_npm_i.assert_any_call("target-repo")
        git_pull.assert_any_call("source-repo")
        git_pull.assert_any_call("target-repo")
        git_checkout_new_branch.assert_called_once_with(
            "target-repo", "release/1.2.3"
        )
        clear_directory_contents.assert_called_once_with("target-repo")
        copy_directory_contents.assert_called_once_with(
            "source-repo", "target-repo"
        )
        get_building_archive_dev.assert_called_once_with(
            repo2_path="target-repo", build_version="1.2.3"
        )
        git_add_commit_push.assert_called_once()
        get_building_archive_preprod.assert_called_once_with(
            repo2_path="target-repo", build_version="1.2.3"
        )
        get_building_archive_prod.assert_called_once_with(
            repo2_path="target-repo", build_version="1.2.3"
        )

    def test_build_frontend_exits_when_source_repo_invalid(self):
        with patch("src.build_frontend.get_required_env", side_effect=self._env):
            with patch("src.build_frontend.check_repo", return_value=False):
                with self.assertRaises(SystemExit) as cm:
                    build_frontend("1.2.3", "release/1.2.3")

        self.assertEqual(cm.exception.code, 1)

    def test_build_frontend_exits_on_failed_dev_archive(self):
        patchers = self._success_patches()
        mocks = [patcher.start() for patcher in patchers]
        self.addCleanup(lambda: [patcher.stop() for patcher in reversed(patchers)])
        mocks[8].return_value = False

        with self.assertRaises(SystemExit) as cm:
            build_frontend("1.2.3", "release/1.2.3")

        self.assertEqual(cm.exception.code, 1)

    def test_build_frontend_exits_on_each_failed_step(self):
        scenarios = [
            ("target repo invalid", lambda mocks: setattr(mocks[1], "side_effect", [True, False])),
            ("source checkout", lambda mocks: setattr(mocks[2], "return_value", False)),
            ("source npm install", lambda mocks: setattr(mocks[3], "return_value", False)),
            ("source pull", lambda mocks: setattr(mocks[4], "return_value", False)),
            ("target checkout", lambda mocks: setattr(mocks[2], "side_effect", [True, False])),
            ("target pull", lambda mocks: setattr(mocks[4], "side_effect", [True, False])),
            ("target branch", lambda mocks: setattr(mocks[5], "return_value", False)),
            ("clear target", lambda mocks: setattr(mocks[6], "return_value", False)),
            ("copy target", lambda mocks: setattr(mocks[7], "return_value", False)),
            ("target npm install", lambda mocks: setattr(mocks[3], "side_effect", [True, False])),
            ("commit push", lambda mocks: setattr(mocks[9], "return_value", False)),
            ("preprod archive", lambda mocks: setattr(mocks[10], "return_value", False)),
            ("prod archive", lambda mocks: setattr(mocks[11], "return_value", False)),
        ]

        for name, setup_failure in scenarios:
            with self.subTest(name=name):
                patchers = self._success_patches()
                mocks = [patcher.start() for patcher in patchers]
                try:
                    setup_failure(mocks)

                    with self.assertRaises(SystemExit) as cm:
                        build_frontend("1.2.3", "release/1.2.3")

                    self.assertEqual(cm.exception.code, 1)
                finally:
                    for patcher in reversed(patchers):
                        patcher.stop()
