#!/bin/bash

: "${BACKEND_REPO_ROOT_BASH:?BACKEND_REPO_ROOT_BASH is required}"
: "${RELEASE_ROOT_BASH:?RELEASE_ROOT_BASH is required}"
: "${BACKEND_APP_ROOT_DIR:=example_backend_app}"
BACKEND_REPO_ROOT="$BACKEND_REPO_ROOT_BASH"
BUILD_DIR_FULL="$BACKEND_REPO_ROOT/$BACKEND_APP_ROOT_DIR"
ARCHIVE_ROOT="$RELEASE_ROOT_BASH"
ARCHIVE_DIR="$ARCHIVE_ROOT/$2"

if [ $# -eq 0 ]; then
    echo "No archive name provided. Usage: $0 <archive_name>"
    exit 1
fi

ARCHIVE_NAME="$ARCHIVE_DIR/backend_r_$2-bf_$1-env_$3.tar.gz"

if [ ! -d "$ARCHIVE_DIR" ]; then
    mkdir -p "$ARCHIVE_DIR"
    echo "Created directory: $ARCHIVE_DIR"
fi

if [ -d "$BUILD_DIR_FULL" ]; then
    echo "Directory '$BUILD_DIR_FULL' exists. Proceeding with archiving..."
    
    # Только содержимое директории backend application root.
    tar -czvf "$ARCHIVE_NAME" \
    --exclude="**/tests" \
    --exclude="tests" --exclude="**/.env" \
    --exclude="**/.env.example" \
    --exclude="__pycache__" \
    --exclude="*/__pycache__" \
    --exclude="*/__pycache__/*" \
    --exclude="*.pyc" \
    --exclude="*.pyo" \
    --exclude="unit_test_runner.py" \
    -C "$BACKEND_REPO_ROOT" "$BACKEND_APP_ROOT_DIR"
    echo "Archive created: $ARCHIVE_NAME"
else
    echo "Directory '$BUILD_DIR_FULL' does not exist. No archive created."
fi
