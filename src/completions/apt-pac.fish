# apt-pac fish completion

function __fish_apt_pac_needs_command
    set cmd (commandline -opc)
    if [ (count $cmd) -eq 1 ]
        return 0
    end
    return 1
end

function __fish_apt_pac_using_command
    set cmd (commandline -opc)
    if [ (count $cmd) -gt 1 ]
        if [ $argv[1] = $cmd[2] ]
            return 0
        end
    end
    return 1
end

# Commands
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a update -d 'Update package database'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a upgrade -d 'Upgrade all installed packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a dist-upgrade -d 'Upgrade all installed packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a full-upgrade -d 'Upgrade all installed packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a install -d 'Install packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a reinstall -d 'Reinstall packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a remove -d 'Remove packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a purge -d 'Remove packages and configuration'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a autoremove -d 'Remove orphaned packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a search -d 'Search for packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a show -d 'Show package details'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a list -d 'List packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a depends -d 'Show package dependencies'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a rdepends -d 'Show reverse dependencies'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a policy -d 'Show package policy'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a madison -d 'Show available versions'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a source -d 'Download package source'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a build-dep -d 'Install build dependencies'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a showsrc -d 'Show source package info'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a check -d 'Verify database integrity'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a clean -d 'Remove cached packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a autoclean -d 'Remove old cached packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a stats -d 'Show package statistics'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a edit-sources -d 'Edit pacman.conf'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a config -d 'Display pacman configuration'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a file-search -d 'Search for file in packages'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a changelog -d 'View package changelog'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a scripts -d 'View package scripts'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a apt-mark -d 'Mark packages as auto/manual'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a pkgnames -d 'List package names'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a dotty -d 'Generate dependency graph'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a apt-key -d 'Manage GPG keys'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a add-repository -d 'Add repository info'
complete -f -c apt-pac -n '__fish_apt_pac_needs_command' -a download -d 'Download packages without installing'

# Options
complete -f -c apt-pac -s y -l yes -d 'Automatic yes to prompts'
complete -f -c apt-pac -s q -l quiet -d 'Quiet output'
complete -f -c apt-pac -l verbose -d 'Verbose output'
complete -f -c apt-pac -s s -l simulate -d 'Simulation mode'
complete -f -c apt-pac -l dry-run -d 'Simulation mode'
complete -f -c apt-pac -l download-only -d 'Download only'
complete -f -c apt-pac -s f -l fix-broken -d 'Fix broken dependencies'
complete -f -c apt-pac -l no-install-recommends -d 'Skip optional dependencies'
complete -f -c apt-pac -l only-upgrade -d 'Only upgrade installed packages'
complete -f -c apt-pac -s v -l version -d 'Show version'
complete -f -c apt-pac -s h -l help -d 'Show help'

# Arguments
complete -f -c apt-pac -n '__fish_apt_pac_using_command install' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command reinstall' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command remove' -a '(__fish_print_installed_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command purge' -a '(__fish_print_installed_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command show' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command depends' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command rdepends' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command source' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command build-dep' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command showsrc' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command madison' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command policy' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command changelog' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command scripts' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command dotty' -a '(__fish_print_packages)'
complete -f -c apt-pac -n '__fish_apt_pac_using_command download' -a '(__fish_print_packages)'

complete -f -c apt-pac -n '__fish_apt_pac_using_command apt-mark' -a 'auto manual'
complete -f -c apt-pac -n '__fish_apt_pac_using_command apt-key' -a 'add list del delete remove adv'
complete -f -c apt-pac -n '__fish_apt_pac_using_command list' -a '--installed --upgradable --manual-installed --all-versions --repo'
