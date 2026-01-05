#!/bin/bash

_apt_pac_completion() {
    local cur prev opts commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    commands="update upgrade dist-upgrade full-upgrade install reinstall remove purge autoremove \
              search show list depends rdepends policy madison source build-dep showsrc \
              check clean autoclean stats edit-sources config file-search changelog scripts \
              apt-mark pkgnames dotty apt-key key add-repository download moo pacman"

    opts="-h --help -v --version -y --yes --assume-yes -q --quiet --verbose -s --simulate --dry-run \
          --download-only -f --fix-broken --no-install-recommends --only-upgrade --official --aur --aur-only"

    case "${prev}" in
        install|reinstall|remove|purge|show|depends|rdepends|policy|madison|source|build-dep|showsrc|file-search|changelog|scripts|dotty|download)
            # Fallback to file completion or we could try to list packages (expensive)
            # For now, let's just use file completion for install/source, but standard completion is fine
            local installed_pkgs=$(pacman -Qq 2>/dev/null)
            local all_pkgs=$(pacman -Slq 2>/dev/null)
            
            if [[ "${prev}" == "install" || "${prev}" == "reinstall" || "${prev}" == "download" || "${prev}" == "source" || "${prev}" == "build-dep" || "${prev}" == "showsrc" || "${prev}" == "show" || "${prev}" == "depends" || "${prev}" == "rdepends" || "${prev}" == "madison" || "${prev}" == "policy" || "${prev}" == "changelog" || "${prev}" == "scripts" || "${prev}" == "dotty" ]]; then
                 COMPREPLY=( $(compgen -W "${all_pkgs}" -- ${cur}) )
            elif [[ "${prev}" == "remove" || "${prev}" == "purge" ]]; then
                 COMPREPLY=( $(compgen -W "${installed_pkgs}" -- ${cur}) )
            fi
            return 0
            ;;
        apt-mark)
            COMPREPLY=( $(compgen -W "auto manual" -- ${cur}) )
            return 0
            ;;
        apt-key|key)
            COMPREPLY=( $(compgen -W "add list del delete remove adv" -- ${cur}) )
            return 0
            ;;
        list)
            COMPREPLY=( $(compgen -W "--installed --upgradable --manual-installed --all-versions --repo" -- ${cur}) )
            return 0
            ;;
        search)
            COMPREPLY=( $(compgen -W "--aur --official" -- ${cur}) )
            return 0
            ;;
        *)
            ;;
    esac

    if [[ ${cur} == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
    fi

    COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )
}

complete -F _apt_pac_completion apt-pac
