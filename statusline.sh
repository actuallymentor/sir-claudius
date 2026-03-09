#!/bin/bash
# -----------------------------------------------------------
# statusline.sh — portable Claude Code statusline for containers
#
# A Linux-compatible rewrite of the host's statusline-command.sh.
# Uses curl (not swift) and GNU date (not BSD date).
# Reads CLAUDE_SESSION_KEY and CLAUDE_ORG_ID from env vars.
# -----------------------------------------------------------

# Display toggles — all enabled by default, fully self-contained
show_modifiers=1
show_branch=1
show_usage=1
show_bar=1
show_reset=1

# Read JSON input from Claude Code (stdin — currently unused but required)
cat > /dev/null

# ---- colours ----

GREEN=$'\033[0;32m'
GRAY=$'\033[0;90m'
YELLOW=$'\033[0;33m'
RESET=$'\033[0m'

# 10-level gradient: dark green → deep red
LEVEL_1=$'\033[38;5;22m'
LEVEL_2=$'\033[38;5;28m'
LEVEL_3=$'\033[38;5;34m'
LEVEL_4=$'\033[38;5;100m'
LEVEL_5=$'\033[38;5;142m'
LEVEL_6=$'\033[38;5;178m'
LEVEL_7=$'\033[38;5;172m'
LEVEL_8=$'\033[38;5;166m'
LEVEL_9=$'\033[38;5;160m'
LEVEL_10=$'\033[38;5;124m'

# ---- session modifiers (yolo, worktree, resume, etc.) ----

CYAN=$'\033[0;36m'
MAGENTA=$'\033[0;35m'

modifiers_text=""
if [ "$show_modifiers" = "1" ]; then
    mods="${CLAUDIUS_MODIFIERS:-}"
    if [ -n "$mods" ] && [ "$mods" != "default" ]; then
        # Uppercase each modifier and join with middle dots
        mod_display=""
        for m in $mods; do
            upper=$(echo "$m" | tr '[:lower:]' '[:upper:]')
            mod_display="${mod_display:+${mod_display}·}${upper}"
        done
        modifiers_text="${MAGENTA}${mod_display}${RESET}"
    else
        modifiers_text="${CYAN}claudius${RESET}"
    fi
fi

# ---- git branch ----

branch_text=""
if [ "$show_branch" = "1" ]; then
    if git rev-parse --git-dir > /dev/null 2>&1; then
        branch=$(git branch --show-current 2>/dev/null)
        [ -n "$branch" ] && branch_text="${GREEN}⎇ ${branch}${RESET}"
    fi
fi

# ---- usage (via curl) ----

usage_text=""
if [ "$show_usage" = "1" ]; then

    # Graceful degradation: if credentials are missing, show a placeholder
    if [ -n "$CLAUDE_SESSION_KEY" ] && [ -n "$CLAUDE_ORG_ID" ]; then

        api_result=$(curl -s --max-time 5 \
            -H "Cookie: sessionKey=$CLAUDE_SESSION_KEY" \
            -H "Accept: application/json" \
            "https://claude.ai/api/organizations/$CLAUDE_ORG_ID/usage" 2>/dev/null)

        # Parse JSON with jq (available in the container)
        utilization=$(echo "$api_result" | jq -r '.five_hour.utilization // empty' 2>/dev/null)
        resets_at=$(echo "$api_result" | jq -r '.five_hour.resets_at // empty' 2>/dev/null)
    fi

    if [ -n "$utilization" ] && [ "$utilization" != "null" ]; then

        # Pick colour based on usage level
        if   [ "$utilization" -le 10 ]; then usage_color="$LEVEL_1"
        elif [ "$utilization" -le 20 ]; then usage_color="$LEVEL_2"
        elif [ "$utilization" -le 30 ]; then usage_color="$LEVEL_3"
        elif [ "$utilization" -le 40 ]; then usage_color="$LEVEL_4"
        elif [ "$utilization" -le 50 ]; then usage_color="$LEVEL_5"
        elif [ "$utilization" -le 60 ]; then usage_color="$LEVEL_6"
        elif [ "$utilization" -le 70 ]; then usage_color="$LEVEL_7"
        elif [ "$utilization" -le 80 ]; then usage_color="$LEVEL_8"
        elif [ "$utilization" -le 90 ]; then usage_color="$LEVEL_9"
        else                                 usage_color="$LEVEL_10"
        fi

        # Progress bar
        if [ "$show_bar" = "1" ]; then
            if [ "$utilization" -eq 0 ]; then
                filled_blocks=0
            elif [ "$utilization" -eq 100 ]; then
                filled_blocks=10
            else
                filled_blocks=$(( (utilization * 10 + 50) / 100 ))
            fi
            [ "$filled_blocks" -lt 0 ] && filled_blocks=0
            [ "$filled_blocks" -gt 10 ] && filled_blocks=10
            empty_blocks=$((10 - filled_blocks))

            progress_bar=" "
            i=0; while [ $i -lt $filled_blocks ]; do progress_bar="${progress_bar}▓"; i=$((i + 1)); done
            i=0; while [ $i -lt $empty_blocks ];  do progress_bar="${progress_bar}░"; i=$((i + 1)); done
        else
            progress_bar=""
        fi

        # Reset time (GNU date)
        reset_time_display=""
        if [ "$show_reset" = "1" ] && [ -n "$resets_at" ] && [ "$resets_at" != "null" ]; then
            # Strip fractional seconds for GNU date compatibility
            iso_time=$(echo "$resets_at" | sed 's/\.[0-9]*Z$/Z/; s/\.[0-9]*+/+/')
            epoch=$(date -d "$iso_time" "+%s" 2>/dev/null)

            if [ -n "$epoch" ]; then
                reset_time=$(date -d "@$epoch" "+%H:%M" 2>/dev/null)
                [ -n "$reset_time" ] && reset_time_display=$(printf " → Reset: %s" "$reset_time")
            fi
        fi

        usage_text="${usage_color}Usage: ${utilization}%${progress_bar}${reset_time_display}${RESET}"
    else
        usage_text="${YELLOW}Usage: ~${RESET}"
    fi
fi

# ---- assemble output ----

output=""
separator="${GRAY} │ ${RESET}"

[ -n "$modifiers_text" ] && output="${modifiers_text}"

if [ -n "$branch_text" ]; then
    [ -n "$output" ] && output="${output}${separator}"
    output="${output}${branch_text}"
fi

if [ -n "$usage_text" ]; then
    [ -n "$output" ] && output="${output}${separator}"
    output="${output}${usage_text}"
fi

printf "%s\n" "$output"
