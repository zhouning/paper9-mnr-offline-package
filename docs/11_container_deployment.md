# 11 容器化部署

本文说明如何把 Paper9 MNR 离线包制作成 Docker/OCI 容器镜像，并在自然资源部内网以
容器方式运行。容器化部署适合目标机器没有 Python/conda 环境，但允许导入和运行容器
镜像的场景。

镜像的最新双模式使用说明见 `docs/14_dual_mode_image_usage.md`。本文侧重镜像构建、
导出和基础运行命令。

## 当前自然资源部目标机器画像

客户目前提供的三台机器均按以下口径处理：

| 项 | 当前值 |
| --- | --- |
| 操作系统 | `deepin server 16` |
| 兼容信息 | `ID_LIKE="rhel fedora centos deepin"`，系统信息包含 CentOS 7 兼容标识 |
| CPU 架构 | `x86_64` |
| Paper9 镜像架构 | `linux/amd64` |
| 容器运行时策略 | 客户已重新确认允许使用 Docker |
| Podman | 未发现，可不作为默认路径 |

因此，面向这批机器的默认交付物是：

```text
dist/paper9-mnr-offline-container-amd64-20260625.tar.gz
```

解包后默认加载：

```text
images/paper9-mnr-offline-linux-amd64.tar
```

`arm64` 包仍保留给其他 ARM 服务器使用，但不是这三台 deepin x86_64 机器的默认包。

## 镜像边界

镜像包含：

- Python 3.11。
- Paper9 MNR 源码、脚本、配置模板和文档。
- GeoPandas、Rasterio、Fiona、PyProj、GDAL 相关 wheel 依赖。
- PyTorch、ONNX、ONNX Runtime。

镜像不包含：

- 自然资源部真实 DLTB 数据。
- 自然资源部真实行政区数据。
- 中间成果和最终输出。

客户数据通过 volume 挂载到容器内：

```text
/app/data/input
/app/data/working
/app/outputs
```

## 本机构建双架构镜像

Docker Desktop buildx 支持 `linux/amd64` 和 `linux/arm64` 时，可分别构建并导出：

```bash
docker buildx build \
  --platform linux/arm64 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.0.0-arm64 .

docker buildx build \
  --platform linux/amd64 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.0.0-amd64 .
```

如果当前网络不需要代理，可以删除 `--build-arg HTTP_PROXY/HTTPS_PROXY/NO_PROXY`。

如果 Docker Hub 或本机 registry mirror 在解析基础镜像时失败，可以临时指定可访问的
基础镜像源；默认仍是 `python:3.11-bookworm`：

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg BASE_IMAGE=hub.rat.dev/library/python:3.11-bookworm \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.0.0-amd64 .
```

## 本机容器验证

以 `arm64` 为例：

```bash
docker run --rm --platform linux/arm64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  python scripts/00_check_env.py

docker run --rm --platform linux/arm64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  python -m pytest tests -q

docker run --rm --platform linux/arm64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml --dry-run
```

完整 smoke 验证：

```bash
docker run --rm --platform linux/arm64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml

docker run --rm --platform linux/arm64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  python scripts/05_audit.py configs/paper9v2_no_net_loss_authority_slope.yml --write
```

`amd64` 验证时把 `--platform linux/arm64` 和镜像 tag 改为：

```text
--platform linux/amd64
paper9-mnr-offline:paper9v2-2.0.0-amd64
```

在 Apple Silicon Docker Desktop 上运行 `amd64` 会通过 QEMU 模拟，速度会明显慢于原生
`arm64`。

## Notebook 扩展模式

镜像内置 JupyterLab 和 `/app/notebooks` 模板，用于数据核查、过程解释和结果可视化。
Notebook 是扩展模式，正式运行仍建议使用命令行批处理。

本机启动：

```bash
docker run --rm --platform linux/arm64 \
  -p 8888:8888 \
  -e PAPER9_LOG_DIR=/app/outputs/logs \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  jupyter lab \
    --ip=0.0.0.0 \
    --port=8888 \
    --no-browser \
    --allow-root \
    --notebook-dir=/app/notebooks \
    --ServerApp.token=paper9
```

访问：

```text
http://127.0.0.1:8888/lab?token=paper9
```

Notebook 触发完整流程时，也会把日志写入 `outputs/logs`。

## 导出离线镜像

```bash
mkdir -p dist
docker save paper9-mnr-offline:paper9v2-2.0.0-arm64 -o dist/paper9-mnr-offline-linux-arm64.tar
docker save paper9-mnr-offline:paper9v2-2.0.0-amd64 -o dist/paper9-mnr-offline-linux-amd64.tar
```

把对应架构的 tar 文件交付给自然资源部。不要把客户真实数据打进镜像 tar。

## 自然资源部内网加载和运行

针对当前 deepin server 16 x86_64 机器，使用 amd64 包：

```bash
tar -xzf paper9-mnr-offline-container-amd64-20260625.tar.gz
cd paper9-mnr-offline-container-amd64-20260625
shasum -a 256 -c SHA256SUMS.txt
```

如果目标 Linux 没有 `shasum`，用：

```bash
sha256sum -c SHA256SUMS.txt
```

加载镜像：

```bash
docker load -i images/paper9-mnr-offline-linux-amd64.tar
```

准备目录：

```bash
mkdir -p /data/paper9/input /data/paper9/working /data/paper9/outputs
```

放入客户数据：

```text
/data/paper9/input/DLTB_with_authority_slope.gpkg
/data/paper9/input/admin_units.gpkg
/data/paper9/input/DEM_placeholder.tif
```

检查配置和打印命令：

```bash
./bin/run-paper9-container.sh check \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

正式运行：

```bash
./bin/run-paper9-container.sh run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh audit \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

`--image-ref` 是 Paper9v2 正式发布镜像引用，建议所有发布和验收命令显式传入完整
`paper9-mnr-offline:paper9v2-2.0.0-{amd64,arm64}`。`--image paper9-mnr-offline --arch amd64`
仍可用于 v1 和历史包兼容，但不作为 Paper9v2 发布口径。

如果以后换成 ARM 服务器，再使用 `arm64` 包，把 `--arch amd64` 改为 `--arch arm64`，
并把 `--image-ref` 改为 `paper9-mnr-offline:paper9v2-2.0.0-arm64`。

运行日志位于：

```text
/data/paper9/outputs/logs
```

## 验收标准

- 容器内 `python scripts/00_check_env.py` 通过。
- 容器内 `python -m pytest tests -q` 通过。
- `run_full_pipeline.py --dry-run` 中 prepare 命令包含 `--reference-layer`。
- `run_full_pipeline.py --dry-run` 中 sample 和 plan 命令均包含 `--cultivated-area-floor-delta-ha 0`。
- 使用 Paper9v2 配置完成至少一次 `configs/paper9v2_no_net_loss_authority_slope.yml` 完整 smoke。
- 正式数据运行后，`scripts/05_audit.py <config> --write` 显示关键成果均存在。
- 如启用 Notebook 扩展模式，`/app/notebooks` 能打开，交互地图能写入 `outputs/notebook/`。
