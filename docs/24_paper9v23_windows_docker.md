# Paper9v2.3 Windows Docker 离线部署

## 1. 交付结论

内网允许 Docker 后，优先使用以下镜像：

```text
paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64
platform: linux/amd64
package: 0.4.0
algorithm: paper9v2 2.3.0
profile: dltb_dem_only
```

`legacy-amd64` 不要求现场 CPU 暴露完整 x86-64-v2 指令集，兼容既有现场机器缺少
`sse4_1` 或 `popcnt` 的情况。Windows 使用 Docker Desktop 的 Linux containers 模式运行。
容器始终使用 `--network none`，现场运行不访问互联网。

镜像包含 Paper9 源码、Python/GDAL/PyTorch/ONNX 运行时、配置和测试。DLTB、DEM、行政参考和
运行输出位于镜像外，通过只读或读写 bind mount 提供，便于独立校验数据哈希并避免重复镜像层。

## 2. 本机构建

已有 v2.2.3 legacy 镜像时，可以复用其依赖层快速构建：

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  --build-arg BASE_IMAGE=paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64 \
  --build-arg REUSE_INSTALLED_DEPS=1 \
  --build-arg PACKAGE_VERSION=0.4.0 \
  --build-arg ALGORITHM_VERSION=2.3.0 \
  --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
  --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64 .
```

没有旧镜像时，使用 `python:3.11-bookworm` 并重新安装锁定的 legacy 依赖：

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  --build-arg LEGACY_X86_64=1 \
  --build-arg PACKAGE_VERSION=0.4.0 \
  --build-arg ALGORITHM_VERSION=2.3.0 \
  -t paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64 .
```

## 3. 本机验证和导出

真实东兴数据的缩小参数端到端验证：

```bash
./scripts/smoke_paper9v23_container.sh \
  --image paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64 \
  --data-root /tmp/paper9-v23-container-smoke
```

该脚本依次执行环境检查、完整 pytest、v2.3 配置检查、真实 DLTB+DEM 融合、`prepare`、
`sample`、`train`、`plan` 和 `audit`。smoke 使用 100 条 transition、2 个 pairwise state x
5 个动作、1 个模型 x 1 epoch；它用于验证容器功能，不替代正式默认参数验收。

导出镜像：

```bash
docker save \
  -o dist/paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar \
  paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64
```

将镜像、内置样例、DEM、行政参考和 Windows PowerShell 启动器组装成单一离线包：

```bash
./deploy/container-runtime/package-paper9v23-image-bundle.sh \
  --image-tar dist/paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar \
  --git-commit "$(git rev-parse HEAD)"
```

## 4. Windows Docker Desktop 验证

要求：Windows x64、Docker Desktop、Linux containers 模式、至少 16 GB 内存和 20 GB 可用磁盘。
自治区级 DLTB 建议 32 GB 内存。将离线包解压到短路径，例如：

```text
D:\paper9_v23_docker
```

在 Windows PowerShell 5.1 或更高版本执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd D:\paper9_v23_docker

docker load -i .\images\paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar
docker image inspect paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64

.\bin\run-paper9v23-docker.ps1 check -Dataset dongxing
```

先跑缩小参数的完整东兴 smoke：

```powershell
.\bin\run-paper9v23-docker.ps1 all `
  -Dataset dongxing `
  -Config configs/paper9v23_dongxing_container_smoke.yml `
  -DataRoot D:\paper9-data\dongxing-smoke
```

再根据时间和机器资源运行东兴默认正式参数：

```powershell
.\bin\run-paper9v23-docker.ps1 all `
  -Dataset dongxing `
  -DataRoot D:\paper9-data\dongxing-full
```

璧山区使用：

```powershell
.\bin\run-paper9v23-docker.ps1 all `
  -Dataset bishan `
  -DataRoot D:\paper9-data\bishan
```

## 5. 中宁县现场 DLTB

将完整 FileGDB 目录放在 Docker Desktop 已共享的本地磁盘，例如
`E:\宁夏数据\2025DLTB.gdb`，然后执行：

```powershell
.\bin\run-paper9v23-docker.ps1 all `
  -Dataset zhongning `
  -DltbSource "E:\宁夏数据\2025DLTB.gdb" `
  -DataRoot D:\paper9-data\zhongning
```

如果 FileGDB 中存在多个候选面图层，增加 `-DltbLayer "实际图层名"`。输入路径必须是完整
`.gdb` 目录，不接受单个内部文件、压缩包或 GeoPackage。

至少保留以下证据：

- `<DataRoot>\input\fusion_report.json`；
- `<DataRoot>\input\input_availability.json`；
- `<DataRoot>\outputs\logs\`；
- `<DataRoot>\outputs\audit_summary.json`。

本模式不评估 PDT、生态保护红线或永久基本农田，`regulatory_compliance_claim_allowed` 必须为
`false`。结果只能用于探索性技术验证，不能形成自然资源合规结论。
