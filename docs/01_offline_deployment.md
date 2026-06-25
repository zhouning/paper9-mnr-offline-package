# 01 离线部署

目标环境是不依赖 ArcGIS Pro / arcpy 的内网 Python 环境。Paper9 核心已经复制到
`src/farmland_mpc`，新增的 `src/paper9_mnr` 只负责配置校验和流程编排。

如果目标 Linux 机器没有任何 Python/conda/GDAL/Torch 环境且完全不能联网，当前仓库
目录本身不能拷贝后直接运行。必须同时交付 Linux 运行时包，例如 conda-pack 生成的
完整环境归档。具体见 `docs/10_linux_airgap_bundle.md`。

## 推荐环境

- Windows 10/11 或 Windows Server
- Python 3.11
- conda-forge 同源的 GDAL、PROJ、GEOS、Fiona、Rasterio、GeoPandas
- PyTorch、ONNX、ONNX Runtime

优先使用内网 conda 镜像或离线 conda 包。纯 pip 安装 GIS 栈时，必须确认 GDAL、
PROJ、GEOS 和 Python ABI 一致。

## 安装步骤

在外网机器准备依赖包，经过单位安全流程导入内网后，在工程根目录执行：

```powershell
conda env create -f environment.yml
conda activate paper9-mnr-offline
python -m pip install --no-index --find-links=wheelhouse -e .
```

如果内网有 conda 镜像，可以直接用镜像安装 `environment.yml` 中的 conda 依赖，
`wheelhouse` 只放 pip 侧补充包。

## 部署后检查

```powershell
python scripts\00_check_env.py --no-heavy
python scripts\00_check_env.py
python -m pytest tests -q
```

`--no-heavy` 只检查轻量包装层；完整检查会导入 GeoPandas、Rasterio、Torch 和
ONNX Runtime。

## 目录约定

- `data/input/`: 放入自然资源部提供的两类必需业务输入：
  `DLTB_with_authority_slope.gpkg` 和 `admin_units.gpkg`。如使用
  `slope.source: field`，`DEM_placeholder.tif` 只是接口占位文件。
- `data/working/`: 中间成果，包括 prepared 目录、采样数据、模型。
- `outputs/`: 规划结果、审计报告和对外汇报材料。
- `configs/`: 每次试验的配置文件，应作为可追溯记录保存。

客户侧完整运行说明见 `docs/09_mnr_customer_runbook.md`。
