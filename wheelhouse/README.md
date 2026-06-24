# Offline Wheelhouse

Put intranet-approved wheel files here before installing with pip:

```powershell
python -m pip install --no-index --find-links=wheelhouse -e .
```

For GIS dependencies on Windows, prefer a conda-forge mirror or a packed conda
environment because GDAL, PROJ, GEOS, Fiona, Rasterio, and PyTorch DLLs must be
ABI-compatible. Use pip wheels only after they have been tested on the same
Windows and Python version used in the intranet.

