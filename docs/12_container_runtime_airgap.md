# 12 离线安装容器运行时

本文面向一种折中部署场景：自然资源部目标 Linux 机器没有 Docker/Podman，但允许离线
安装容器运行时。此时不用改 Paper9 算法包，也不用在目标机器上安装 Python/GDAL/Torch；
只需要先离线安装 Docker 或 Podman，再 `docker load`/`podman load` Paper9 镜像 tar。

容器运行时安装完成后，Paper9 镜像的双模式使用步骤见
`docs/14_dual_mode_image_usage.md`。

## 当前客户机器适用性

客户当前提供的机器均为 `deepin server 16`、`x86_64`。系统信息包含：

```text
ID_LIKE="rhel fedora centos deepin"
CENTOS_MANTISBT_PROJECT_VERSION="7"
```

因此，Paper9 镜像选择 `linux/amd64`。2026-07-01 现场 `lscpu` 输出显示目标机
缺少 `sse4_1` 和 `popcnt`，不满足 x86-64-v2；必须使用 `legacy-amd64` 包。
如果目标机器已经有 Docker，直接使用
`paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz` 中的镜像和运行脚本即可。
Paper9v2.1 正式镜像引用为 `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64`；其他 ARM
服务器按需使用 `paper9-mnr-offline:paper9v2-2.1.0-arm64`。

前期截图中至少有一台机器能找到 `/usr/bin/docker`，另有机器未找到 Docker/Podman。现在客户已
确认允许 Docker 后，如果现场机器仍没有 Docker，需要先准备 deepin server 16/CentOS 7
兼容的 x86_64 Docker 离线安装包及其全部依赖，再按本文安装。不要使用 arm64 包，也不要把
Ubuntu/openEuler/Kylin 等其他发行版的包直接混用到 deepin server 16。

## 交付物结构

按目标 CPU 架构和 Linux 发行版分别准备交付包。例如：

```text
paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
paper9-mnr-container-runtime-paper9v2-2.0.0-arm64.tar.gz
```

解压后建议包含：

```text
paper9-mnr-offline-container-legacy-amd64-20260701/
  images/
    paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
  runtime-packages/
    *.rpm 或 *.deb
  bin/
    install-container-runtime.sh
    run-paper9-container.sh
  docs/
    12_container_runtime_airgap.md
  README.txt
```

`runtime-packages/` 必须是目标 Linux 发行版、版本和 CPU 架构对应的 Docker 或 Podman
离线安装包，并包含全部依赖。不能把 Rocky/CentOS 的 RPM 直接拿到 Ubuntu 上用，也
不能把 amd64 包拿到 arm64 机器上用。

## 在本机组装交付包

已有 Paper9 镜像 tar 后，等拿到目标系统对应的容器运行时 RPM/DEB 包，执行：

```bash
deploy/container-runtime/package-container-runtime-bundle.sh \
  --arch amd64 \
  --image-tar dist/paper9-mnr-offline-paper9v2-2.0.0-linux-amd64.tar \
  --runtime-packages-dir /path/to/docker-or-podman-packages \
  --out dist/paper9-mnr-container-runtime-paper9v2-2.0.0-amd64.tar.gz
```

arm64 改为：

```bash
deploy/container-runtime/package-container-runtime-bundle.sh \
  --arch arm64 \
  --image-tar dist/paper9-mnr-offline-paper9v2-2.0.0-linux-arm64.tar \
  --runtime-packages-dir /path/to/docker-or-podman-packages \
  --out dist/paper9-mnr-container-runtime-paper9v2-2.0.0-arm64.tar.gz
```

## 目标内网机器安装容器运行时

解压交付包：

```bash
tar -xzf paper9-mnr-container-runtime-paper9v2-2.0.0-amd64.tar.gz
cd paper9-mnr-container-runtime-paper9v2-2.0.0-amd64
```

安装 Docker：

```bash
sudo ./bin/install-container-runtime.sh \
  --runtime docker \
  --packages-dir runtime-packages
```

如果交付的是 Podman 包：

```bash
sudo ./bin/install-container-runtime.sh \
  --runtime podman \
  --packages-dir runtime-packages
```

脚本只安装本地包，不连接网络。RPM 系统会优先使用 `dnf --disablerepo='*'` 或
`yum --disablerepo='*'`；DEB 系统会使用本地 `.deb` 包和 `apt-get --no-download`。

## 放置客户数据

准备数据目录：

```bash
sudo mkdir -p /data/paper9/input /data/paper9/working /data/paper9/outputs
sudo chown -R "$USER":"$USER" /data/paper9
```

放入客户数据：

```text
/data/paper9/input/DLTB_with_authority_slope.gpkg
/data/paper9/input/admin_units.gpkg
/data/paper9/input/DEM_placeholder.tif
```

`DEM_placeholder.tif` 是接口占位文件；业务输入仍是 DLTB 和行政区两类数据。

## 加载镜像并运行

以 amd64 + Docker 为例：

```bash
./bin/run-paper9-container.sh check \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --image-tar images/paper9-mnr-offline-paper9v2-2.0.0-linux-amd64.tar

./bin/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml

./bin/run-paper9-container.sh run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml

./bin/run-paper9-container.sh audit \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml
```

Podman 时把 `--runtime docker` 改成 `--runtime podman`。
`run` 会在 `prepare -> sample -> train -> plan` 后自动执行 `audit`，只有耕地面积不减少、
平均坡度降低、连片度上升三项硬门禁全部通过才返回成功；单独的 `audit` 动作用于复核既有产物。
`--image-ref` 是 Paper9v2 正式发布镜像引用。`--image paper9-mnr-offline --arch amd64`
仍保留给 v1 和历史包兼容使用；Paper9v2 发布、验收和现场运行应显式使用完整
`paper9-mnr-offline:paper9v2-2.0.0-{amd64,arm64}` 引用。

如需启动 Notebook 扩展模式：

```bash
./bin/run-paper9-container.sh notebook \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --notebook-port 8888 \
  --notebook-token paper9
```

Notebook 模式使用同样的数据挂载，交互地图写到 `/data/paper9/outputs/notebook/`，流程日志写到
`/data/paper9/outputs/logs/`。

如果目标机启用了 SELinux 且 Podman/Docker 挂载目录被拒绝访问，可追加：

```bash
--volume-suffix ,Z
```

## 验收标准

- `install-container-runtime.sh` 成功输出 Docker/Podman 版本或 `podman info`。
- `run-paper9-container.sh check` 通过环境检查、测试和配置检查。
- `run-paper9-container.sh dry-run` 打印的 prepare 命令包含 `--reference-layer`。
- `run-paper9-container.sh dry-run` 打印的 sample 和 plan 命令均包含 `--cultivated-area-floor-delta-ha 0`。
- `run-paper9-container.sh run` 生成 `outputs/plan_paper9v2_no_net_loss/DLTB_optimized.shp`，
  写出 `outputs/audit_summary.json`，并通过 Paper9v2 三项硬门禁。
- `run-paper9-container.sh audit` 可对既有产物重复执行同一套审计。
- `outputs/logs/` 中存在 run manifest 和各阶段日志。

## 仍需客户确认的信息

打包实际容器运行时安装包前，需要自然资源部确认：

- Linux 发行版和版本：当前已知是 `deepin server 16`，但仍需客户确认现场三台机器版本是否一致。
- CPU 架构：当前已知是 `x86_64`，对应 `amd64`。
- 是否所有机器都已安装 Docker；未安装的机器需要提供 deepin/CentOS7 兼容 Docker 离线包。
- 是否允许启动 Docker 服务并把当前用户加入可运行 Docker 的权限组。
- 是否启用 SELinux、AppArmor 或其他主机安全策略。
