#!/bin/bash

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <owner/repo-name> [tag]"
    echo "Example: $0 signalapp/libsignal"
    echo "Example: $0 signalapp/libsignal v0.36.0"
    exit 1
fi
REPO="$1"
PINNED_TAG="${2:-}"
LOCAL_VERSION_FILE=".current_version"
TARGET_DIR="./libsignal_latest_release"

# --- EXIT CODE DEFINITIONS ---
# 0: No update needed (already latest/pinned version)
# 1: Error (API failure, clone failure, missing dependencies)
# 2: New release successfully cloned

# --- CHECK FOR DEPENDENCIES ---
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is not installed. Please install it (e.g., sudo apt install jq)."
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "Error: 'curl' is not installed."
    exit 1
fi

# --- DETERMINE TARGET TAG ---
if [ -n "$PINNED_TAG" ]; then
    echo "Using pinned tag: $PINNED_TAG"
    LATEST_TAG="$PINNED_TAG"
else
    # --- GET LATEST RELEASE TAG FROM GITHUB ---
    echo "Checking GitHub for latest release of $REPO..."
    RELEASE_DATA=$(curl -s "https://api.github.com/repos/$REPO/releases/latest")
    LATEST_TAG=$(echo "$RELEASE_DATA" | jq -r '.tag_name')

    # Check if the API returned a valid tag
    if [ "$LATEST_TAG" == "null" ] || [ -z "$LATEST_TAG" ]; then
        echo "Error: Could not fetch latest release. Check repo name or API limits."
        exit 1
    fi
fi

# --- COMPARE WITH LOCAL VERSION ---
if [ -f "$LOCAL_VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$LOCAL_VERSION_FILE")
else
    CURRENT_VERSION=""
fi

if [ "$LATEST_TAG" == "$CURRENT_VERSION" ]; then
    echo "Up to date (Version: $LATEST_TAG). No action needed."
    exit 0
fi

# --- ACTION: CLONE NEW RELEASE ---
echo "New version found: $LATEST_TAG (Local: ${CURRENT_VERSION:-None})"
echo "Cloning release..."

if [ -d "$TARGET_DIR/.git" ]; then
    # Repository exists - refresh with git pull equivalent
    cd "$TARGET_DIR" || exit 1

    # Fetch the specific tag (shallow if possible)
    if ! git fetch --depth=1 origin tag "$LATEST_TAG" 2>/dev/null; then
        git fetch origin --tags
    fi

    # Checkout the new tag (detached HEAD)
    git checkout -f "$LATEST_TAG"

    # Save the new version
    echo "$LATEST_TAG" > "$LOCAL_VERSION_FILE"
    if [ $? -eq 0 ]; then
        echo "Successfully updated to $LATEST_TAG in $TARGET_DIR"
        exit 2
    else
        echo "Error: Failed to write version file."
        exit 1
    fi
else
    # Fresh clone (original behavior)
    rm -rf "$TARGET_DIR"
    git clone --branch "$LATEST_TAG" --depth 1 "https://github.com/$REPO.git" "$TARGET_DIR"

    if [ $? -eq 0 ]; then
        echo "$LATEST_TAG" > "$LOCAL_VERSION_FILE"
        if [ $? -eq 0 ]; then
            echo "Successfully updated to $LATEST_TAG in $TARGET_DIR"
            exit 2
        else
            echo "Error: Failed to write version file."
            exit 1
        fi
    else
        echo "Clone failed."
        exit 1
    fi
fi
