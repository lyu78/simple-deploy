"""Tests for WindowsPipelineDryRunTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineDryRunTests(WindowsPipelineTestCase):

    def test_prepare_build_env_keeps_configured_backend_app_root(self):
        """Не перетирает явно заданный backend app root дефолтным значением."""
        build_env = prepare_build_env(
            {
                "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
                "BACKEND_APP_ROOT_DIR": BACKEND_APP_ROOT,
                "DEV_DOMAIN": DEV_DOMAIN,
            }
        )

        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], BACKEND_APP_ROOT)
        self.assertEqual(build_env["BACKEND_DJANGO_SETTINGS_MODULE"], f"{BACKEND_APP_ROOT}.settings.base")

    def test_dry_run_fails_when_backend_app_root_is_missing(self):
        """Dry-run сообщает ошибку, если backend app root не задан и не найден."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            source_repo.mkdir()
            (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
            reporter = Reporter()

            with patch.dict("os.environ", {}, clear=True):
                check_backend_build_inputs(
                    reporter,
                    {
                        "BACKEND_SOURCE_REPO_PATH": str(source_repo),
                        "DEV_DOMAIN": DEV_DOMAIN,
                    },
                )

        self.assertTrue(any("BACKEND_APP_ROOT_DIR" in issue for issue in reporter.issues))

    def test_dry_run_checks_backend_settings_import_when_venv_exists(self):
        """Dry-run проверяет импорт Django settings через найденный backend venv."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            app_root = source_repo / BACKEND_APP_ROOT
            venv_scripts = source_repo / ".venv" / "Scripts"
            app_root.mkdir(parents=True)
            venv_scripts.mkdir(parents=True)
            (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
            python_path = venv_scripts / "python.exe"
            python_path.write_text("", encoding="utf-8")
            reporter = Reporter()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "simple_deploy.processes.dry_run_checks.run_command",
                    return_value=CommandResult(0, f"{BACKEND_APP_ROOT}.settings.base\n", ""),
                ) as run_mock:
                    check_backend_build_inputs(
                        reporter,
                        {
                            "BACKEND_SOURCE_REPO_PATH": str(source_repo),
                            "BACKEND_APP_ROOT_DIR": BACKEND_APP_ROOT,
                            "BACKEND_DJANGO_SETTINGS_MODULE": f"{BACKEND_APP_ROOT}.settings.base",
                            "DEV_DOMAIN": DEV_DOMAIN,
                        },
                    )

        self.assertEqual(reporter.issues, [])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], str(python_path))
        self.assertEqual(command[1:3], ["-Xutf8", "-c"])
        self.assertIn(f"{BACKEND_APP_ROOT}.settings.base", command[3])

    def test_dry_run_fails_on_non_idempotent_data_insert_sql(self):
        """Dry-run отклоняет INSERT без ON CONFLICT в обычных data insert каталогах."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_STANDARD_INSERT_DIR
            insert_dir.mkdir(parents=True)
            bad_sql = insert_dir / "insert_bad.sql"
            bad_sql.write_text("INSERT INTO table_name (id) VALUES (1);\n", encoding="utf-8")
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert_bad.sql" in issue for issue in reporter.issues))

    def test_dry_run_passes_on_idempotent_data_insert_sql(self):
        """Dry-run принимает INSERT с конфликтной стратегией обновления."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_STANDARD_INSERT_DIR
            insert_dir.mkdir(parents=True)
            good_sql = insert_dir / "insert_good.sql"
            good_sql.write_text(
                "INSERT INTO table_name (id) VALUES (1) "
                "ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_fails_on_catalog_business_key_duplicate(self):
        """Dry-run ловит дубликаты бизнес-ключей в catalog data SQL."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_CATALOG_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_contractsubject.sql"
            sql.write_text(
                "\n".join(
                    [
                        f"INSERT INTO public.{CATALOG_BUSINESS_KEY_TABLE} (id, title)",
                        "VALUES (1, 'same title')",
                        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                        f"INSERT INTO public.{CATALOG_BUSINESS_KEY_TABLE} (id, title)",
                        "VALUES (2, 'same title')",
                        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                    ]
                ),
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("catalog business key duplicate" in issue for issue in reporter.issues))
        self.assertTrue(any("same title" in issue for issue in reporter.issues))

    def test_dry_run_allows_full_state_truncate_insert_sql(self):
        """Разрешает full-state insert, если SQL сам очищает управляемую таблицу."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_full_state.sql"
            sql.write_text(
                "TRUNCATE TABLE public.some_owned_table RESTART IDENTITY;\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_allows_full_state_drop_create_insert_sql(self):
        """Разрешает full-state insert, если SQL пересоздает управляемую таблицу."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_recreated_table.sql"
            sql.write_text(
                "DROP TABLE IF EXISTS public.some_owned_table;\n"
                "CREATE TABLE public.some_owned_table (id bigint PRIMARY KEY);\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_allows_drop_insert_sql(self):
        """Разрешает insert после DROP зависимого объекта в full-state каталоге."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_drop_reset.sql"
            sql.write_text(
                "DROP MATERIALIZED VIEW IF EXISTS public.some_owned_view;\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_fails_on_insert_new_objects_truncate(self):
        """Запрещает TRUNCATE в insert_new_objects, где допустим только insert-if-missing."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"TRUNCATE TABLE public.{INSERT_NEW_OBJECTS_TABLE};\n"
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT DO NOTHING;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert-if-missing idempotency" in issue for issue in reporter.issues))

    def test_dry_run_fails_on_insert_new_objects_without_do_nothing(self):
        """Запрещает insert_new_objects с UPDATE-веткой вместо DO NOTHING."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert-if-missing idempotency" in issue for issue in reporter.issues))

    def test_dry_run_passes_on_insert_new_objects_do_nothing(self):
        """Разрешает insert_new_objects, если конфликтная стратегия только DO NOTHING."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT DO NOTHING;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])
