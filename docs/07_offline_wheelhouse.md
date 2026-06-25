# 07 离线 Wheelhouse

`wheelhouse/` 用于存放经过内网审批的 Python wheel 文件。它不是自动下载目录。

注意：`wheelhouse/` 也不是完整 Linux 运行时。对于没有 Python/conda 环境且不能联网
的新 Linux 机器，优先制作 `conda-pack` 运行时包，见
`docs/10_linux_airgap_bundle.md`。

## 外网准备

在与内网同版本 Python、同操作系统的外网机器上准备：

```powershell
python -m pip download -d wheelhouse -r requirements-lock.txt
```

如果没有锁定文件，建议先在外网建立可运行 conda 环境，再导出明确版本清单。GIS 栈
不建议临时拼 wheel。

## 内网安装

```powershell
python -m pip install --no-index --find-links=wheelhouse -e .
```

这条命令要求目标机器已经有可用 Python 和 ABI 兼容的 native 依赖。GIS 和 Torch
依赖较重，完全空白 Linux 不应只依赖 wheelhouse。

如果内网使用 conda 镜像，优先：

```powershell
conda env create -f environment.yml
conda activate paper9-mnr-offline
python -m pip install --no-index --find-links=wheelhouse -e .
```

## 验收

安装后必须运行：

```powershell
python scripts\00_check_env.py
python -m pytest tests -q
```

只有这两步通过，才进入真实县域数据的 `prepare/sample/train/plan`。
