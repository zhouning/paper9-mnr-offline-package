# 14 双模式镜像使用手册

Paper9 MNR 离线镜像支持两种使用模式：

- 命令行批处理模式：正式生产运行、验收、重复执行和问题诊断的主入口。
- Notebook 扩展模式：现场核查输入数据、解释流程日志、查看结果交互地图和做交互式复核的辅助入口。

两种模式使用同一个镜像、同一份配置、同一组数据挂载目录。Notebook 不是替代批处理的生产入口，
而是把批处理产生的日志和成果可视化出来，便于客户现场验证。

## 当前客户机器默认参数

自然资源部当前提供的机器信息显示：

```text
操作系统：deepin server 16
CPU 架构：x86_64
容器策略：已确认允许 Docker
默认运行时：docker
默认镜像：paper9-mnr-offline:paper9v2-2.0.0-amd64
默认离线包：paper9-mnr-container-runtime-paper9v2-2.0.0-amd64.tar.gz
默认配置：configs/paper9v2_no_net_loss_authority_slope.yml
```

因此，以下现场命令默认使用 `--runtime docker --arch amd64 --image-ref
paper9-mnr-offline:paper9v2-2.0.0-amd64`。`--image-ref` 是 Paper9v2 正式发布镜像引用；
`--image paper9-mnr-offline --arch amd64` 保留给 v1 和历史包兼容使用，不作为 Paper9v2
发布口径。`arm64` 镜像包仍然保留，但仅用于其他 ARM 服务器，不用于当前这三台 deepin
x86_64 机器；对应正式引用为 `paper9-mnr-offline:paper9v2-2.0.0-arm64`。

## Paper9v2 业务门禁和已验证基线

Paper9v2 的默认配置是 `configs/paper9v2_no_net_loss_authority_slope.yml`。它把以下三项作为
正式 run/audit 的硬门禁：

| 指标 | 通过条件 | 说明 |
| --- | --- | --- |
| 县域耕地总面积 | `cultivated_area_change_ha >= 0` | 县域范围内耕地总面积不减少 |
| 耕地平均坡度 | `slope_change_pct < 0` | 负值表示平均坡度降低 |
| 连片度 | `cont_change > 0` | 正值表示连片度上升 |
| 百亩方 | 报告并尽量提升 | 默认不是 hard gate，需在报告中解释数量和面积变化 |

`run` 动作已经把 audit 放在最后阶段；如果三项硬门禁失败，正式流程应返回失败，不应把结果描述为可采用方案。
`audit` 动作用于对已有产物重复复核。

本机已用 Paper9v2 Docker 镜像完成东兴和璧山两套数据的全流程 E2E，报告见
`docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md`。验证摘要：

| 数据集 | run_id | 总用时 | 耕地面积变化 | 坡度变化 | 连片度变化 | audit |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 东兴 | `20260627-155224` | 4044.299s | +508.783 ha | -0.3431% | +0.0530 | 通过 |
| 璧山 | `20260627-170016` | 2919.626s | +4.323 ha | -0.8564% | +0.0268 | 通过 |

## 镜像和数据边界

镜像包含 Python 运行时、Paper9 MNR 代码、配置模板、脚本、文档、测试、JupyterLab 和可视化依赖。
镜像不包含自然资源部真实数据，也不包含运行后的成果。

客户侧只需要挂载三个目录：

```text
/data/paper9/input    -> /app/data/input     只读，放客户输入数据
/data/paper9/working  -> /app/data/working   可写，放中间过程产物
/data/paper9/outputs  -> /app/outputs        可写，放最终成果、日志和 notebook 地图
```

客户业务输入仍是两类：

```text
/data/paper9/input/DLTB_with_authority_slope.gpkg
/data/paper9/input/admin_units.gpkg
```

`DEM_placeholder.tif` 是原 Paper9 接口需要的占位文件，不是第三类业务输入：

```text
/data/paper9/input/DEM_placeholder.tif
```

## 模式一：命令行批处理模式

批处理模式用于正式内网运行。建议顺序为 `check -> dry-run -> run -> audit`。

已有镜像 tar 时，先加载对应 CPU 架构的镜像：

```bash
docker load -i images/paper9-mnr-offline-linux-amd64.tar
```

其他 ARM 服务器才使用：

```bash
docker load -i images/paper9-mnr-offline-linux-arm64.tar
```

准备目录：

```bash
mkdir -p /data/paper9/input /data/paper9/working /data/paper9/outputs
```

检查容器环境、配置和测试：

```bash
./bin/run-paper9-container.sh check \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

只打印完整流程命令，不实际运行：

```bash
./bin/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

确认 dry-run 中 `prepare` 命令包含以下参数：

```text
--slope-method from_field --slope-field slope_mean
--reference-layer data/input/admin_units.gpkg --reference-name-field XZQMC
```

同时确认 dry-run 中 `sample` 和 `plan` 命令均包含以下参数：

```text
--cultivated-area-floor-delta-ha 0
```

正式运行：

```bash
./bin/run-paper9-container.sh run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

运行完成后做成果审计：

```bash
./bin/run-paper9-container.sh audit \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

如果目标机是 arm64，把 `--arch amd64` 改为 `--arch arm64`，把 `--image-ref` 改为
`paper9-mnr-offline:paper9v2-2.0.0-arm64`，并加载 arm64 镜像 tar。
如果使用 Podman，把 `--runtime docker` 改为 `--runtime podman`。

## 模式二：Notebook 扩展模式

Notebook 模式用于核查和解释，不建议作为无人值守生产入口。启动方式：

```bash
./bin/run-paper9-container.sh notebook \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9 \
  --notebook-port 8888 \
  --notebook-token paper9
```

访问地址：

```text
http://127.0.0.1:8888/lab?token=paper9
```

如果在服务器上运行，把 `127.0.0.1` 换成客户允许访问的服务器地址，并确认防火墙允许访问
`--notebook-port` 指定的端口。

镜像内置的 notebook 模板位于：

```text
/app/notebooks/
```

建议按顺序打开：

```text
00_input_data_check.ipynb
01_pipeline_run_and_logs.ipynb
02_result_visualization.ipynb
```

Notebook 中完整流程默认不会自动执行。需要在 Notebook 中触发完整运行时，先确认 dry-run
输出无误，再把 `01_pipeline_run_and_logs.ipynb` 里的：

```python
RUN_PIPELINE = False
```

改为：

```python
RUN_PIPELINE = True
```

注意：`run-paper9-container.sh notebook --config ...` 会把配置路径写入容器环境变量
`PAPER9_CONFIG`。Notebook 模板默认读取该环境变量；如需临时切换，也可以直接修改代码单元里的
`CONFIG` 变量。

## 本机模拟客户 x86_64 验收步骤

当前客户机器是 x86_64，因此本机即使是 Apple Silicon，也应额外验证 `linux/amd64`
镜像。由于 `run-paper9-container.sh` 会阻止宿主机架构和 `--arch` 不一致，本机模拟
amd64 时使用原生 `docker run --platform linux/amd64` 命令；客户 deepin x86_64 机器上
仍按上一节使用 `./bin/run-paper9-container.sh --arch amd64`。

准备隔离输出目录：

```bash
mkdir -p data/working/e2e-amd64 outputs/e2e-amd64
```

检查配置：

```bash
docker run --rm --platform linux/amd64 \
  -e PAPER9_LOG_DIR=/app/outputs/logs \
  -v /Users/zhouning/paper9-mnr-offline-package/data/input:/app/data/input:ro \
  -v /Users/zhouning/paper9-mnr-offline-package/data/working/e2e-amd64:/app/data/working:rw \
  -v /Users/zhouning/paper9-mnr-offline-package/outputs/e2e-amd64:/app/outputs:rw \
  paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  python -m paper9_mnr.cli check-config configs/paper9v2_no_net_loss_authority_slope.yml
```

执行 dry-run、run 和单独复核 audit 时，把最后一行分别替换为：

```bash
python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml --dry-run
python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml
python scripts/05_audit.py configs/paper9v2_no_net_loss_authority_slope.yml --write
```

`run_full_pipeline.py` 的正式运行已把 audit 纳入最后阶段，只有 Paper9v2 的耕地面积不减少、
平均坡度降低、连片度上升三项硬门禁通过才会返回成功；第三条命令用于对已生成产物重复审计。

Notebook 依赖检查：

```bash
docker run --rm --platform linux/amd64 paper9-mnr-offline:paper9v2-2.0.0-amd64 jupyter lab --version
```

## 本机原生 arm64 补充验收步骤

本机已有代理输入数据和两个镜像后，可以用轻量配置做双模式验收。以下命令以 Apple Silicon
原生 arm64 镜像为例。

批处理模式：

```bash
deploy/container-runtime/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch arm64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --input-dir /Users/zhouning/paper9-mnr-offline-package/data/input \
  --working-dir /Users/zhouning/paper9-mnr-offline-package/data/working \
  --outputs-dir /Users/zhouning/paper9-mnr-offline-package/outputs

deploy/container-runtime/run-paper9-container.sh run \
  --runtime docker \
  --arch arm64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --input-dir /Users/zhouning/paper9-mnr-offline-package/data/input \
  --working-dir /Users/zhouning/paper9-mnr-offline-package/data/working \
  --outputs-dir /Users/zhouning/paper9-mnr-offline-package/outputs

deploy/container-runtime/run-paper9-container.sh audit \
  --runtime docker \
  --arch arm64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --input-dir /Users/zhouning/paper9-mnr-offline-package/data/input \
  --working-dir /Users/zhouning/paper9-mnr-offline-package/data/working \
  --outputs-dir /Users/zhouning/paper9-mnr-offline-package/outputs
```

Notebook 模式：

```bash
deploy/container-runtime/run-paper9-container.sh notebook \
  --runtime docker \
  --arch arm64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-arm64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --input-dir /Users/zhouning/paper9-mnr-offline-package/data/input \
  --working-dir /Users/zhouning/paper9-mnr-offline-package/data/working \
  --outputs-dir /Users/zhouning/paper9-mnr-offline-package/outputs \
  --notebook-port 8888 \
  --notebook-token paper9
```

然后打开：

```text
http://127.0.0.1:8888/lab?token=paper9
```

上述命令会让 notebook 默认读取 `configs/paper9v2_no_net_loss_authority_slope.yml`。打开后第一个代码单元会打印
当前 `CONFIG`，先确认它指向 Paper9v2 配置，再继续运行后续单元。

## 自然资源部现场验收步骤

现场验收建议按以下顺序执行：

1. `docker load` 或 `podman load` 对应架构镜像。
2. 放置 DLTB、行政区和 DEM 占位文件。
3. 执行 `run-paper9-container.sh check`，确认环境、依赖、测试和配置通过。
4. 执行 `run-paper9-container.sh dry-run`，确认参数和数据路径正确。
5. 执行 `run-paper9-container.sh run`，完成 prepare/sample/train/plan。
6. 查看 `outputs/audit_summary.json`，确认三项 hard gate 均通过；必要时再执行
   `run-paper9-container.sh audit` 对既有产物重复复核。
7. 如需现场解释，再启动 `run-paper9-container.sh notebook` 查看输入、日志和交互地图。

## 日志、成果和诊断入口

批处理和 Notebook 触发的完整流程都会写日志：

```text
/data/paper9/outputs/logs/
```

每次完整运行生成：

```text
run_full_pipeline-YYYYMMDD-HHMMSS.log
run_full_pipeline-YYYYMMDD-HHMMSS.json
YYYYMMDD-HHMMSS-prepare.log
YYYYMMDD-HHMMSS-sample.log
YYYYMMDD-HHMMSS-train.log
YYYYMMDD-HHMMSS-plan.log
YYYYMMDD-HHMMSS-audit.log
```

优先打开 JSON manifest。它记录配置、每个阶段的命令、开始时间、结束时间、返回码、耗时和阶段日志路径。

默认正式成果：

```text
/data/paper9/outputs/plan_paper9v2_no_net_loss/DLTB_optimized.shp
/data/paper9/outputs/plan_paper9v2_no_net_loss/mpc_summary.json
/data/paper9/outputs/audit_summary.json
```

`audit_summary.json` 中重点查看：

```text
constraint_status.hard_constraint_passed
constraint_status.records[0].cultivated_area_change_ha
constraint_status.records[0].slope_change_pct
constraint_status.records[0].cont_change
constraint_status.records[0].baimu_count_change
constraint_status.records[0].baimu_area_change_ha
```

现场报告至少应记录 run_id、镜像引用、配置文件、各阶段耗时、上述 audit 指标和
`DLTB_optimized.shp` 产物路径。

Notebook 导出的离线交互地图：

```text
/data/paper9/outputs/notebook/input_layers_map.html
/data/paper9/outputs/notebook/optimization_changes_map.html
```

这些 HTML 地图用于现场解释和核查，默认对展示图层采样并压缩坐标精度；正式矢量成果
`DLTB_optimized.shp` 不会因此被抽样或简化。

## 常见问题

### 目标机器没有网络怎么办？

正常。交付的是已构建好的镜像 tar。目标机器只需要容器运行时和 `docker load`/`podman load`，
不需要访问 PyPI、Docker Hub 或 GitHub。

### 目标机器没有 Docker/Podman 怎么办？

如果允许离线安装容器运行时，按 `docs/12_container_runtime_airgap.md` 准备对应发行版和架构的
Docker/Podman 离线安装包。如果完全不允许容器运行时，需要改走 Linux 离线 Python 运行时包方案。

### Notebook 能否在纯内网可视化？

可以。当前可视化是离线 Leaflet 交互式 HTML 地图，镜像内置 JS/CSS，不依赖外网地图瓦片或 CDN。

### Notebook 模式是否会自动运行完整流程？

不会。Notebook 模板默认只做核查、dry-run 和结果查看。需要手动把 `RUN_PIPELINE` 改为 `True`
才会触发完整流程。

### 什么时候需要重新 sample 和 train？

修改 reward、约束、业务偏好或输入数据后，应重新运行 `sample -> train -> plan`。不能只用旧模型
重跑 `plan` 后直接解释为新偏好下的结果。
