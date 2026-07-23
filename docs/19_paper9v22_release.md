# Paper9v2.2.2 发布说明

## 发布标识

| 项 | 值 |
| --- | --- |
| Python 包版本 | `0.3.2` |
| 算法 | `paper9v2 2.2.2` |
| 客户平台 | `linux/amd64`，`legacy-amd64` CPU 兼容模式 |
| 镜像 | `paper9-mnr-offline:paper9v2-2.2.2-legacy-amd64` |
| 默认配置 | `configs/paper9v22_authority_constraints.yml` |
| 独立镜像 tar | `dist/paper9-mnr-offline-paper9v2-2.2.2-legacy-linux-amd64.tar` |
| 轻量部署包 | `dist/paper9-mnr-offline-container-paper9v2-2.2.2-legacy-amd64.tar.gz` |
| 内置高程 | Copernicus DEM GLO-30 `N29E104/N29E105/N29E106` |
| 内置行政参考 | 东兴区 29 个、璧山区 15 个乡镇/街道面，源日期 2021-06-22 |
| 镜像 ID | `sha256:71b2ebed3bc2753a409dc1f48298dff2b0933120a4b121799fdb0ade397b8a7f` |
| Docker 逻辑大小 | `923205101` 字节 |
| 独立镜像 tar SHA-256 | `d73908eb3ac91e176758bc35871c6809c09e92ee5da79b22b635b5f8229d2908` |
| 轻量部署包 SHA-256 | 见包外 `dist/SHA256SUMS-paper9v2-2.2.2-legacy-amd64.txt` |

最终镜像 ID、构建时间、文件字节数和 SHA-256 以
`dist/MANIFEST-paper9v2-2.2.2-legacy-amd64.json` 与
`dist/SHA256SUMS-paper9v2-2.2.2-legacy-amd64.txt` 为准。归档内部所有文件还必须通过包内
`SHA256SUMS.txt` 校验。

## 2.2.2 修正内容

`2.2.2` 不覆盖已发布的 `2.2.1` 工件。本补丁在最终四 GDB + 内置 DEM 契约上增加行政
参考数据和完整离线诊断能力：

- 从客户提供的全国 `xiangzhen.shp` 筛出东兴区 29 条、璧山区 15 条，随包内置并自动选县。
- 行政参考只用于乡镇名称和空间归属，不参与生态红线、永久基本农田或交换约束。
- 明确 PDT 为 `quality_control_only`；不影响连续坡度、交换锁、奖励或优化结果。
- wrapper 为所有动作记录宿主机、运行时、镜像、挂载和退出状态。
- 融合器记录图层候选、字段、CRS、范围、几何修复、DEM、坡度、约束、哈希和阶段耗时。
- 失败时生成含 traceback、当次参数和完整运行库版本的诊断 JSON。
- 所有诊断集中在 `DATA_ROOT/outputs/logs/`，便于按客户制度从内网带回分析。

## 2.2.1 基础能力

`2.2.0` 已完成 ArcPy-free 融合和保护区锁定的候选验证，但它仍要求一个容器包含四图层，
且 DEM 需现场另行提供，不能满足客户最终输入条件。因此保留旧工件，不覆盖、不重新打标签，
并以 `2.2.1` 发布修正后的现场契约；这些能力由 `2.2.2` 继承。

本版主要变化：

- 每县接收四个独立 FileGDB 路径，客户不提供图层名、县名、CRS 或 DEM。
- 单面图层自动选取，多图层按名称和字段唯一识别；歧义时失败。
- 轻量离线包携带覆盖东兴区、璧山区的三个 GLO-30 COG 及完整来源/哈希清单。
- DEM 按 DLTB 县域范围裁窗后计算 Horn 连续坡度；PDT 等级只作质检。
- 自动生成 `DEM_placeholder.tif`，不再要求现场复制或伪造占位数据。
- wrapper 新增 `fuse`，四个 GDB 与 DEM 只读挂载，融合输出可写，所有动作关闭网络。
- 生态红线和永久基本农田继续使用 `EXCH_LOCK` 双向硬锁定和人工冲突复核。

## 兼容性与边界

单容器 `source` API 保留，已有开发测试可继续使用。Paper9v2.1 不读取 `EXCH_LOCK`，不得
用于本次权威保护层数据。Paper9v2.2.0 不具备最终四 GDB 与随包 DEM 的现场入口，也不得作为
本次最终交付。

仓库与构建环境没有客户真实 FileGDB，因此不能声称东兴区、璧山区真实数据 E2E 已完成。
发布验证覆盖代码、模拟四源融合、OpenFileGDB、容器、CPU 兼容、离线包完整性和 dry-run；
正式业务验收仍须在内网使用四个真实 GDB 分县执行 `fuse -> check -> dry-run -> run -> audit`。

最终候选验证结果：镜像内 `73 passed`，本次新增和修改文件通过 Ruff，OpenFileGDB=`rw`，
ArcPy 不存在，legacy CPU 基线仅要求 SSE/SSE2/SSE3，配置检查与完整 pipeline dry-run 通过。
三个 DEM 文件的字节数及 MD5 均与官方 S3 对象一致，并完成 Rasterio 全波段读取。东兴区
范围的模拟 DLTB 跨越 E104/E105 接缝，璧山区范围使用 E106；两组四独立 GDB 容器融合的
坡度空值均为零。

最终轻量包解包后，包内 `SHA256SUMS.txt` 对 67 个文件全部校验通过；直接执行包内 wrapper，
只传四个 GDB 路径且不传 `--dem-dir`、`--admin-reference`，璧山区仍自动选中随包 DEM 和
15 个行政参考面，完成融合并生成 `container-wrapper-*.log`、`authoritative_fusion-*.log`、
`authoritative_fusion-*.jsonl` 及 latest 日志。完整数值见发布 manifest。

具体现场命令见 `docs/09_mnr_customer_runbook.md`，融合算法和保护口径见
`docs/18_authoritative_filegdb_fusion.md`。
