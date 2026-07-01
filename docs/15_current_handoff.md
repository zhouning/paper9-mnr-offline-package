# 15 当前工作进度接续说明

更新时间：2026-07-01

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
- `linux/arm64` 镜像包仍保留给其他 ARM 服务器，但不是当前这三台机器的默认包。

## 当前镜像和使用方式

- 当前 Paper9v2 默认配置：`configs/paper9v2_no_net_loss_authority_slope.yml`
- 当前客户 deepin x86_64 现场默认镜像：`paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64`
- 当前已导出的 x86_64 独立镜像 tar：
  `dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar`
- 当前校验文件：
  `dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt`
- 本机 Apple Silicon 已验证镜像：`paper9-mnr-offline:paper9v2-2.0.0-arm64`
- 当前 amd64 交付镜像元数据：包版本 `0.2.1`，算法 `paper9v2 2.1.0`，revision 待 legacy 构建写入
- 前次 arm64 E2E 验证镜像元数据：包版本 `0.2.0`，算法 `paper9v2 2.0.0`，revision `a58fa3ad15c9`
- 现场运行脚本：`deploy/container-runtime/run-paper9-container.sh`
- 推荐现场顺序：
  1. `check`
  2. `dry-run`
  3. `run`
  4. 查看 `outputs/audit_summary.json`
  5. 如需复核既有产物，再单独执行 `audit`
  6. 如需解释和可视化，再启动 `notebook`

详细命令以以下文档为准：

- `docs/09_mnr_customer_runbook.md`
- `docs/11_container_deployment.md`
- `docs/13_notebook_and_logs.md`
- `docs/14_dual_mode_image_usage.md`

## 正式全量验证口径

本机已按 Paper9v2 正式参数完成东兴和璧山两套数据的 Docker 端到端验证。使用配置：

```text
configs/paper9v2_no_net_loss_authority_slope.yml
```

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

## Paper9v2 双数据集全量验证结果

完整图文报告：

```text
docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md
```

正式输出目录：

- 东兴：`outputs/paper9v2_docker_e2e_20260627/dongxing/`
- 璧山：`outputs/paper9v2_docker_e2e_20260627/bishan/`

| 数据集 | run_id | 总用时 | prepare | sample | train | plan | audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 东兴 | `20260627-155224` | 4044.299s | 76.829s | 2102.909s | 1673.070s | 191.410s | 通过 |
| 璧山 | `20260627-170016` | 2919.626s | 36.434s | 1632.444s | 1144.977s | 105.687s | 通过 |

核心业务结果：

| 数据集 | 耕地面积变化 | 坡度变化 | 连片度变化 | 百亩方数变化 | 百亩方面积变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 东兴 | +508.783 ha | -0.3431% | +0.0530 | -23 | +766.871 ha |
| 璧山 | +4.323 ha | -0.8564% | +0.0268 | +1 | +34.638 ha |

产物入口：

- run manifest：`outputs/paper9v2_docker_e2e_20260627/{dongxing,bishan}/logs/run_full_pipeline-*.json`
- audit：`outputs/paper9v2_docker_e2e_20260627/{dongxing,bishan}/audit_summary.json`
- MPC 摘要：`outputs/paper9v2_docker_e2e_20260627/{dongxing,bishan}/plan_paper9v2_no_net_loss/mpc_summary.json`
- 最终矢量：`outputs/paper9v2_docker_e2e_20260627/{dongxing,bishan}/plan_paper9v2_no_net_loss/DLTB_optimized.shp`

## 已知 warning

Paper9v2 双数据集 E2E 日志中出现的 warning 类型一致，目前均未导致阶段失败：

- Shapefile/DBF 字段名被截断，例如 `SHAPE_Length -> SHAPE_Leng`。
- 局部连通图存在 disconnected components / islands。
- `RuntimeWarning: invalid value encountered in divide`，来自没有有效面积或邻接的块级统计。
- `511011214` 在 Phase B 中无可用 blocks，被跳过。
- ONNX version converter 出现 fallback/traceback warning，但 6 个 ONNX 成员均完成导出并通过
  parity 校验，最大差异在 `4.77e-07` 到 `7.15e-07` 量级。
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
docker image inspect paper9-mnr-offline:paper9v2-2.0.0-arm64
ls -lh outputs/paper9v2_docker_e2e_20260627/dongxing/plan_paper9v2_no_net_loss
python3 -m json.tool outputs/paper9v2_docker_e2e_20260627/dongxing/logs/run_full_pipeline-20260627-155224.json
```

## 后续现场部署关注点

1. 现场 deepin server 16 上 Docker 版本、服务状态、普通用户权限和数据盘路径。
2. 镜像 tar 和运行脚本是否能完整拷入内网机器。
3. 客户正式输入文件是否满足 `docs/02_data_contract.md`：
   - 带权威坡度字段的 DLTB。
   - 可细化到村级的全国行政区数据。
4. 正式配置中路径、字段名、CRS 和输出目录是否与现场数据一致。
5. 首次现场运行先执行 `check -> dry-run -> run -> audit`，不要直接跳到 Notebook。
6. Notebook 作为扩展模式，用于查看输入、日志和地图可视化，不替代批处理正式运行。
