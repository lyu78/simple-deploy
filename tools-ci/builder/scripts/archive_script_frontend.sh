#!/bin/bash

BUILD_DIR="build"
: "${RELEASE_ROOT_BASH:?RELEASE_ROOT_BASH is required}"
ARCHIVE_ROOT="$RELEASE_ROOT_BASH"
ARCHIVE_DIR="$ARCHIVE_ROOT/$2"

if [ $# -eq 0 ]; then
    echo "No archive name provided. Usage: $0 <archive_name>"
    exit 1
fi

ARCHIVE_NAME="$ARCHIVE_DIR/frontend_r_$2-bf_$1-env_$3.tar.gz"

if [ ! -d "$ARCHIVE_DIR" ]; then
    mkdir -p "$ARCHIVE_DIR"
    echo "Created directory: $ARCHIVE_DIR"
fi

if [ -d "$BUILD_DIR" ]; then
    echo "Directory '$BUILD_DIR' exists. Proceeding with archiving..."
    
    tar -czvf "$ARCHIVE_NAME" "$BUILD_DIR"  
    echo "Archive created: $ARCHIVE_NAME"
else
    echo "Directory '$BUILD_DIR' does not exist. No archive created."
fi
