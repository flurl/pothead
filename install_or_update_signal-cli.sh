#!/bin/bash
set -euo pipefail

# --- EXIT CODES ---
# 0 = New release found, build completed successfully
# 2 = No new release, no action taken
# 1 = Error occurred

# --- ARGUMENT PARSING ---
LIBSIGNAL_JAVA_HOME=""
SIGNALCLI_JAVA_HOME=""
FORCE=false
LIBSIGNAL_TAG=""

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
        --libsignal-tag)
            LIBSIGNAL_TAG="$2"
            shift 2
            ;;
        --libsignal-tag-file)
            if [ ! -f "$2" ]; then
                echo "❌ Error: --libsignal-tag-file '$2' not found."
                exit 1
            fi
            LIBSIGNAL_TAG=$(cat "$2" | tr -d '[:space:]')
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--libsignal-java-home <path>] [--signalcli-java-home <path>] [--force] [--libsignal-tag <tag>] [--libsignal-tag-file <file>]"
            exit 1
            ;;
    esac
done

# Set base directory to the folder where this script is stored (no hardcoded paths)
BASE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$BASE_DIR"
LIBSIGNAL_DIR="$BASE_DIR/libsignal_latest_release"

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
# Step 3: Check for new libsignal release (skipped with --force)
# ------------------------------------------------------------------------------
if [ "$FORCE" = true ]; then
    echo -e "\n==> --force specified, skipping version check and proceeding with build..."
else
    if [ -n "$LIBSIGNAL_TAG" ]; then
        echo -e "\n==> Checking for pinned libsignal release: $LIBSIGNAL_TAG..."
    else
        echo -e "\n==> Checking for new libsignal releases..."
    fi

    # TEMPORARILY DISABLE 'set -e' so a non-zero exit DOESN'T kill the script
    set +e
    ./check_release.sh signalapp/libsignal ${LIBSIGNAL_TAG:+"$LIBSIGNAL_TAG"}
    CHECK_EXIT=$?
    set -e   # re-enable immediately

    # Handle check result
    if [ $CHECK_EXIT -eq 0 ]; then
        echo -e "\n✅ No new libsignal release available. Exiting without build."
        exit 2
    elif [ $CHECK_EXIT -eq 2 ]; then
        echo -e "\n🚀 New libsignal release detected! Proceeding with build..."
    else
        echo -e "\n❌ Error checking for libsignal updates (exit code $CHECK_EXIT)."
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# Step 4: Run build process ONLY if new release was detected
# ------------------------------------------------------------------------------

# Build libsignal first
# libsignal uses gradle 8.13 which does not work with Java 25
OLD_JAVA_HOME="${JAVA_HOME:-}"
if [ -n "$LIBSIGNAL_JAVA_HOME" ]; then
    echo "==> Using --libsignal-java-home: $LIBSIGNAL_JAVA_HOME"
    export JAVA_HOME="$LIBSIGNAL_JAVA_HOME"
fi
cd $LIBSIGNAL_DIR/java
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
# Prefer the explicitly requested tag; fall back to .current_version written by check_release.sh.
if [ -n "$LIBSIGNAL_TAG" ]; then
    BUILT_VERSION="$LIBSIGNAL_TAG"
elif [ -f "$BASE_DIR/.current_version" ]; then
    BUILT_VERSION=$(cat "$BASE_DIR/.current_version" | tr -d '[:space:]')
else
    echo "❌ Error: Cannot determine built libsignal version: no --libsignal-tag given and .current_version not found."
    exit 1
fi
# The tag is e.g. "v0.90.0"; the jar is named "libsignal-client-0.90.0.jar" (no leading 'v')
BUILT_VERSION_STRIPPED="${BUILT_VERSION#v}"
LIBSIGNAL_JAR="$LIBSIGNAL_DIR/java/client/build/libs/libsignal-client-${BUILT_VERSION_STRIPPED}.jar"
if [ ! -f "$LIBSIGNAL_JAR" ]; then
    echo "❌ Error: Expected jar not found: $LIBSIGNAL_JAR"
    echo "   Built version from .current_version: $BUILT_VERSION"
    echo "   Available jars:"
    find "$LIBSIGNAL_DIR/java/client/build/libs" -name "libsignal-client-*.jar" -not -name "*-sources.jar" | sort | sed 's/^/     /'
    exit 1
fi
echo "Found libsignal build: $LIBSIGNAL_JAR"

# Build signal-cli
if [ -d signal-cli ]; then
    echo -e "\n==> Updating signal-cli..."
    cd signal-cli
    git pull
else
    echo -e "\n==> Cloning latest signal-cli..."
    git clone --depth 1 https://github.com/AsamK/signal-cli.git
    cd signal-cli
fi
echo -e "\n==> Building signal-cli against new libsignal..."
./gradlew -Plibsignal_client_path="$LIBSIGNAL_JAR" build
./gradlew -Plibsignal_client_path="$LIBSIGNAL_JAR" installDist

cd "$BASE_DIR"
echo -e "\n🎉 ALL BUILDS COMPLETED SUCCESSFULLY!"
echo "Installed signal-cli location: $BASE_DIR/signal-cli/build/install/signal-cli/bin/signal-cli"
exit 0
