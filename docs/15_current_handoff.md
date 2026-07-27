# 15 当前工作进度接续说明

更新时间：2026-07-27

本文用于关闭当前窗口后，在后续窗口继续处理 Paper9 自然资源部离线部署包。本文只记录
工程状态、验证证据和后续动作，不包含客户真实数据。

## 当前部署判断

- 客户已重新确认允许使用 Docker，因此当前主线是 Docker/OCI 离线部署包。
- 客户提供的三台机器画像：
  - 操作系统：`deepin server 16`
  - 架构：`x86_64`
  - Docker：至少一台机器上已存在 `/usr/bin/docker`，其他机器需要现场再次确认。
  - Podman：当前截图中未安装。
- 2026-07-01 现场 `lscpu` 显示这批 deepin x86_64 机器缺少 `sse4_1` 和 `popcnt`，
  不满足 x86-64-v2；默认使用 `linux/amd64` 的 `legacy-amd64` 镜像包。
- `linux/arm64` 镜像可按需另行构建，但不在当前三台机器的交付范围内。

## 当前镜像和使用方式

- 当前 Paper9v2 默认配置：`configs/paper9v22_authority_constraints.yml`
- 当前客户 deepin x86_64 现场默认镜像：`paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64`
- 当前 x86_64 独立镜像 tar：
  `dist/paper9-mnr-offline-paper9v2-2.2.3-legacy-linux-amd64.tar`
- 当前校验文件：
  `dist/SHA256SUMS-paper9v2-2.2.3-legacy-amd64.txt`
- 当前 legacy-amd64 交付镜像元数据：包版本 `0.3.3`，算法 `paper9v2 2.2.3`，
  CPU 兼容性 `legacy-x86_64-without-x86-64-v2`。镜像 ID、文件字节数和 SHA-256 以
  `dist/MANIFEST-paper9v2-2.2.3-legacy-amd64.json` 为准。
- Windows Intel 机器曾从 GitHub 源码重新构建历史 `paper9v2-2.1.0-legacy-amd64` 并完成测试，
  其隔离配置已提交为 `configs/windows_dongxing_real_docker_e2e.yml`
- 现场运行脚本：`deploy/container-runtime/run-paper9-container.sh`
- 推荐现场顺序：
  1. `fuse`，客户只传四个 GDB 路径，DEM 和行政参考自动使用包内默认资源
  2. `check`
  3. `dry-run`
  4. `run`
  5. 查看 `outputs/audit_summary.json`
  6. 如需复核既有产物，再单独执行 `audit`
  7. 如需解释和可视化，再启动 `notebook`

详细命令以以下文档为准：

- `docs/09_mnr_customer_runbook.md`
- `docs/11_container_deployment.md`
- `docs/13_notebook_and_logs.md`
- `docs/14_dual_mode_image_usage.md`

## 当前候选包验证口径

Paper9v2.2 使用配置：

```text
configs/paper9v22_authority_constraints.yml
```

本版新增 FileGDB 融合、本地 DEM 坡度计算、生态保护红线和永久基本农田双向锁定。
代码与镜像验证不等于客户真实数据 E2E；仓库当前缺少东兴区、璧山区客户真实 FileGDB，
因此不能宣称本版已经完成两县正式端到端验收。

v2.2.2 在 v2.2.1 验证基础上增加 44 个包内乡镇参考面、PDT 非驱动角色声明，以及宿主机、
融合阶段、JSONL 事件和失败 traceback 诊断。最终镜像内 `73 passed`，本次新增和修改文件
通过 Ruff，OpenFileGDB 驱动为 `rw`，ArcPy 不存在，legacy CPU 兼容检查、默认配置检查和
完整流程 dry-run 均通过。

v2.2.3 修正真实权威数据暴露的两个问题：统一支持 `0101/0102/0103`、`0301-0307` 等现行
四位地类编码，并在混码或识别不到耕地/林地时失败；融合后在宿主机生成
`DATA_ROOT/FUSION_OUTPUTS.txt`，逐一列出六个融合文件的绝对路径、字节数和 SHA-256。

三个 GLO-30 瓦片的字节数与 S3 `Content-Length` 一致，MD5 与对象 `ETag` 一致，SHA-256、
CRS、范围、分辨率及栅格可读性均已写入 `DEM_MANIFEST.json`。另在东兴区、璧山区范围内
分别用四个独立模拟 OpenFileGDB 和真实随包 DEM 完成容器 `fuse`；东兴样本跨 E104/E105
接缝，两组 `slope.null_count` 均为 `0`，县区推断、双向锁定和人工复核标记正确。最终轻量
包内 67 个文件的 SHA-256 全部通过；从解包后的 wrapper 只传四个 GDB、不传 DEM 和行政
参考路径，璧山区仍自动选中 15 个行政面并成功完成融合。

2.2.2 独立镜像 tar 为 `923243008` 字节，SHA-256 为
`d73908eb3ac91e176758bc35871c6809c09e92ee5da79b22b635b5f8229d2908`。轻量包因包含本发布
文档，不在包内硬编码自身 SHA；最终字节数和 SHA-256 见包外
`dist/MANIFEST-paper9v2-2.2.2-legacy-amd64.json` 与
`dist/SHA256SUMS-paper9v2-2.2.2-legacy-amd64.txt`。

Paper9v2 的 hard gate 为：

- 县域耕地总面积不减少：`cultivated_area_change_ha >= 0`。
- 耕地平均坡度降低：`slope_change_pct < 0`。
- 连片度上升：`cont_change > 0`。
- 百亩方数量和面积报告并尽量提升，但不是默认 hard gate。

未使用：

- `configs/container_mnr_proxy.yml`
- 缩小的 sampling/training/planning 参数
- 跳过阶段的 smoke 流程

正式参数包括：

- `sampling.n_episodes: 60`
- `sampling.n_states: 1000`
- `sampling.n_actions: 50`
- `training.n_members: 3`
- `training.epochs: 30`
- `training.patience: 8`
- `planning.horizon: 5`
- `planning.top_k: 50`
- `planning.mpc_batch_size: 1024`

## Paper9v2.1 legacy-amd64 历史验证结果

完整报告：

```text
docs/reports/paper9v21_legacy_amd64_e2e_20260701/REPORT.md
```

本机正式输出目录：

```text
outputs/paper9v21_legacy_docker_e2e_20260701-2038/
```

| 环境 | run_id | 总用时 | prepare | sample | train | plan | audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 本机 Docker `linux/amd64` | `20260701-123848` | 6771.457s | 289.024s | 4728.314s | 1442.745s | 311.198s | 通过 |
| Windows Intel Docker | 见 Windows 运行日志 | 见 Windows 运行日志 | 见 Windows 运行日志 | 见 Windows 运行日志 | 见 Windows 运行日志 | 见 Windows 运行日志 | 已完成测试 |

核心业务结果：

| 环境 | 耕地面积变化 | 坡度变化 | 连片度变化 | 百亩方数变化 | 百亩方面积变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 本机 Docker `linux/amd64` | +446.199 ha | -0.3691% | +0.0483 | -20 | +669.173 ha |

产物入口：

- run manifest：`outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/logs/run_full_pipeline-20260701-123848.json`
- audit：`outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/audit_summary.json`
- MPC 摘要：`outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/plan_paper9v2_no_net_loss/mpc_summary.json`
- 最终矢量：`outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/plan_paper9v2_no_net_loss/DLTB_optimized.shp`

2026-06-27 的 Paper9v2.0 arm64 东兴/璧山双数据集验证仍保留在
`docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md`。上述结果只用于
回溯旧版运行基线；x86_64 现场正式使用保护区约束时必须改用 v2.2。

## 已知 warning

Paper9v2.1 legacy-amd64 E2E 日志中出现的 warning 类型如下，目前均未导致阶段失败：

- Fiona 对 GeoPackage v1.4 的 partial support 提示，以及 `BGRQ` 日期解析提示。
- Shapefile/DBF 字段名被截断，例如 `SHAPE_Length -> SHAPE_Leng`。
- 局部连通图存在 disconnected components / islands。
- `RuntimeWarning: invalid value encountered in divide`，来自没有有效面积或邻接的块级统计。
- `511011214` 在 Phase B 中无可用 blocks，被跳过。
- ONNX parity 校验通过，3 个成员最大差异分别为 `9.54e-07`、`4.77e-07`、`1.79e-07`。
- plan 阶段会提示 `baimu_area_penalty=3100.0` reward override。当前 sample/train 已使用同一套
  reward 权重；如果以后临时修改 plan 权重，应重新 sample/train。

现场部署时如果客户要求零 warning，需要优先处理 DBF 字段名截断和空乡镇 blocks 的诊断展示。

## 本机本地状态

以下目录是本机验证产物，通常被 `.gitignore` 忽略，不应提交到 GitHub：

- `data/input/`
- `data/working/`
- `outputs/`
- `dist/`

下个窗口如需继续核验本机产物，先检查：

```bash
cd /Users/zhouning/paper9-mnr-offline-package
git status --short
docker image inspect paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64
ls -lh outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/plan_paper9v2_no_net_loss
python3 -m json.tool outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/logs/run_full_pipeline-20260701-123848.json
```

## 后续现场部署关注点

1. 现场 deepin server 16 上 Docker 版本、服务状态、普通用户权限和数据盘路径。
2. 镜像 tar 和运行脚本是否能完整拷入内网机器。
3. 客户每县提供 DLTB、PDT、生态保护红线、永久基本农田四个完整 FileGDB 目录；DEM 和
   乡镇空间参考已随交付包内置，不向客户索取。PDT 只作质检。融合要求见
   `docs/18_authoritative_filegdb_fusion.md`。
4. 正式配置中路径、字段名、CRS 和输出目录是否与现场数据一致。
5. 首次现场运行先执行 `check -> dry-run -> run -> audit`，不要直接跳到 Notebook。
6. Notebook 作为扩展模式，用于查看输入、日志和地图可视化，不替代批处理正式运行。
7. 内网故障反馈必须带回该县完整 `outputs/logs/` 和 `input/fusion_report.json`，不能只截图。
