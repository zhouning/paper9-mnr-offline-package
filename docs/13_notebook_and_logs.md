# 13 Notebook 扩展模式与日志

Paper9 MNR 容器同时支持两种运行模式：

- 命令行批处理模式：用于正式内网运行、验收和重复执行。
- Notebook 扩展模式：用于输入数据核查、过程解释、成果可视化和现场诊断。

Notebook 不是正式运行的唯一入口。正式生产运行仍建议使用
`run-paper9-container.sh check/dry-run/run/audit`，这样命令、日志和输出更容易复核。

完整的双模式镜像使用流程见 `docs/14_dual_mode_image_usage.md`。本文只展开 Notebook
和日志细节。

当前自然资源部机器为 `deepin server 16 / x86_64`，且客户已确认允许 Docker，因此现场默认使用：

```text
runtime = docker
arch = amd64
data_root = /data/paper9
image_ref = paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64
config = configs/paper9v2_no_net_loss_authority_slope.yml
```

## Notebook 启动

已有 Docker/Podman 和 Paper9 镜像后：

```bash
./bin/run-paper9-container.sh notebook \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9 \
  --notebook-port 8888 \
  --notebook-token paper9
```

浏览器访问：

```text
http://127.0.0.1:8888/lab?token=paper9
```

如果是在服务器上运行，需要把 `127.0.0.1` 换成客户允许访问的服务器地址，并确认内网
防火墙允许访问该端口。

## Notebook 模板

镜像内置模板位于：

```text
/app/notebooks/
```

当前包括：

```text
00_input_data_check.ipynb
01_pipeline_run_and_logs.ipynb
02_result_visualization.ipynb
```

这些 notebook 读取同一份配置：

```text
configs/paper9v2_no_net_loss_authority_slope.yml
```

Notebook 模式会读取容器环境变量 `PAPER9_CONFIG`。使用
`run-paper9-container.sh notebook --config configs/paper9v2_no_net_loss_authority_slope.yml` 启动时，wrapper 会把
该配置传入 Notebook。

如未通过 wrapper 注入配置，也可以在每个 notebook 的第一个代码单元把 `CONFIG` 改成：

```python
CONFIG = "configs/paper9v2_no_net_loss_authority_slope.yml"
```

并使用同样的数据挂载：

```text
/app/data/input
/app/data/working
/app/outputs
```

Notebook 里的完整流程运行默认关闭。需要实际执行时，先确认 dry-run 输出无误，再把
`RUN_PIPELINE = False` 改成 `RUN_PIPELINE = True`。

## 可视化能力

Notebook 可在纯内网中完成交互式地图可视化，不依赖外网地图瓦片或 CDN：

- DLTB 图斑与行政区边界叠加检查，可缩放、拖拽、点选查看属性。
- 必要字段、坐标系、记录数、空间范围检查。
- 优化结果 `CHG_FLAG` 分类地图展示。
- `farm->forest`、`forest->farm`、`unchanged` 汇总。
- 关键地图导出到 `outputs/notebook/*.html`。

为保证现场浏览器响应速度，Notebook 地图默认使用采样预览，并对展示用 GeoJSON 做坐标精度压缩。
需要更密集的图斑显示时，可在对应代码单元调大 `max_features`。

## 日志目录

命令行和 notebook 触发的完整流程都会把运行日志写到：

```text
/app/outputs/logs
```

由于 `/app/outputs` 挂载到宿主机，目标机器上对应目录为：

```text
/data/paper9/outputs/logs
```

每次 `scripts/run_full_pipeline.py` 运行会生成：

```text
run_full_pipeline-YYYYMMDD-HHMMSS.log
run_full_pipeline-YYYYMMDD-HHMMSS.json
YYYYMMDD-HHMMSS-prepare.log
YYYYMMDD-HHMMSS-sample.log
YYYYMMDD-HHMMSS-train.log
YYYYMMDD-HHMMSS-plan.log
YYYYMMDD-HHMMSS-audit.log
```

JSON manifest 记录配置文件、每个阶段的命令、开始/结束时间、返回码、阶段日志路径和
运行状态。现场诊断优先查看 manifest，再按失败阶段打开对应日志。

Paper9v2 的正式 `run` 已把 audit 作为最后阶段。现场解释时重点查看：

```text
/data/paper9/outputs/audit_summary.json
/data/paper9/outputs/plan_paper9v2_no_net_loss/mpc_summary.json
```

`audit_summary.json` 的 `constraint_status.hard_constraint_passed` 必须为 `true`，并且记录中应显示
耕地面积不减少、平均坡度降低、连片度上升。Notebook 用于解释这些结果，不替代批处理验收。
