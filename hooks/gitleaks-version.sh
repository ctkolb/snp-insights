# SPDX-License-Identifier: GPL-3.0-or-later
# Sourced by the hooks (not a hook itself). Warns when the local gitleaks
# differs from the release CI pins, since default rules change between releases.
# Warning only: CI is the enforcement.
check_gitleaks_version() {
    pinned="$(sed -n 's/^ *VER=\([0-9][0-9.]*\) # gitleaks-pin$/\1/p' .github/workflows/ci.yml 2>/dev/null | head -n 1)"
    local_ver="$(gitleaks version 2>/dev/null | head -n 1 | awk '{print $NF}' | tr -d 'v')"
    if [ -n "$pinned" ] && [ "$local_ver" != "$pinned" ]; then
        echo "$1: gitleaks ${local_ver:-unknown} differs from the CI pin $pinned; a clean local scan may not match CI." >&2
    fi
}
