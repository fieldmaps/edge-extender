class TopoTools < Formula
  include Language::Python::Virtualenv

  desc "DuckDB-powered geospatial topology utilities"
  homepage "https://github.com/OCHA-DAP/topo-tools-py"
  url "https://files.pythonhosted.org/packages/eb/cc/53739d47cddcffe6abaa12040b1930eadd9cee47850297c1d2e875966b29/topo_tools-0.5.3.tar.gz"
  sha256 "989f95a7fc276d725085f58fe91f9dc5912b368511066744c3c090aed18a9d7a"
  license "MIT"

  depends_on "cmake" => :build
  depends_on "ninja" => :build
  depends_on "libyaml"
  depends_on "python@3.14"

  resource "hatchling" do
    url "https://files.pythonhosted.org/packages/69/08/33331757185504aae48b8d9bd78cec03a76e3aecfb52e549d05a2347c0dd/hatchling-1.32.0.tar.gz"
    sha256 "0bdbde4a52b06c37e3eca395f85a762bf0ef06fe374fd8ae429dc6be10230f5f"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/c7/0e/7fa0ef50764b67090eca4114772a2abf8b6148198475e54c660b97caeee6/click-8.5.0.tar.gz"
    sha256 "ba0d2089de75ea0310e2dde03160e6ca10009947fb95a182f9b54021bb272e34"
  end

  resource "duckdb" do
    url "https://files.pythonhosted.org/packages/7d/19/e57151753576373c6696a12022648546cca6038e8833fda2908ee2342d9b/duckdb-1.5.5.tar.gz"
    sha256 "72f33ee57ca7595b23957671a2cc7f7fe2be0ecc2d68f63abedcfcaa3a5c1238"
  end

  resource "psutil" do
    url "https://files.pythonhosted.org/packages/aa/c6/d1ddf4abb55e93cebc4f2ed8b5d6dbad109ecb8d63748dd2b20ab5e57ebe/psutil-7.2.2.tar.gz"
    sha256 "0746f5f8d406af344fd547f1c8daa5f5c33dbc293bb8d6a16d80b4bb88f59372"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Usage", shell_output("#{bin}/topo-tools --help")
  end
end
