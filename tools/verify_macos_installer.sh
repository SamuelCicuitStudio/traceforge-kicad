#!/usr/bin/env bash
set -euxo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'Run this check on macOS.' >&2; exit 2; }

archive=(dist/TraceForge-*-KiCad10-macOS.zip)
[[ ${#archive[@]} == 1 && -f "${archive[0]}" ]] || { echo 'Expected one macOS ZIP.' >&2; exit 1; }
temp="$(mktemp -d)"
unzip -q "${archive[0]}" -d "$temp"
package=("$temp"/TraceForge-*)
[[ ${#package[@]} == 1 && -d "${package[0]}" ]] || exit 1
fake_python="$temp/fake-python3"
printf '#!/bin/sh\nexit 0\n' > "$fake_python"
chmod +x "$fake_python"
plugins="$temp/KiCad plugins"
bash "${package[0]}/tools/install_native_bridge_macos.sh" --python "$fake_python" --plugins-dir "$plugins"
destination="$plugins/traceforge_native_bridge"
[[ -L "$destination" ]] || exit 1
expected_source="$(cd "${package[0]}/native_bridge" && pwd -P)"
[[ "$(readlink "$destination")" == "$expected_source" ]] || exit 1
[[ "$(cat "${package[0]}/traceforge-python.txt")" == "$fake_python" ]] || exit 1
bash "${package[0]}/tools/install_native_bridge_macos.sh" --python "$fake_python" --plugins-dir "$plugins"
mkdir -p "$temp/blocked/traceforge_native_bridge"
if bash "${package[0]}/tools/install_native_bridge_macos.sh" --python "$fake_python" --plugins-dir "$temp/blocked" >/dev/null 2>&1; then
  echo 'Installer replaced an ordinary directory.' >&2
  exit 1
fi
echo 'PASS: macOS installer link, repeat install, and ordinary-directory protection'
