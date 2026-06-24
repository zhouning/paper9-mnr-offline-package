"""farmland_mpc: contrastive world-model + MPC for county-scale farmland consolidation.

Pure-Python entry points for data preparation, transition sampling,
contrastive ensemble training, and MPC planning. The same library backs
the standalone CLI (`farmland-mpc plan ...`) and the optional ArcGIS Pro
toolbox wrapper.
"""

import os
import sys
from pathlib import Path


def _isolate_conda_geostack() -> None:
    # On Windows + Python 3.8+, native DLLs are not resolved via PATH; we must
    # register `Library/bin` with os.add_dll_directory. We also redirect
    # GDAL/PROJ data + driver search paths to the conda env's own files,
    # otherwise stale ArcGIS Pro GDAL plugins (e.g. gdal_E57.dll, gdal_SDTS.dll)
    # are picked up, fail to load, and emit Chinese-locale error messages that
    # crash rasterio/fiona's UTF-8 log handler downstream.
    if sys.platform != "win32":
        return
    env_root = Path(sys.executable).parent
    library = env_root / "Library"
    if not library.is_dir():
        return

    if hasattr(os, "add_dll_directory"):
        for sub in ("bin", "mingw-w64/bin", "usr/bin"):
            d = library / sub
            if d.is_dir():
                try:
                    os.add_dll_directory(str(d))
                except (OSError, ValueError):
                    pass

    # Point GDAL/PROJ at the conda env's own data dirs; clear any ArcGIS Pro
    # gdalplugins path that may have been inherited from the parent process.
    proj_share = library / "share" / "proj"
    gdal_share = library / "share" / "gdal"
    gdal_plugins = library / "lib" / "gdalplugins"
    if proj_share.is_dir():
        os.environ["PROJ_LIB"] = str(proj_share)
        os.environ["PROJ_DATA"] = str(proj_share)
    if gdal_share.is_dir():
        os.environ["GDAL_DATA"] = str(gdal_share)
    if gdal_plugins.is_dir():
        os.environ["GDAL_DRIVER_PATH"] = str(gdal_plugins)
    else:
        # If conda has no gdalplugins, completely UNSET the var so GDAL falls
        # back to its built-in driver registry. Setting it to "" makes some
        # GDAL builds scan CWD; leaving an inherited ArcGIS Pro path in place
        # makes them load incompatible plugins.
        os.environ.pop("GDAL_DRIVER_PATH", None)


_isolate_conda_geostack()

__version__ = "0.2.1"
