#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: install_native_bridge_macos.sh [--replace-existing] [--plugins-dir DIR] [--python PYTHON3]' >&2
}

replace_existing=false
plugins_dir="${TRACEFORGE_KICAD_PLUGINS_DIR:-$HOME/Documents/KiCad/10.0/scripting/plugins}"
python_bin="${TRACEFORGE_PYTHON:-}"
while (($#)); do
  case "$1" in
    --replace-existing) replace_existing=true; shift ;;
    --plugins-dir|--python)
      (($# >= 2)) || { usage; exit 2; }
      if [[ "$1" == --plugins-dir ]]; then plugins_dir="$2"; else python_bin="$2"; fi
      shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

[[ "$(uname -s)" == Darwin ]] || { echo 'This installer runs on macOS only.' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_dir="$root/native_bridge"
[[ -f "$source_dir/__init__.py" ]] || { echo 'Extract the complete TraceForge ZIP before installing.' >&2; exit 1; }

if [[ -z "$python_bin" ]]; then python_bin="$(command -v python3 || true)"; fi
[[ -n "$python_bin" && -x "$python_bin" ]] || { echo 'Choose a Python 3 interpreter with --python PATH.' >&2; exit 1; }
python_bin="$(cd "$(dirname "$python_bin")" && pwd -P)/$(basename "$python_bin")"
"$python_bin" -c 'import wx; assert wx.version()' >/dev/null 2>&1 || {
  echo 'The selected Python cannot import wxPython. Install wxPython for this interpreter or pass --python PATH.' >&2
  exit 1
}

mkdir -p "$plugins_dir"
plugins_dir="$(cd "$plugins_dir" && pwd -P)"
destination="$plugins_dir/traceforge_native_bridge"
if [[ -L "$destination" ]]; then
  existing="$(readlink "$destination")"
  if [[ "$existing" != "$source_dir" ]]; then
    [[ "$replace_existing" == true ]] || {
      echo "Another TraceForge symlink exists at $destination. Use --replace-existing after closing KiCad." >&2
      exit 1
    }
    # Remove only the verified symlink entry, never its target.
    unlink "$destination"
    ln -s "$source_dir" "$destination"
  fi
elif [[ -e "$destination" ]]; then
  echo "An ordinary file or directory exists at $destination. Preserve it and inspect manually." >&2
  exit 1
else
  ln -s "$source_dir" "$destination"
fi
printf '%s\n' "$python_bin" > "$root/traceforge-python.txt"
echo "TraceForge linked at $destination"
echo "Panel Python: $python_bin"
echo 'Restart KiCad 10 PCB Editor, then open Tools > External Plugins > TraceForge.'
