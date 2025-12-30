# Maintainer: Your Name <user@archlinux.org>

pkgname=apt-pac-git
_pkgname=apt-pac
pkgver=2026.01.01
pkgrel=1
pkgdesc="An APT-style wrapper for pacman with APT-like output"
arch=('any')
url="https://github.com/JotaRandom/apt-pac"
license=('MIT')
depends=('python'
         'python-rich'
         'python-tomli'
         'devtools'
         'pacman-contrib')
makedepends=('python-build'
             'python-installer'
             'python-setuptools'
             'python-wheel'
             'git')
source=("$_pkgname::git+https://github.com/JotaRandom/$_pkgname.git")
sha256sums=('SKIP')

version() {
  cd "$srcdir/$_pkgname"
  git describe --tags --long
}

build() {
  cd "$srcdir/$_pkgname"
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$_pkgname"
  python -m installer --destdir="$pkgdir" dist/*.whl
  
  # Install global configuration
  install -Dm644 config.toml "$pkgdir/etc/apt-pac/config.toml"
}
