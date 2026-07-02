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

2026-07-01 现场日志显示，目标 `x86_64` CPU flags 缺少 `sse4_1` 和 `popcnt`，
不满足 x86-64-v2；旧 `paper9v2-2.0.0-amd64` 镜像中的 NumPy 因 `X86_V2`
baseline 在 `prepare` 阶段导入失败。因此，面向这批机器的默认交付物更新为
`legacy-amd64`：

```text
dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
```

解包后默认加载：

```text
images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
```

`arm64` 包仍保留给其他 ARM 服务器使用，但不是这三台 deepin x86_64 机器的默认包。

## Paper9v2 发布基线

当前部署使用 Paper9v2 业务约束版，默认配置为：

```text
configs/paper9v2_no_net_loss_authority_slope.yml
```

发布和验收命令应显式使用不可变镜像引用，不使用历史 `paper9-mnr-offline:amd64` /
`paper9-mnr-offline:arm64` 作为 Paper9v2 口径：

| 项 | amd64 | arm64 |
| --- | --- | --- |
| 镜像引用 | `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64` | `paper9-mnr-offline:paper9v2-2.1.0-arm64` |
| 镜像 tar | `images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar` | `images/paper9-mnr-offline-paper9v2-2.1.0-linux-arm64.tar` |
| 容器运行时整包 | `paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz` | 后续按需生成 |
| 目标场景 | 当前 deepin x86_64 现场默认，兼容缺少 `sse4_1`/`popcnt` 的 legacy-amd64 主机 | 其他 ARM 服务器 |

镜像标签应包含以下元数据，运行报告和 run manifest 也应记录同一口径：

| 元数据 | 当前值 |
| --- | --- |
| Python 包版本 | `0.2.1` |
| 算法名 | `paper9v2` |
| 算法版本 | `2.1.0` |
| 当前 amd64 导出镜像 revision | `1b94698-dirty` |
| 当前 GitHub 最新源码提交 | `86f57153771d789b7756f6f1d7c956b09278e9eb` |
| 默认配置 | `configs/paper9v2_no_net_loss_authority_slope.yml` |

Paper9v2 的 audit hard gate：

- 县域范围内耕地总面积不减少：`cultivated_area_change_ha >= 0`。
- 耕地平均坡度降低：`slope_change_pct < 0`。
- 连片度上升：`cont_change > 0`。
- 百亩方数量和面积需要报告并尽量提升，但默认不是 hard gate。

当前 `paper9v2.1 legacy-amd64` 候选包验证报告见
`docs/reports/paper9v21_legacy_amd64_e2e_20260701/REPORT.md`。本次已完成真实数据
`prepare -> sample -> train -> plan -> audit` 全流程：

| 环境 | run_id | 镜像 | 总用时 | audit 结果 | 关键业务结果 |
| --- | --- | --- | ---: | --- | --- |
| 本机 Docker `linux/amd64` | `20260701-123848` | `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64` | 6771.457s | 通过 | 耕地 +446.199 ha，坡度 -0.3691%，连片度 +0.0483 |
| Windows Intel Docker | 见 Windows 提交配置 | `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64` | 见 Windows 运行日志 | 已完成测试 | 从 GitHub 源码重新构建并测试 |

说明：2026-06-27 的 Paper9v2.0 arm64 双数据集报告仍保留在
`docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md`，作为历史基线；
当前自然资源部 x86_64 现场继续测试应以 v2.1 legacy-amd64 包为准。

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
  --platform linux/amd64 \
  --build-arg LEGACY_X86_64=1 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1,host.docker.internal \
  --load \
  -t paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 .

docker buildx build \
  --platform linux/arm64 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.1.0-arm64 .
```

如果当前网络不需要代理，可以删除 `--build-arg HTTP_PROXY/HTTPS_PROXY/NO_PROXY`。
`legacy-amd64` 构建必须保留 `--build-arg LEGACY_X86_64=1`，这样 Dockerfile 会走
`constraints/legacy-x86_64.txt`，固定 NumPy/PyTorch/GIS/CLI 依赖到老 x86_64 CPU
兼容组合。

如果 Docker Hub 或本机 registry mirror 在解析基础镜像时失败，可以临时指定可访问的
基础镜像源；默认仍是 `python:3.11-bookworm`：

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg LEGACY_X86_64=1 \
  --build-arg BASE_IMAGE=hub.rat.dev/library/python:3.11-bookworm \
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 .
```

### Windows Intel 全新构建

你的 Windows Intel 机器可以从 GitHub pull 源码后重新构建镜像，不需要拷贝本机生成的
`.tar` 镜像文件。前提是 Docker Desktop 使用 Linux containers，并且 build 阶段能访问
Docker Hub、PyPI 和 PyTorch CPU wheel 源。

PowerShell 示例：

```powershell
git clone https://github.com/zhouning/paper9-mnr-offline-package.git
cd paper9-mnr-offline-package

docker buildx build `
  --platform linux/amd64 `
  --build-arg LEGACY_X86_64=1 `
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 `
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 `
  --build-arg NO_PROXY=localhost,127.0.0.1,host.docker.internal `
  --load `
  -t paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 .

docker run --rm --platform linux/amd64 `
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 `
  python scripts/check_legacy_cpu_compat.py --require-legacy-amd64

docker run --rm --platform linux/amd64 `
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 `
  python -m pytest tests -q
```

如果代理不在 Windows 本机，或 Docker Desktop 无法通过 `host.docker.internal:7897`
访问代理，需要把 `HTTP_PROXY/HTTPS_PROXY` 改成 Docker build 容器可访问的代理地址。
完整端到端运行建议在 WSL2 或 Git Bash 中执行，因为 `deploy/container-runtime/*.sh`
和若干验收命令按 POSIX shell 编写；仅构建镜像时 PowerShell 可以直接使用上面的命令。

## 本机容器验证

以当前 `legacy-amd64` 为例：

```bash
docker run --rm --platform linux/amd64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python scripts/00_check_env.py

docker run --rm --platform linux/amd64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python -m pytest tests -q

docker run --rm --platform linux/amd64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml --dry-run
```

完整 smoke 验证：

```bash
docker run --rm --platform linux/amd64 \
  -v "$PWD/data/input:/app/data/input:ro" \
  -v "$PWD/data/working:/app/data/working" \
  -v "$PWD/outputs:/app/outputs" \
  paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml
```

正式 `run_full_pipeline.py` 已包含最后的 audit 阶段。若只需要复核既有成果，可单独执行
`python scripts/05_audit.py configs/paper9v2_no_net_loss_authority_slope.yml --write`。

如需验证 `arm64` 镜像，把 `--platform linux/amd64` 和镜像 tag 改为：

```text
--platform linux/arm64
paper9-mnr-offline:paper9v2-2.1.0-arm64
```

在 Apple Silicon Docker Desktop 上运行 `amd64` 会通过 QEMU 模拟，速度会明显慢于原生 `arm64`；
客户 deepin x86_64 机器上运行 `legacy-amd64` 则不需要 QEMU。

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
  paper9-mnr-offline:paper9v2-2.1.0-arm64 \
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
docker save paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  -o dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar

docker save paper9-mnr-offline:paper9v2-2.1.0-arm64 \
  -o dist/paper9-mnr-offline-paper9v2-2.1.0-linux-arm64.tar
```

把对应架构的 tar 文件交付给自然资源部。不要把客户真实数据打进镜像 tar。

当前已导出的自然资源部 x86_64 目标镜像文件：

```text
dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt
dist/MANIFEST-paper9v2-2.1.0-legacy-amd64.json
```

校验：

```bash
cd dist
shasum -a 256 -c SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt
```

当前 SHA256：

```text
7e86853d2bb7462022ef385bdde6587e452de209b149ad0341be7f41f2e7cd56  paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
0b3fcacc69291109e73a71bb248f1c308a9a683396e49e36e5c8ece754c33da1  paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
```

## 自然资源部内网加载和运行

针对当前 deepin server 16 x86_64 机器，使用 amd64 包：

```bash
tar -xzf paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
cd paper9-mnr-offline-container-legacy-amd64-20260701
shasum -a 256 -c SHA256SUMS.txt
```

如果目标 Linux 没有 `shasum`，用：

```bash
sha256sum -c SHA256SUMS.txt
```

加载镜像：

```bash
docker load -i images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
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
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

正式运行：

```bash
./bin/run-paper9-container.sh run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh audit \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

`--image-ref` 是 Paper9v2 正式发布镜像引用，建议所有发布和验收命令显式传入完整
`paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64`。`--image paper9-mnr-offline --arch amd64`
仍可用于 v1 和历史包兼容，但不作为 Paper9v2 发布口径。

如果以后换成 ARM 服务器，再使用 `arm64` 包，把 `--arch amd64` 改为 `--arch arm64`，
并把 `--image-ref` 改为 `paper9-mnr-offline:paper9v2-2.1.0-arm64`。

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
- 正式数据运行后，`run_full_pipeline.py` 的 manifest 包含 `audit` 阶段，`outputs/audit_summary.json`
  显示关键成果均存在，且 Paper9v2 硬门禁通过。
- `outputs/plan_paper9v2_no_net_loss/mpc_summary.json` 至少记录耕地面积变化、坡度变化、连片度变化、
  百亩方数量/面积变化和完成置换数；这些数值应写入现场验收报告。
- 如启用 Notebook 扩展模式，`/app/notebooks` 能打开，交互地图能写入 `outputs/notebook/`。
