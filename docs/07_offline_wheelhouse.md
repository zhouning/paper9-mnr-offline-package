# 07 离线 Wheelhouse

`wheelhouse/` 用于存放经过内网审批的 Python wheel 文件。它不是自动下载目录。

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

