#!/bin/bash
set -euo pipefail

# --- EXIT CODES ---
# 0 = New release found, build completed successfully (or cleanup-only run finished)
# 2 = No new release, no action taken
# 1 = Error occurred

# --- ARGUMENT PARSING ---
LIBSIGNAL_JAVA_HOME=""
SIGNALCLI_JAVA_HOME=""
FORCE=false
CLEANUP_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --libsignal-java-home)
            LIBSIGNAL_JAVA_HOME="$2"
            shift 2
            ;;
        --signalcli-java-home)
            SIGNALCLI_JAVA_HOME="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--libsignal-java-home <path>] [--signalcli-java-home <path>] [--force] [--cleanup-only]"
            exit 1
            ;;
    esac
done

# Set base directory to the folder where this script is stored (no hardcoded paths)
BASE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$BASE_DIR"
LIBSIGNAL_DIR="$BASE_DIR/libsignal_latest_release"
SIGNALCLI_DIR="$BASE_DIR/signal-cli"

if [ "$FORCE" = true ] && [ "$CLEANUP_ONLY" = true ]; then
    echo "❌ Error: --force and --cleanup-only cannot be combined."
    exit 1
fi

# ------------------------------------------------------------------------------
# Cleanup: reclaim disk space after a build (also runnable on its own via
# --cleanup-only). Every step is optional and must not fail the script.
# ------------------------------------------------------------------------------
cleanup() {
    echo -e "\n==> Cleaning up build artifacts..."

    # Rust build artifacts for libsignal (largest, not needed after jar is produced)
    if [ -d "$LIBSIGNAL_DIR/target" ]; then
        echo "  Removing libsignal Rust target dir..."
        rm -rf "$LIBSIGNAL_DIR/target"
    fi

    # signal-cli Gradle intermediates — keep only the installed distribution
    if [ -d "$SIGNALCLI_DIR/build" ]; then
        echo "  Removing signal-cli build intermediates (keeping build/install/)..."
        find "$SIGNALCLI_DIR/build" -mindepth 1 -maxdepth 1 ! -name "install" -exec rm -rf {} +
    fi

    # Remove Gradle wrapper distributions older than the two most recently used
    if [ -d "$HOME/.gradle/wrapper/dists" ]; then
        echo "  Pruning old Gradle wrapper distributions..."
        # Keep the 2 most recently modified, delete the rest
        ls -dt "$HOME/.gradle/wrapper/dists"/gradle-* 2>/dev/null | tail -n +3 | xargs -r rm -rf || true
    fi

    # Remove Gradle version caches older than the two most recently used
    if [ -d "$HOME/.gradle/caches" ]; then
        echo "  Pruning old Gradle version caches..."
        # Only target numeric version dirs (e.g. 8.13, 9.4.0), keep 2 most recent
        find "$HOME/.gradle/caches" -mindepth 1 -maxdepth 1 -type d \
            | grep -E '/[0-9]+\.[0-9]' \
            | xargs -r ls -dt 2>/dev/null \
            | tail -n +3 | xargs -r rm -rf || true
    fi

    # Old Rust nightly toolchains (keep stable + most recent nightly if any)
    if command -v rustup &> /dev/null; then
        echo "  Pruning old Rust nightly toolchains..."
        rustup toolchain list | grep nightly | sort | head -n -1 | awk '{print $1}' \
            | xargs -r rustup toolchain uninstall || true
    fi

    echo "  Cleanup done."
}

# ------------------------------------------------------------------------------
# Cleanup-only mode: skip every build step
# ------------------------------------------------------------------------------
if [ "$CLEANUP_ONLY" = true ]; then
    echo "==> --cleanup-only specified, skipping dependency checks and builds."
    # rustup lives in ~/.cargo/bin, which a non-login shell may not have on PATH
    if [ -f "$HOME/.cargo/env" ]; then
        source "$HOME/.cargo/env"
    fi
    cleanup
    exit 0
fi

# ------------------------------------------------------------------------------
# Step 1: Check and install apt dependencies ONLY if missing
# ------------------------------------------------------------------------------
REQUIRED_APT_PACKAGES=(
    default-jdk
    cmake
    libclang-dev
    protobuf-compiler
    jq
)
MISSING_PACKAGES=()

echo "==> Checking for required system packages..."
for pkg in "${REQUIRED_APT_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" &> /dev/null; then
        MISSING_PACKAGES+=("$pkg")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo "Installing missing packages: ${MISSING_PACKAGES[*]}"
    sudo apt update
    sudo apt install -y "${MISSING_PACKAGES[@]}"
else
    echo "All required system packages are already installed."
fi

# ------------------------------------------------------------------------------
# Step 2: Check and install Rust / Rustup ONLY if missing
# ------------------------------------------------------------------------------
echo -e "\n==> Checking for Rust installation..."
if ! command -v rustup &> /dev/null; then
    echo "Rustup not found, installing unattended..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
else
    echo "Rustup is already installed."
fi
# Ensure rust/cargo are available in the current script PATH
source "$HOME/.cargo/env"

# ------------------------------------------------------------------------------
# Step 3: Check for new signal-cli release (skipped with --force)
# ------------------------------------------------------------------------------
if [ "$FORCE" = true ]; then
    echo -e "\n==> --force specified, skipping signal-cli version check and proceeding with build..."
else
    echo -e "\n==> Checking for new signal-cli releases..."

    # TEMPORARILY DISABLE 'set -e' so a non-zero exit DOESN'T kill the script
    set +e
    ./check_release.sh AsamK/signal-cli --target-dir ./signal-cli
    CHECK_EXIT=$?
    set -e   # re-enable immediately

    # Handle check result
    if [ $CHECK_EXIT -eq 0 ]; then
        echo -e "\n✅ No new signal-cli release available. Exiting without build."
        exit 2
    elif [ $CHECK_EXIT -eq 2 ]; then
        echo -e "\n🚀 New signal-cli release detected! Proceeding with build..."
    else
        echo -e "\n❌ Error checking for signal-cli updates (exit code $CHECK_EXIT)."
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# Step 4: Determine required libsignal version from signal-cli source
# ------------------------------------------------------------------------------
LIBSIGNAL_VERSION_FILE="$SIGNALCLI_DIR/libsignal-version"
if [ ! -f "$LIBSIGNAL_VERSION_FILE" ]; then
    echo "❌ Error: $LIBSIGNAL_VERSION_FILE not found. Is signal-cli checked out?"
    exit 1
fi
LIBSIGNAL_TAG="v$(cat "$LIBSIGNAL_VERSION_FILE" | tr -d '[:space:]')"
echo -e "\n==> signal-cli requires libsignal $LIBSIGNAL_TAG"

# ------------------------------------------------------------------------------
# Step 5: Fetch the required libsignal version
# ------------------------------------------------------------------------------
echo -e "\n==> Fetching libsignal $LIBSIGNAL_TAG..."

set +e
./check_release.sh signalapp/libsignal --tag "$LIBSIGNAL_TAG" --target-dir ./libsignal_latest_release
LIBSIGNAL_CHECK_EXIT=$?
set -e

if [ $LIBSIGNAL_CHECK_EXIT -eq 1 ]; then
    echo -e "\n❌ Error fetching libsignal $LIBSIGNAL_TAG."
    exit 1
fi
# exit 0 (already at correct version) or exit 2 (just updated) — both are fine

# ------------------------------------------------------------------------------
# Step 6: Build libsignal
# ------------------------------------------------------------------------------

# libsignal uses gradle 8.13 which does not work with Java 25
OLD_JAVA_HOME="${JAVA_HOME:-}"
if [ -n "$LIBSIGNAL_JAVA_HOME" ]; then
    echo "==> Using --libsignal-java-home: $LIBSIGNAL_JAVA_HOME"
    export JAVA_HOME="$LIBSIGNAL_JAVA_HOME"
fi
cd "$LIBSIGNAL_DIR/java"
echo -e "\n==> Building libsignal JNI bindings..."
./build_jni.sh desktop
echo -e "\n==> Building libsignal client library..."
./gradlew --no-daemon :client:assemble -PskipAndroid=true
cd "$BASE_DIR"

# use old java home (or signalcli-specific override). signal-cli uses gradle 9.3 which does not work with older java releases
if [ -n "$SIGNALCLI_JAVA_HOME" ]; then
    echo "==> Using --signalcli-java-home: $SIGNALCLI_JAVA_HOME"
    export JAVA_HOME="$SIGNALCLI_JAVA_HOME"
else
    export JAVA_HOME="$OLD_JAVA_HOME"
fi

# Determine the exact jar for the checked-out version.
# The libsignal-version file contains e.g. "0.90.0"; the jar is named "libsignal-client-0.90.0.jar"
LIBSIGNAL_TAG_STRIPPED="${LIBSIGNAL_TAG#v}"
LIBSIGNAL_JAR="$LIBSIGNAL_DIR/java/client/build/libs/libsignal-client-${LIBSIGNAL_TAG_STRIPPED}.jar"
if [ ! -f "$LIBSIGNAL_JAR" ]; then
    echo "❌ Error: Expected jar not found: $LIBSIGNAL_JAR"
    echo "   libsignal version: $LIBSIGNAL_TAG"
    echo "   Available jars:"
    find "$LIBSIGNAL_DIR/java/client/build/libs" -name "libsignal-client-*.jar" -not -name "*-sources.jar" | sort | sed 's/^/     /'
    exit 1
fi
echo "Found libsignal build: $LIBSIGNAL_JAR"

# ------------------------------------------------------------------------------
# Step 7: Build signal-cli against the new libsignal
# ------------------------------------------------------------------------------
cd "$SIGNALCLI_DIR"
echo -e "\n==> Building signal-cli against libsignal $LIBSIGNAL_TAG..."
./gradlew -Plibsignal_client_path="$LIBSIGNAL_JAR" build
./gradlew -Plibsignal_client_path="$LIBSIGNAL_JAR" installDist

cd "$BASE_DIR"
echo -e "\n🎉 ALL BUILDS COMPLETED SUCCESSFULLY!"
echo "Installed signal-cli location: $SIGNALCLI_DIR/build/install/signal-cli/bin/signal-cli"

# ------------------------------------------------------------------------------
# Step 8: Post-build cleanup to reclaim disk space
# ------------------------------------------------------------------------------
cleanup
exit 0
