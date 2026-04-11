#!/bin/bash
# narrative-claude.sh — one-click launcher for hands-free Claude Code.
#
# 1. Stops any previously-running dictation listener.
# 2. Tells Apple Terminal to open a new window running `claude`, and
#    captures the window ID of that new window.
# 3. Writes the window ID into ~/NarrateClaude/dictation/state/target.json.
# 4. Waits for claude to boot (banner, narrate-mode prep, prompt drawn).
# 5. Starts the hands-free dictation listener pointed at that window.
#
# When you close the Terminal window, dispatch's watchdog notices
# within ~5 seconds and shuts the listener down automatically.
#
# ── Running this ─────────────────────────────────────────────────────
# You can run this script directly:
#     bash ~/NarrateClaude/narrative-claude.sh
#
# …or wrap it in a macOS .app bundle so you can double-click it from
# Finder / the Dock / a Desktop shortcut. Minimal .app structure:
#
#     NarrativeClaude.app/
#       Contents/
#         Info.plist               <- CFBundleExecutable = NarrativeClaude
#         MacOS/
#           NarrativeClaude        <- symlink or copy of this script, +x
#         Resources/
#           AppIcon.icns           <- your icon (optional)
#
# See README.md for a short "build your own .app wrapper" recipe.

DICT_DIR="$HOME/NarrateClaude/dictation"
DICT="$DICT_DIR/bin/dictation"
STATE_DIR="$DICT_DIR/state"

# 1. Kill any previous listener so the new window owns the mic.
if [ -x "$DICT" ]; then
    "$DICT" stop >/dev/null 2>&1 || true
fi

# 2. Open the Terminal window and capture its ID. `do script` returns the
#    new tab; we read its tty path and then walk Terminal's windows looking
#    for the tab with a matching tty. tty comparison is robust whereas
#    `tabs of w contains newTab` is finicky for object references.
WIN_ID=$(/usr/bin/osascript <<'OSA'
tell application "Terminal"
    activate
    set newTab to do script "cd ~/NarrateClaude && export CLAUDE_SESSION_LABEL='NarrativeClaude' && claude"
    set newTty to ""
    try
        set newTty to tty of newTab
    end try
    delay 0.4
    set foundId to ""
    if newTty is not "" then
        repeat with w in windows
            repeat with t in tabs of w
                try
                    if tty of t is newTty then
                        set foundId to (id of w) as text
                        exit repeat
                    end if
                end try
            end repeat
            if foundId is not "" then exit repeat
        end repeat
    end if
    if foundId is "" then
        -- Fallback: assume the new tab is in the front window
        try
            set foundId to (id of front window) as text
        end try
    end if
    return foundId
end tell
OSA
)

if [ -z "$WIN_ID" ]; then
    /usr/bin/osascript -e 'display dialog "NarrativeClaude: failed to open Terminal window." buttons {"OK"} default button 1 with icon stop'
    exit 1
fi

# 3. Save the binding so dispatch knows where to paste.
mkdir -p "$STATE_DIR"
cat > "$STATE_DIR/target.json" <<JSON
{ "app": "Terminal", "window_id": $WIN_ID }
JSON

# 4. Give `claude` time to boot (banner, narrate-mode prep, prompt drawn)
#    before we start pasting things into its prompt.
sleep 6

# 5. Start the hands-free listener.
# NARRATE_DICTATION_LAUNCHER is the gate that lets `dictation start`
# actually run — anything else calling `dictation start` is refused.
if [ -x "$DICT" ]; then
    NARRATE_DICTATION_LAUNCHER="NarrativeClaude.app" "$DICT" start >/dev/null 2>&1 || true
fi
