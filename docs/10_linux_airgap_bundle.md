# 10 Linux 纯离线运行包

当前仓库是 Paper9 离线源码包和运行配置，不是已经包含 Linux Python/GDAL/Torch
运行时的“拷贝即运行包”。如果自然资源部新 Linux 机器没有任何 Python、conda、GDAL
环境且不能联网，不能只拷贝当前仓库目录后直接运行。

要做到拷贝后可运行，需要额外制作 Linux 同架构运行时包。推荐使用 `conda-pack`
或等价方式生成完整 Python 环境归档。

## 必须随包携带的内容

面向完全断网 Linux 的交付包至少应包含：

| 内容 | 说明 |
| --- | --- |
| Paper9 源码包 | 本仓库的 `src/`、`scripts/`、`configs/`、`docs/`、`pyproject.toml`、`environment.yml`。 |
| Linux Python 运行时 | Python 3.11，以及 GeoPandas、Rasterio、Fiona、PyProj、GDAL、PROJ、GEOS、PyTorch、ONNX、ONNX Runtime 等 native 依赖。 |
| 启动脚本 | 激活环境、执行 `00_check_env.py`、`check-config`、`run_full_pipeline.py`。 |
| 客户数据 | `data/input/DLTB_with_authority_slope.gpkg`、`data/input/admin_units.gpkg` 和 `DEM_placeholder.tif`。 |
| 配置文件 | 至少包含一份按真实 CRS、字段名和输出目录修改后的 `configs/*.yml`。 |

macOS 上创建的 conda 环境不能直接拷贝到 Linux 使用；必须在 Linux x86_64 或与目标
机器一致的 Linux 架构上制作运行时包。

## 推荐打包方式：conda-pack

在有网络的 Linux 制包机上执行，制包机应尽量与目标内网 Linux 机器同 CPU 架构、
同 glibc/OS 大版本。

```bash
git clone <repo-url> paper9-mnr-offline-package
cd paper9-mnr-offline-package

conda env create -f environment.yml
conda activate paper9-mnr-offline
python -m pip install -e .

python scripts/00_check_env.py
python -m pytest tests -q

conda install -c conda-forge conda-pack
conda-pack -n paper9-mnr-offline -o dist/paper9-mnr-linux-x86_64-env.tar.gz
```

然后组装交付目录：

```text
paper9-mnr-linux-bundle/
  env/paper9-mnr-linux-x86_64-env.tar.gz
  paper9-mnr-offline-package/
  install_linux_airgap.sh
  run_check.sh
  run_full.sh
```

## 目标内网机器安装

在目标 Linux 机器上解压：

```bash
tar -xzf paper9-mnr-linux-bundle.tar.gz
cd paper9-mnr-linux-bundle
mkdir -p runtime/env
tar -xzf env/paper9-mnr-linux-x86_64-env.tar.gz -C runtime/env
runtime/env/bin/conda-unpack
```

运行环境检查：

```bash
runtime/env/bin/python paper9-mnr-offline-package/scripts/00_check_env.py --no-heavy
runtime/env/bin/python paper9-mnr-offline-package/scripts/00_check_env.py
runtime/env/bin/python -m pytest paper9-mnr-offline-package/tests -q
```

放入客户数据后运行：

```bash
cd paper9-mnr-offline-package
../runtime/env/bin/python -m paper9_mnr.cli check-config configs/real_data_from_authority_slope.yml
../runtime/env/bin/python scripts/run_full_pipeline.py configs/real_data_from_authority_slope.yml --dry-run
../runtime/env/bin/python scripts/run_full_pipeline.py configs/real_data_from_authority_slope.yml
../runtime/env/bin/python scripts/05_audit.py configs/real_data_from_authority_slope.yml --write
```

## 不推荐只依赖 wheelhouse

`wheelhouse/` 只适合存放纯 Python 或已验证兼容的 wheel。Paper9 依赖 GIS 和深度学习
native 库，纯 pip wheel 在完全空白 Linux 上容易遇到 GDAL/PROJ/GEOS、libstdc++、
OpenMP、Torch/ONNX Runtime ABI 不一致问题。

如果必须使用 wheelhouse，也应在同版本 Linux、同 Python 版本、同 CPU 架构上完整
验证：

```bash
python scripts/00_check_env.py
python -m pytest tests -q
python scripts/run_full_pipeline.py configs/real_data_from_authority_slope.yml --dry-run
```

## 交付前验收条件

只有同时满足以下条件，才能称为“拷贝到无网 Linux 后可运行”：

- 交付包中包含 Linux 运行时归档，不依赖目标机器已有 Python/conda。
- 在目标 Linux 或等价离线测试机上完成解压、`conda-unpack` 和环境检查。
- `python scripts/00_check_env.py` 通过。
- `python -m pytest tests -q` 通过。
- 使用真实或代理输入数据完成至少一次 `run_full_pipeline.py --dry-run`。
- 正式数据到位后，`scripts/05_audit.py <config> --write` 能确认关键输出存在。
