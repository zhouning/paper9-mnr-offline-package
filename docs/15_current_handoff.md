# 15 当前工作进度接续说明

更新时间：2026-06-25

本文用于关闭当前窗口后，在后续窗口继续处理 Paper9 自然资源部离线部署包。本文只记录
工程状态、验证证据和后续动作，不包含客户真实数据。

## 当前部署判断

- 客户已重新确认允许使用 Docker，因此当前主线是 Docker/OCI 离线部署包。
- 客户提供的三台机器画像：
  - 操作系统：`deepin server 16`
  - 架构：`x86_64`
  - Docker：至少一台机器上已存在 `/usr/bin/docker`，其他机器需要现场再次确认。
  - Podman：当前截图中未安装。
- 这批 deepin x86_64 机器默认使用 `linux/amd64` 镜像包。
- `linux/arm64` 镜像包仍保留给其他 ARM 服务器，但不是当前这三台机器的默认包。

## 当前镜像和使用方式

- 本机验证镜像：`paper9-mnr-offline:amd64`
- 本机验证平台参数：`--platform linux/amd64`
- 现场运行脚本：`deploy/container-runtime/run-paper9-container.sh`
- 推荐现场顺序：
  1. `check`
  2. `dry-run`
  3. `run`
  4. `audit`
  5. 如需解释和可视化，再启动 `notebook`

详细命令以以下文档为准：

- `docs/09_mnr_customer_runbook.md`
- `docs/11_container_deployment.md`
- `docs/13_notebook_and_logs.md`
- `docs/14_dual_mode_image_usage.md`

## 正式全量验证口径

本机已按正式参数完成两轮端到端 Docker 验证。使用的是基于
`configs/real_data_from_authority_slope.yml` 的正式配置，只把输出目录改成独立目录。

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

## 两轮全量验证结果

第一轮输出目录：

- 日志：`outputs/full_real_data_20260625/logs/`
- run manifest：`outputs/full_real_data_20260625/logs/run_full_pipeline-20260625-111045.json`
- 规划摘要：`outputs/full_real_data_20260625/plan/mpc_summary.json`
- 最终矢量：`outputs/full_real_data_20260625/plan/DLTB_optimized.shp`

第二轮输出目录：

- 日志：`outputs/full_real_data_20260625_run2/logs/`
- dry-run manifest：`outputs/full_real_data_20260625_run2/logs/run_full_pipeline-20260625-142056.json`
- run manifest：`outputs/full_real_data_20260625_run2/logs/run_full_pipeline-20260625-142307.json`
- check-config 日志：`outputs/full_real_data_20260625_run2/logs/check-config-run2-verify.log`
- audit 日志：`outputs/full_real_data_20260625_run2/logs/audit-run2-verify.log`
- audit 摘要：`outputs/full_real_data_20260625_run2/audit_summary.json`
- 规划摘要：`outputs/full_real_data_20260625_run2/plan/mpc_summary.json`
- 最终矢量：`outputs/full_real_data_20260625_run2/plan/DLTB_optimized.shp`

两轮耗时：

| 阶段 | 第一轮 | 第二轮 |
| --- | ---: | ---: |
| prepare | 112.008s | 108.913s |
| sample | 1765.975s | 1757.748s |
| train | 1482.805s | 1670.922s |
| plan | 245.508s | 371.855s |
| total | 3606.304s | 3909.444s |

核心成果两轮一致：

- `slope_change_pct = -0.4839646431431592`
- `cont_change = 0.04298771154939418`
- `baimu_area_change_ha = 257.98083532556296`
- `baimu_count_change = -1`
- `swaps_completed = 458`
- `cultivated_area_change_ha = 27.712161006724834`
- `cultivated_area_change_pct = 0.0354532918460902`
- 输入图斑数 `134369`
- 进入环境图斑数 `76377`
- pass-through 图斑数 `57992`
- farm->forest `458`
- forest->farm `458`

二进制产物哈希对比结论：

- `transitions.npz` 一致
- `pairwise.npz` 一致
- 3 个 `ensemble_member*.onnx` 一致
- 3 个 `ensemble_member*.pt` 一致
- `mpc_land_use.npy` 一致
- `DLTB_optimized.shp/.dbf/.shx/.prj` 一致

`mpc_summary.json` 和日志文件的文件哈希不同，原因是运行目录、开始结束时间和耗时字段不同；
核心业务指标一致。

## 已知 warning

两轮日志中出现的 warning 类型一致，目前均未导致阶段失败：

- Shapefile/DBF 字段名被截断，例如 `source_index -> source_ind`。
- 1 个图斑数不足阈值的乡镇被丢弃。
- `511011214` 在 Phase B 中无可用 blocks，被跳过。
- ONNX version converter 出现 fallback/traceback warning，但训练阶段 returncode 为 `0`，ONNX
  和 PT 模型文件已生成，且两轮哈希一致。

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
docker image inspect paper9-mnr-offline:amd64
ls -lh outputs/full_real_data_20260625_run2/plan
python3 -m json.tool outputs/full_real_data_20260625_run2/logs/run_full_pipeline-20260625-142307.json
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
