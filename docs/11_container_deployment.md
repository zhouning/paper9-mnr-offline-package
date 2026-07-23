# Paper9v2.2.2 容器构建与离线交付

## 目标

当前客户机器为 deepin server 16、`x86_64`，现场 CPU 缺少 `sse4_1` 和 `popcnt`，
因此正式镜像使用兼容旧 CPU 的 `legacy-amd64` 依赖约束：

```text
paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64
```

镜像包含 Python、GDAL/OpenFileGDB、GeoPandas、Rasterio、Paper9 代码、配置、测试和
JupyterLab，不包含 ArcPy。客户四个真实 GDB 不写入镜像。覆盖东兴区和璧山区的三个
Copernicus DEM GLO-30 瓦片随离线部署包交付，放在镜像外，便于核验来源和哈希。

## 构建镜像

在仓库根目录执行：

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg LEGACY_X86_64=1 \
  --build-arg PACKAGE_VERSION=0.3.2 \
  --build-arg ALGORITHM_NAME=paper9v2 \
  --build-arg ALGORITHM_VERSION=2.2.2 \
  --build-arg GIT_COMMIT="$(git rev-parse --short HEAD)-dirty" \
  --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --load \
  -t paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 .
```

如本机已有经过验证的上一补丁镜像，且 `pyproject.toml` 与约束文件确认没有新增或升级第三方
依赖，可复用其已安装依赖，仅重装当前项目源码：

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg BASE_IMAGE=paper9-mnr-offline:paper9v2-2.2.1-legacy-amd64 \
  --build-arg REUSE_INSTALLED_DEPS=1 \
  --build-arg LEGACY_X86_64=1 \
  --build-arg PACKAGE_VERSION=0.3.2 \
  --build-arg ALGORITHM_VERSION=2.2.2 \
  --load \
  -t paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 .
```

该路径仍会重新复制源码、配置、测试、文档和参考数据，并在镜像构建阶段执行环境检查与
legacy CPU 检查；只有依赖安装层复用。若依赖约束发生变化，不得使用此参数。

如果构建机需要代理，只向构建命令增加客户批准的 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`
参数。运行时统一 `--network none`，不得依赖代理或公网。

## 镜像验证

```bash
docker run --rm --platform linux/amd64 --network none \
  paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  python -m pytest tests -q

docker run --rm --platform linux/amd64 --network none \
  paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  python scripts/check_legacy_cpu_compat.py --require-legacy-amd64

docker run --rm --platform linux/amd64 --network none \
  paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  python -c "import pyogrio; print(pyogrio.list_drivers()['OpenFileGDB'])"

docker run --rm --platform linux/amd64 --network none \
  paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  python -c "import importlib.util; assert importlib.util.find_spec('arcpy') is None"
```

OpenFileGDB 驱动应至少包含 `r`；当前构建预期为 `rw`。legacy 检查必须报告
`legacy_amd64_safe=True`。

## 导出镜像

```bash
docker save paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  -o dist/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar
```

不要覆盖 `2.2.0` 的 tar、manifest 或校验文件。

## 生成轻量交付包

DEM 目录必须包含三个 `.tif` 和 `DEM_MANIFEST.json`。打包脚本缺少这些内容时会失败：

```bash
./deploy/container-runtime/package-lightweight-container-bundle.sh \
  --arch amd64 \
  --image-tar dist/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar \
  --image-ref paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64 \
  --dem-dir dist/dem/copernicus_glo30 \
  --package-version 0.3.2 \
  --algorithm-name paper9v2 \
  --algorithm-version 2.2.2 \
  --out dist/paper9-mnr-offline-container-paper9v2-2.2.2-legacy-amd64.tar.gz
```

如果客户机器还没有 Docker/Podman，使用
`package-container-runtime-bundle.sh` 并额外传入与 deepin 版本、CPU 架构严格匹配的
`--runtime-packages-dir`。不能把 Rocky/CentOS 的 RPM 直接拿到 Ubuntu 或 deepin 使用。

## 归档验收

1. 计算独立镜像 tar 和轻量包的 SHA-256，写入外部 manifest。
2. 解压轻量包到临时目录。
3. 在解压根目录运行 `sha256sum -c SHA256SUMS.txt`。
4. 检查 `MANIFEST.json` 中版本、镜像引用、DEM 路径和 CPU 兼容说明。
5. 校验 `dem/copernicus_glo30/DEM_MANIFEST.json` 内每个瓦片的 SHA-256。
6. 从解压后的镜像 tar 执行 `docker load`，重复镜像内测试、OpenFileGDB、legacy CPU 和
   无 ArcPy 检查。
7. 用四个独立模拟 GDB 执行一次容器 `fuse`，确认 GDB/DEM 只读、input 可写、网络关闭。
8. 执行 `check` 和完整 pipeline `dry-run`。

## 客户现场入口

客户不直接拼装 `docker run`。唯一正式入口为：

```bash
./bin/run-paper9-container.sh fuse \
  --dltb-gdb /path/to/dltb.gdb \
  --pdt-gdb /path/to/pdt.gdb \
  --eco-redline-gdb /path/to/stbhhx.gdb \
  --permanent-basic-farmland-gdb /path/to/yjjbntbhtb.gdb
```

首次 `docker load` 后，以上四个 GDB 目录是唯一需要现场填写的客户数据参数。wrapper 自动
确定运行时、架构、正式镜像、包内 DEM、行政参考和隔离的 `data-root`，并在融合结束时打印
后续 `check -> dry-run -> run -> audit` 的完整命令。详细操作见 `docs/09_mnr_customer_runbook.md`。

## ARM 边界

源码保留 `arm64` 标签选择逻辑，但本次不交付 ARM 工件。只有在 ARM 服务器上重新构建、
完成同等测试并制作独立校验清单后，才能发布
`paper9-mnr-offline:paper9v2-2.2.2-arm64`。
