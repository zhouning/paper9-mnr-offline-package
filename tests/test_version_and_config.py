import paper9_mnr
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION


def test_version_constants_define_paper9v2_release():
    assert PACKAGE_VERSION == "0.2.0"
    assert paper9_mnr.__version__ == PACKAGE_VERSION
    assert ALGORITHM_NAME == "paper9v2"
    assert ALGORITHM_VERSION == "2.0.0"
