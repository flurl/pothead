#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Locate the script and its parent (the project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Who is running the script?  Prefer the original user when using sudo.
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

# ----------------------------------------------------------------------
# Parse optional command-line arguments
JAVA_HOME_VAL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --java-home=*)
      JAVA_HOME_VAL="${1#*=}"
      shift
      ;;
    --java-home)
      JAVA_HOME_VAL="${2:-}"
      if [[ -z "$JAVA_HOME_VAL" ]]; then
        echo "ERROR: --java-home requires a path argument"
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--java-home /path/to/java]"
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1"
      echo "Usage: $0 [--java-home /path/to/java]"
      exit 1
      ;;
  esac
done

# ----------------------------------------------------------------------
# Paths inside the project root (parent of the script directory)
VENV_DIR="$PROJECT_DIR/venv"                # change to however your venv dir is named
PYTHON_BIN="$VENV_DIR/bin/python"
SCRIPT_PY="$PROJECT_DIR/pothead.py"

# Input / output files
TEMPLATE="$SCRIPT_DIR/pothead.service.template"
OUTPUT="$SCRIPT_DIR/pothead.service"

[[ -f "$TEMPLATE" ]] || { echo "ERROR: template not found: $TEMPLATE"; exit 1; }
[[ -x "$PYTHON_BIN" ]] || echo "WARNING: $PYTHON_BIN not executable (did you create the venv?)"
[[ -f "$SCRIPT_PY" ]] || echo "WARNING: $SCRIPT_PY not found"

# ----------------------------------------------------------------------
# Build ExecStart – optionally prefix with JAVA_HOME=
if [[ -n "$JAVA_HOME_VAL" ]]; then
  EXEC_START="$PYTHON_BIN $SCRIPT_PY\nEnvironment=\"JAVA_HOME=$JAVA_HOME_VAL\""
  [[ -d "$JAVA_HOME_VAL" ]] || echo "WARNING: JAVA_HOME path '$JAVA_HOME_VAL' does not exist"
else
  EXEC_START="$PYTHON_BIN $SCRIPT_PY"
fi


# Do all placeholder replacements.  Use '@' as delimiter because paths may contain '/'.
sed \
  -e "s@<USER>@$RUN_USER@g" \
  -e "s@<GROUP>@$RUN_GROUP@g" \
  -e "s@>GROUP>@$RUN_GROUP@g"   `# typo fallback` \
  -e "s@<WORKING_DIR>@$PROJECT_DIR@g" \
  -e "s@<EXEC_START>@$EXEC_START@g" \
  "$TEMPLATE" > "$OUTPUT"

sudo cp "$OUTPUT" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pothead.service

echo "Successfully installed systemd service file: $OUTPUT"
