#!/bin/bash
set -euo pipefail

# --- EXIT CODES ---
# 0 = New release found, build completed successfully
# 2 = No new release, no action taken
# 1 = Error occurred

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
# Step 3: Check for new libsignal release
# ------------------------------------------------------------------------------
echo -e "\n==> Checking for new libsignal releases..."
# TEMPORARILY DISABLE 'set -e' so a non‑zero exit DOESN'T kill the script
set +e
./check_release.sh signalapp/libsignal
CHECK_EXIT=$?
set -e   # re‑enable immediately

# Handle check result
if [ $CHECK_EXIT -eq 0 ]; then
    echo -e "\n✅ No new libsignal release available. Exiting without build."
    exit 2
elif [ $CHECK_EXIT -eq 2 ]; then
    echo -e "\n🚀 New libsignal release detected! Proceeding with build..."
elif [ $CHECK_EXIT -ne 0 ] && [ $CHECK_EXIT -ne 2 ]; then
    echo -e "\n❌ Error checking for libsignal updates (exit code $CHECK_EXIT)."
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 4: Run build process ONLY if new release was detected
# ------------------------------------------------------------------------------

# Build libsignal first
# libsignal uses gradle 8.13 which does not work with Java 25
OLD_JAVA_HOME=$JAVA_HOME
unset JAVA_HOME
cd $LIBSIGNAL_DIR/java
echo -e "\n==> Building libsignal JNI bindings..."
./build_jni.sh desktop
echo -e "\n==> Building libsignal client library..."
./gradlew --no-daemon :client:assemble -PskipAndroid=true
cd "$BASE_DIR"

# use old java home. signal-cli uses gradle 9.3 which does not work with older java releases
JAVA_HOME=$OLD_JAVA_HOME
export JAVA_HOME

# Dynamically find the built libsignal jar (NO MORE HARDCODED VERSION NUMBERS!)
LIBSIGNAL_JAR=$(find "$LIBSIGNAL_DIR/java/client/build/libs" -name "libsignal-client-*.jar" -type f |grep -v "sources.jar" | head -n 1)
if [ ! -f "$LIBSIGNAL_JAR" ]; then
    echo "❌ Error: Could not find built libsignal jar file"
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


