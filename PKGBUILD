# Maintainer: Your Name <user@archlinux.org>

pkgname=apt-pac
pkgver=0.1.0
pkgrel=1
pkgdesc="An APT-style wrapper for pacman with beautiful output"
arch=('any')
url="https://github.com/user/apt-pac"
license=('MIT')
depends=('python' 'python-rich' 'pacman-contrib')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver::git+https://github.com/user/apt-pac.git") # Placeholder
sha256sums=('SKIP')

build() {
  cd "$srcdir/$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
}
