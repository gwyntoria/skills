# No stty mode changes: read -s restores echo even on cancellation/signals.
read_key() {
    local suffix=""
    KEY=""
    IFS= read -rsn1 KEY || return 1
    if [ "$KEY" = $'\e' ]; then
        # Allow split arrow sequences while keeping standalone Esc responsive.
        IFS= read -rsn2 -t 0.05 suffix || true
        KEY="$KEY$suffix"
    fi
}

# Read a confirmation into REPLY, retaining Enter submission and backspace.
# A standalone Esc discards pending input and returns the existing Back answer.
read_back_answer() {
    REPLY=""
    while read_key; do
        case "$KEY" in
        '')
            printf '\n'
            return 0
            ;;
        $'\e')
            REPLY=b
            printf '\n'
            return 0
            ;;
        $'\177' | $'\b')
            if [ -n "$REPLY" ]; then
                REPLY="${REPLY%?}"
                printf '\b \b'
            fi
            ;;
        $'\e'*) ;; # Navigation sequences are not confirmation text or Back.
        *)
            REPLY+="$KEY"
            printf '%s' "$KEY"
            ;;
        esac
    done
    return 1
}

# Fixed-height pages keep long skill catalogs usable in a small terminal.
# Save each page's selection/cursor before reading a key, including Back/Exit.
# Return 0 to continue, 1 to exit, 2 to go back, or 3 on plan preparation failure.
choose_items() {
    local status=0
    printf '\033[?25l'
    choose_items_page "$@" || status=$?
    printf '\033[?25h'
    return "$status"
}

choose_items_page() {
    local page="$1" title="$2" multiple="$3" defaults="$4"
    shift 4
    local options=("$@") selected=() restored=() cursor=0 i start end mark
    # Defaults are one shared flag or a space-separated flag for each option.
    if [[ "$defaults" = *" "* ]]; then
        read -r -a selected <<<"$defaults"
    else
        for ((i = 0; i < ${#options[@]}; i++)); do selected+=("$defaults"); done
    fi
    if [ "${MENU_VISITED[page]:-0}" -eq 1 ]; then
        cursor="${MENU_CURSORS[page]}"
        for ((i = 0; i < ${#options[@]}; i++)); do selected[i]=0; done
        IFS=' ' read -r -a restored <<<"${MENU_CHOICES[page]}"
        for i in "${restored[@]+"${restored[@]}"}"; do selected[i]=1; done
    fi
    while :; do
        MENU_SELECTED=()
        for ((i = 0; i < ${#options[@]}; i++)); do
            [ "${selected[i]}" -eq 0 ] || MENU_SELECTED+=("$i")
        done
        MENU_VISITED[page]=1
        MENU_CURSORS[page]="$cursor"
        MENU_CHOICES[page]="${MENU_SELECTED[*]}"
        printf '\033[H\033[2J'
        if [ "$page" -eq 11 ]; then
            print_install_plan || return 3
        else
            printf '%s\n\n' "$title"
        fi
        start=$((cursor / 8 * 8))
        end=$((start + 8))
        for ((i = start; i < end && i < ${#options[@]}; i++)); do
            mark=' '
            [ "${selected[i]}" -eq 0 ] || mark=x
            if [ "$i" -eq "$cursor" ]; then printf '> '; else printf '  '; fi
            if [ "$multiple" -eq 1 ]; then printf '[%s] ' "$mark"; fi
            printf '%s\n' "${options[i]}"
        done
        if [ "$page" -ne 11 ]; then
            printf '\nItem %s/%s' "$((cursor + 1))" "${#options[@]}"
            if [ "$multiple" -eq 1 ]; then printf ' | Selected: %s' "${#MENU_SELECTED[@]}"; fi
            printf '\n'
        fi
        if [ "$multiple" -eq 1 ]; then
            printf '↑↓ Move   Space Toggle   Enter Continue\na All   n None'
        else
            printf '↑↓ Move   Enter Choose'
        fi
        if [ "$page" -ne 0 ]; then printf '   b/Esc Back'; fi
        printf '   q Exit\n'
        read_key || return 1
        case "$KEY" in
        $'\e[A' | $'\eOA') cursor=$(((cursor + ${#options[@]} - 1) % ${#options[@]})) ;;
        $'\e[B' | $'\eOB') cursor=$(((cursor + 1) % ${#options[@]})) ;;
        ' ')
            if [ "$multiple" -eq 1 ]; then selected[cursor]=$((1 - selected[cursor])); fi
            ;;
        a | n)
            if [ "$multiple" -eq 1 ]; then
                for ((i = 0; i < ${#options[@]}; i++)); do
                    selected[i]=0
                    [ "$KEY" != a ] || selected[i]=1
                done
            fi
            ;;
        '')
            if [ "$multiple" -eq 0 ]; then MENU_SELECTED=("$cursor"); fi
            return 0
            ;;
        b | B | $'\e') if [ "$page" -ne 0 ]; then return 2; fi ;;
        q | Q) return 1 ;;
        esac
    done
}

# Keep each picker row tied to its entry so selection does not collapse distinct installations.
choose_skill_repositories() {
    local status=0
    printf '\033[?25l'
    choose_skill_repositories_page "$@" || status=$?
    printf '\033[?25h'
    return "$status"
}

choose_skill_repositories_page() {
    local page="$1" title="$2" color="$3" cursor=0 child=-1 i j group found start end total chosen mark row key_page selected_count
    local groups=() item_groups=() selected=() children=()
    local group_heading=Repository group_list=Repos enter_action
    if [ "$page" -eq 9 ]; then
        group_heading=Source
        group_list=Sources
    fi
    local dependency_mode="${4:-0}" notice='' reasons explicit=() requirements=() before=() touched=()
    for ((i = 0; i < ${#REPO_ITEM_LABELS[@]}; i++)); do
        group="${REPO_ITEM_GROUPS[i]}"
        found=-1
        for ((j = 0; j < ${#groups[@]}; j++)); do [ "${groups[j]}" != "$group" ] || {
            found="$j"
            break
        }; done
        if [ "$found" -eq -1 ]; then
            found="${#groups[@]}"
            groups+=("$group")
        fi
        item_groups+=("$found")
        selected+=(0)
    done
    for i in "${REPO_SELECTED[@]+"${REPO_SELECTED[@]}"}"; do selected[i]=1; done
    if [ "$dependency_mode" -eq 1 ]; then
        explicit=("${REPO_EXPLICIT[@]}")
        picker_dependency_graph
        picker_resolve_dependencies
    fi
    cursor="${MENU_CURSORS[page]:-0}"
    while :; do
        REPO_SELECTED=()
        for ((i = 0; i < ${#selected[@]}; i++)); do [ "${selected[i]}" -eq 0 ] || REPO_SELECTED+=("$i"); done
        selected_count="${#REPO_SELECTED[@]}"
        if [ "$dependency_mode" -eq 1 ]; then REPO_EXPLICIT=("${explicit[@]}"); fi
        printf '\033[H\033[2J%s\n' "$title"
        [ -z "$notice" ] || printf '%s\n' "$notice"
        if [ "$child" -lt 0 ]; then
            total=$((${#groups[@]} + 1))
            MENU_CURSORS[page]="$cursor"
        else
            printf '%s: %s\n' "$group_heading" "${groups[child]}"
            children=()
            for ((i = 0; i < ${#selected[@]}; i++)); do [ "${item_groups[i]}" -ne "$child" ] || children+=("$i"); done
            selected_count=0
            for i in "${children[@]}"; do selected_count=$((selected_count + selected[i])); done
            total="${#children[@]}"
            key_page=$((100 + page * 100 + child))
            MENU_CURSORS[key_page]="$cursor"
        fi
        if [ "$cursor" -ge "$total" ]; then cursor=0; fi
        printf '\n'
        start=$((cursor / 8 * 8))
        end=$((start + 8))
        for ((row = start; row < end && row < total; row++)); do
            if [ "$row" -eq "$cursor" ]; then printf '> '; else printf '  '; fi
            if [ "$child" -lt 0 ]; then
                if [ "$row" -eq "${#groups[@]}" ]; then
                    printf 'Continue\n'
                    continue
                fi
                chosen=0
                found=0
                for ((i = 0; i < ${#selected[@]}; i++)); do
                    if [ "${item_groups[i]}" -eq "$row" ]; then
                        found=$((found + 1))
                        chosen=$((chosen + selected[i]))
                    fi
                done
                mark=' '
                if [ "$chosen" -eq "$found" ]; then mark=x; elif [ "$chosen" -gt 0 ]; then mark=-; fi
                printf '[%s] \033[%sm%s\033[0m (%s/%s)\n' "$mark" "$color" "${groups[row]}" "$chosen" "$found"
            else
                i="${children[row]}"
                mark=' '
                [ "${selected[i]}" -eq 0 ] || mark=x
                printf '[%s] \033[%sm%s\033[0m\n' "$mark" "$color" "${REPO_ITEM_LABELS[i]}"
                if [ "$dependency_mode" -eq 1 ] && [ "${selected[i]}" -eq 1 ] && [ "${explicit[i]}" -eq 0 ]; then
                    reasons=''
                    for ((j = 0; j < ${#selected[@]}; j++)); do
                        if [ "${explicit[j]}" -eq 1 ] && [[ "${requirements[j]}" = *" $i "* ]]; then
                            reasons+="${reasons:+, }"$'\033[32m'"${REPO_ITEM_LABELS[j]}"$'\033[0m'
                        fi
                    done
                    printf '      [dependency: %s]\n' "$reasons"
                fi
            fi
        done
        printf '\nItem %s/%s | Selected: %s\n' "$((cursor + 1))" "$total" "$selected_count"
        if [ "$child" -ge 0 ]; then
            printf '↑↓ Move   Space Toggle   Enter %s\n' "$group_list"
        else
            enter_action=Open
            if [ "$cursor" -eq "${#groups[@]}" ]; then enter_action=Continue; fi
            printf '↑↓ Move   Space Toggle group   Enter %s\n' "$enter_action"
        fi
        printf 'a All   n None   c Continue   b/Esc Back   q Exit\n'
        read_key || return 1
        case "$KEY" in
        $'\e[A' | $'\eOA') cursor=$(((cursor + total - 1) % total)) ;;
        $'\e[B' | $'\eOB') cursor=$(((cursor + 1) % total)) ;;
        ' ' | a | n)
            before=("${selected[@]}")
            touched=()
            notice=''
            if [ "$child" -lt 0 ]; then
                [ "$cursor" -lt "${#groups[@]}" ] || [ "$KEY" != ' ' ] || continue
                found=1
                if [ "$KEY" = n ]; then
                    found=0
                elif [ "$KEY" = ' ' ]; then
                    chosen=0
                    total=0
                    for ((i = 0; i < ${#selected[@]}; i++)); do
                        if [ "${item_groups[i]}" -eq "$cursor" ]; then
                            total=$((total + 1))
                            chosen=$((chosen + selected[i]))
                        fi
                    done
                    [ "$chosen" -ne "$total" ] || found=0
                fi
                for ((i = 0; i < ${#selected[@]}; i++)); do
                    if [ "$KEY" != ' ' ] || [ "${item_groups[i]}" -eq "$cursor" ]; then
                        selected[i]="$found"
                        touched+=("$i")
                    fi
                done
            elif [ "$KEY" = ' ' ]; then
                i="${children[cursor]}"
                selected[i]=$((1 - selected[i]))
                touched+=("$i")
            else
                found=1
                [ "$KEY" != n ] || found=0
                for i in "${children[@]}"; do
                    selected[i]="$found"
                    touched+=("$i")
                done
            fi
            if [ "$dependency_mode" -eq 1 ]; then
                # All also promotes already checked dependencies to explicit.
                for i in "${touched[@]}"; do
                    if [ "${selected[i]}" -eq 1 ]; then
                        explicit[i]=1
                    else picker_deselect_dependency "$i"; fi
                done
                picker_resolve_dependencies
                for ((i = 0; i < ${#selected[@]}; i++)); do
                    if [ "${before[i]}" -eq 1 ] && [ "${selected[i]}" -eq 0 ] && [ "${REPO_ITEM_GROUPS[i]}" = mattpocock/skills ]; then
                        notice+="Deselected "$'\033[32m'"${REPO_ITEM_LABELS[i]}"$'\033[0m'". "
                    fi
                done
            fi
            ;;
        '')
            if [ "$child" -ge 0 ]; then
                child=-1
                cursor="${MENU_CURSORS[page]}"
            elif [ "$cursor" -eq "${#groups[@]}" ]; then
                return 0
            else
                child="$cursor"
                key_page=$((100 + page * 100 + child))
                cursor="${MENU_CURSORS[key_page]:-0}"
            fi
            ;;
        c) return 0 ;;
        b | B | $'\e')
            if [ "$child" -ge 0 ]; then
                child=-1
                cursor="${MENU_CURSORS[page]}"
            else return 2; fi
            ;;
        q | Q) return 1 ;;
        esac
    done
}
