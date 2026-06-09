# Maintenance stub

This directory contains the default maintenance page archive:

```text
tools-ci/maintenance_stub/maintenance_stub.tar.gz
```

The archive is universal and is not tied to a release version. During full DEV
deploy `tools-ci/tools/windows_pipeline.py` uploads it to the app VM and unpacks
it into `FRONTEND_RELEASE_PATH` before DB scripts start. The real frontend is
unpacked only after DB scripts, backend unpack, management commands and service
start complete successfully.

The current archive contains one top-level `build/` directory:

```text
build/index.html
build/assets/...
```

The runner unpacks it with `--strip-components=1`, so the deployed
`FRONTEND_RELEASE_PATH` receives `index.html` and `assets/` directly.

After unpacking the stub, full deploy requests `https://DEV_DOMAIN/` and checks
that the returned HTML contains the configured
`maintenance_stub_verify_marker`. The default archive contains the marker:

```text
Плановые технические работы
```

If this archive is replaced with another universal stub, update
`maintenance_stub_verify_marker` in `windows_pipeline.local.json`.

The deploy runner validates the archive before stopping app services when
`maintenance_stub_enabled` is `true`.
