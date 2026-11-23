#!/usr/bin/env bash
# Run a short BatchSlicer demo, made for recording (asciinema or a screen recorder).
#
# It builds its own folder (~/demo by default) with a small kit as a zip file and a
# multi-colour 3MF project, a demo configuration and a "k2" profile, so the commands
# on screen stay short. Your own configuration, profiles and services are not touched.
#
#   ./demo.sh            set up ~/demo (again) and run the demo
#   ./demo.sh --reset    remove ~/demo
#
# Recording:
#   asciinema rec demo.cast --cols 100 --rows 30 --idle-time-limit 2 -c ./demo.sh
#   agg --font-size 18 --speed 1.5 demo.cast demo.gif
#
# Change the settings below to fit your printer and files. With SEND empty, nothing is
# sent; otherwise the G-code is uploaded to that printer (never started).

set -euo pipefail

DEMO="${DEMO_DIR:-$HOME/demo}"
SEND="${SEND-192.168.1.242}"                      # printer to send to; empty to not send
SLICER="orca"
PRINTER="Creality K2 Plus 0.4 nozzle"
FILAMENT="Generic PETG @K2 Plus-all"
PROCESS="0.20mm Standard @Creality K2 Plus 0.4 nozzle"
KIT_PARTS=(
    "$HOME/Downloads/-_boat v4_antenna mount.stl"
    "$HOME/Downloads/-_boat v4_front arm rest.stl"
    "$HOME/Downloads/-_boat v4_front back rest.stl"
)
MULTICOLOUR="$HOME/Downloads/Element+RC+Zuul+Front+Bumper+/Zuul Front Bumper 2 Color.3mf"
USER_CONFIG="${BATCHSLICER_USER_CONFIG:-$HOME/.config/batchslicer/config.yaml}"
TYPING_DELAY=0.035   # seconds per typed character
PAUSE=1.5            # seconds to read a result before the next command

if [[ "${1:-}" == "--reset" ]]; then
    rm -rf "$DEMO"
    echo "Removed $DEMO"
    exit 0
fi

# --- Set up the demo folder (not shown when recording starts after this) ----------------

command -v batchslicer >/dev/null || { echo "batchslicer is not installed (pipx install batchslicer)"; exit 1; }
for file in "${KIT_PARTS[@]}" "$MULTICOLOUR" "$USER_CONFIG"; do
    [[ -f "$file" ]] || { echo "Missing: $file (edit the settings at the top of $0)"; exit 1; }
done
python="$(head -1 "$(command -v batchslicer)" | sed 's/^#!//')"   # BatchSlicer's own Python, with PyYAML

rm -rf "$DEMO"
mkdir -p "$DEMO/kits/boat-kit/files" "$DEMO/output"
for part in "${KIT_PARTS[@]}"; do
    name="$(basename "$part")"; name="${name#-_boat v4_}"; name="${name// /-}"
    cp "$part" "$DEMO/kits/boat-kit/files/$name"
done
(cd "$DEMO/kits" && "$python" -c "
import pathlib, zipfile
with zipfile.ZipFile('boat-kit.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(pathlib.Path('boat-kit').rglob('*.stl')):
        archive.write(path)
") && rm -rf "$DEMO/kits/boat-kit"
cp "$MULTICOLOUR" "$DEMO/kits/bumper.3mf"

"$python" - "$USER_CONFIG" "$DEMO" "$SLICER" "$PRINTER" "$FILAMENT" "$PROCESS" "$SEND" <<'PY'
import sys, yaml
user_config, demo, slicer, printer, filament, process, send = sys.argv[1:]
config = yaml.safe_load(open(user_config, encoding="utf-8")) or {}
config["paths"] = {**(config.get("paths") or {}),
                   "incoming": f"{demo}/kits", "output": f"{demo}/output",
                   "profiles": f"{demo}/profiles.yaml"}
with open(f"{demo}/config.yaml", "w", encoding="utf-8") as file:
    yaml.safe_dump(config, file, sort_keys=False)
profile = {"slicer": slicer, "printer": printer, "filament": filament, "process": process,
           "plates": True, "output": f"{demo}/output"}
if send:
    profile.update(send=send, loaded_filaments=True)
with open(f"{demo}/profiles.yaml", "w", encoding="utf-8") as file:
    yaml.safe_dump({"k2": profile}, file, sort_keys=False)
PY
export BATCHSLICER_CONFIG="$DEMO/config.yaml"
cd "$DEMO"

# --- The demo -----------------------------------------------------------------------------

type_out() {
    printf '\033[1;32m$\033[0m '
    local text="$*" i
    for ((i = 0; i < ${#text}; i++)); do
        printf '%s' "${text:i:1}"
        sleep "$TYPING_DELAY"
    done
    printf '\n'
}

run() {
    type_out "$*"
    sleep 0.4
    "$@" || true
    sleep "$PAUSE"
    printf '\n'
}

comment() {
    printf '\033[2m# %s\033[0m\n' "$*"
    sleep 0.8
}

clear
comment "BatchSlicer: slice with your own presets, put kits on plates, match colours to the CFS"
run batchslicer --version
run ls kits
comment "What would happen? --dry-run slices nothing and sends nothing"
run batchslicer --profile k2 --input kits/bumper.3mf --dry-run
comment "A two-colour project, matched to the spools loaded in the CFS"
run batchslicer --profile k2 --input kits/bumper.3mf
comment "A downloaded kit, zip and all: unpacked, put on one plate"
run batchslicer --profile k2 --input kits/boat-kit.zip
comment "Done. github.com/drak42/batch_slicer"
sleep 2
