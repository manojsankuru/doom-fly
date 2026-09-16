#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOOMFLY="${DOOMFLY:-$ROOT/doomfly}"
DATASET="${DATASET:-malecns_v1}"
MIN_RAM_GB="${MIN_RAM_GB:-8}"
DISK_MARGIN_GB="${DISK_MARGIN_GB:-3}"
SHIM_DIR="$ROOT/tools/doomfly/bin"
if [ -d "$SHIM_DIR" ]; then
    PATH="$SHIM_DIR:$PATH"
fi

pass=0
fail=0

report() {
    local status="$1" name="$2" detail="$3"
    if [ "$status" = PASS ]; then
        pass=$((pass + 1))
        printf '  \033[32mPASS\033[0m  %-18s %s\n' "$name" "$detail"
    else
        fail=$((fail + 1))
        printf '  \033[31mFAIL\033[0m  %-18s %s\n' "$name" "$detail"
    fi
}

find_python() {
    if [ -n "${PYTHON:-}" ]; then
        echo "$PYTHON"
    elif [ -x "$DOOMFLY/.venv-neural/bin/python" ]; then
        echo "$DOOMFLY/.venv-neural/bin/python"
    elif command -v python3.11 >/dev/null 2>&1; then
        command -v python3.11
    else
        command -v python3 2>/dev/null || true
    fi
}

check_repo() {
    if [ -f "$DOOMFLY/doom/datasets.json" ]; then
        report PASS doomfly "$DOOMFLY"
    else
        report FAIL doomfly "no doom/datasets.json under $DOOMFLY (set DOOMFLY=/path/to/clone)"
    fi
}

check_python() {
    PY="$(find_python)"
    if [ -z "$PY" ] || ! "$PY" -c '' 2>/dev/null; then
        report FAIL python "no interpreter found (set PYTHON=/path/to/python3.11)"
        PY=""
        return
    fi
    local version
    version="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
    case "$version" in
        3.11.*) report PASS python "$version at $PY" ;;
        *) report FAIL python "$version at $PY, the pinned stack needs 3.11.x" ;;
    esac
}

check_compiler() {
    local compiler=""
    for candidate in clang++ g++; do
        if command -v "$candidate" >/dev/null 2>&1; then
            compiler="$candidate"
            break
        fi
    done
    if [ -z "$compiler" ]; then
        report FAIL compiler "no clang++ or g++ on PATH; doom.build_kernel calls clang++"
        return
    fi
    local work
    work="$(mktemp -d)"
    printf 'extern "C" int probe(){return 42;}\n' > "$work/probe.cpp"
    if "$compiler" -O3 -std=c++17 -shared -fPIC "$work/probe.cpp" -o "$work/libprobe.so" 2>"$work/err"; then
        local note="" path
        path="$(command -v clang++ 2>/dev/null || true)"
        if [ -z "$path" ]; then
            note=" (no clang++; build_kernel calls clang++, so it needs a shim)"
        elif [ -f "$path" ] && head -c 200 "$path" | grep -q 'exec g++'; then
            note=" (clang++ at $path is a g++ shim)"
        fi
        report PASS compiler "$compiler builds a c++17 shared library$note"
    else
        report FAIL compiler "$compiler cannot build a shared library: $(tr '\n' ' ' < "$work/err" | cut -c1-120)"
    fi
    rm -rf "$work"
}

check_ram() {
    local available_kb=""
    if [ -r /proc/meminfo ]; then
        available_kb="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
    fi
    if [ -z "$available_kb" ]; then
        report FAIL ram "cannot read /proc/meminfo"
        return
    fi
    local available_gb total_gb
    available_gb="$(awk -v kb="$available_kb" 'BEGIN{printf "%.1f", kb/1048576}')"
    total_gb="$(awk '/^MemTotal:/{printf "%.1f", $2/1048576}' /proc/meminfo)"
    if awk -v a="$available_gb" -v m="$MIN_RAM_GB" 'BEGIN{exit !(a>=m)}'; then
        report PASS ram "${available_gb} GB available of ${total_gb} GB"
    else
        report FAIL ram "${available_gb} GB available of ${total_gb} GB, want ${MIN_RAM_GB} GB for 166,700 neurons and 25,582,938 edges"
    fi
}

remote_size() {
    curl -sIL --max-time 20 "$1" 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /^content-length:/{n=$2} END{gsub(/\r/,"",n); print n+0}'
}

check_disk() {
    local registry="$DOOMFLY/doom/datasets.json"
    if [ -z "${PY:-}" ] || [ ! -f "$registry" ]; then
        report FAIL disk "need a working python and $registry to size the download"
        return
    fi
    local data_dir="$DOOMFLY/connectome_data/$DATASET"
    local free_kb free_gb needed_bytes=0 missing=0 unknown=0 files
    files="$("$PY" - "$registry" "$DATASET" <<'PY'
import json, sys
registry = json.load(open(sys.argv[1]))['datasets'][sys.argv[2]]['files']
for name, url in registry.items():
    print(name, url)
PY
)"
    if [ -z "$files" ]; then
        report FAIL disk "dataset $DATASET is not in doom/datasets.json"
        return
    fi
    while read -r name url; do
        [ -n "$name" ] || continue
        if [ -f "$data_dir/$name" ]; then
            continue
        fi
        missing=$((missing + 1))
        local size
        size="$(remote_size "$url")"
        if [ "$size" -gt 0 ] 2>/dev/null; then
            needed_bytes=$((needed_bytes + size))
        else
            unknown=$((unknown + 1))
        fi
    done <<< "$files"
    free_kb="$(df -Pk "$DOOMFLY" | awk 'NR==2{print $4}')"
    free_gb="$(awk -v kb="$free_kb" 'BEGIN{printf "%.1f", kb/1048576}')"
    local needed_gb
    needed_gb="$(awk -v b="$needed_bytes" -v m="$DISK_MARGIN_GB" 'BEGIN{printf "%.1f", b/1073741824+m}')"
    local detail="need ${needed_gb} GB (${missing} file(s) to fetch plus ${DISK_MARGIN_GB} GB for the prepared graph), ${free_gb} GB free"
    if [ "$unknown" -gt 0 ]; then
        detail="$detail, ${unknown} size(s) unknown (offline?)"
    fi
    if awk -v f="$free_gb" -v n="$needed_gb" 'BEGIN{exit !(f>=n)}'; then
        report PASS disk "$detail"
    else
        report FAIL disk "$detail"
    fi
}

check_vizdoom() {
    if [ -z "${PY:-}" ]; then
        report FAIL vizdoom "no python to import it with"
        return
    fi
    local output scratch
    scratch="$(mktemp -d)"
    output="$(cd "$scratch" && "$PY" - <<'PY' 2>&1
import sys
try:
    import vizdoom as vzd
except Exception as exc:
    print(f"import failed: {type(exc).__name__}: {exc}")
    sys.exit(1)
game = vzd.DoomGame()
game.set_window_visible(False)
game.set_sound_enabled(False)
try:
    game.load_config(vzd.scenarios_path + "/basic.cfg")
    game.set_doom_game_path(vzd.__path__[0] + "/freedoom2.wad")
    game.init()
    state = game.get_state()
    shape = None if state is None else state.screen_buffer.shape
    game.close()
except Exception as exc:
    print(f"headless start failed: {type(exc).__name__}: {exc}")
    sys.exit(1)
print(f"{vzd.__version__} started headless, frame {shape}")
PY
)"
    local status=$?
    rm -rf "$scratch"
    if [ "$status" -eq 0 ]; then
        report PASS vizdoom "$output"
    else
        report FAIL vizdoom "$(printf '%s' "$output" | tr '\n' ' ' | cut -c1-160)"
    fi
}

printf '\nflyview preflight (checks only, installs nothing)\n\n'
check_repo
check_python
check_compiler
check_ram
check_disk
check_vizdoom
printf '\n%d passed, %d failed\n\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
