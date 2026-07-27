# Paper9v2.2.3 双模式镜像使用说明

当前默认镜像为 `paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64`，默认配置为
`configs/paper9v22_authority_constraints.yml`。批处理和 Notebook 共用同一镜像、同一融合输入
和同一审计口径。

## 统一的数据准备

无论使用哪种模式，都先对每个县独立执行一次 `fuse`：

```bash
./bin/run-paper9-container.sh fuse \
  --runtime docker --arch amd64 \
  --data-root /data/paper9/dongxing \
  --dltb-gdb /authority/dongxing/DLTB.gdb \
  --pdt-gdb /authority/dongxing/PDT.gdb \
  --eco-redline-gdb /authority/dongxing/STBHHX.gdb \
  --permanent-basic-farmland-gdb /authority/dongxing/YJJBNTBHTB.gdb
```

客户只提供四个 GDB 路径。图层名、县区、CRS 和坡度数据由融合器处理，DEM 来自交付包的
`dem/copernicus_glo30/`。四个 GDB 与 DEM 以只读方式挂载，容器无网络。

融合后目录关系为：

```text
DATA_ROOT/input    融合后的 Paper9 输入，只读挂载给常规运行
DATA_ROOT/working  prepare/sample/train 中间数据，可写
DATA_ROOT/outputs  规划成果、审计和日志，可写
```

`input` 中的 `DEM_placeholder.tif` 是自动生成的接口文件。连续坡度来自
`DLTB_with_authority_slope.gpkg` 的 `slope_mean`。

## 模式一：命令行批处理

正式生产使用批处理模式：

```bash
./bin/run-paper9-container.sh check \
  --runtime docker --arch amd64 --data-root DATA_ROOT

./bin/run-paper9-container.sh dry-run \
  --runtime docker --arch amd64 --data-root DATA_ROOT

./bin/run-paper9-container.sh run \
  --runtime docker --arch amd64 --data-root DATA_ROOT

./bin/run-paper9-container.sh audit \
  --runtime docker --arch amd64 --data-root DATA_ROOT
```

所有动作都使用 `--network none`。`run` 已把 audit 作为最后阶段，单独 `audit` 用于对既有
成果重复复核。默认硬门禁为：耕地总面积不减少、耕地平均坡度降低、连片度上升。

默认成果：

```text
DATA_ROOT/outputs/plan_paper9v22_authority_constraints/DLTB_optimized.shp
DATA_ROOT/outputs/plan_paper9v22_authority_constraints/mpc_summary.json
DATA_ROOT/outputs/audit_summary.json
DATA_ROOT/outputs/logs/
```

## 模式二：Notebook 核查

Notebook 用于输入检查、日志查看和离线地图解释，不替代正式批处理：

```bash
./bin/run-paper9-container.sh notebook \
  --runtime docker --arch amd64 \
  --data-root DATA_ROOT \
  --notebook-port 8888 \
  --notebook-token paper9
```

浏览器访问 `http://127.0.0.1:8888/lab?token=paper9`。模板位于：

```text
00_input_data_check.ipynb
01_pipeline_run_and_logs.ipynb
02_result_visualization.ipynb
```

Notebook 默认不启动完整训练和规划。只有检查 `PAPER9_CONFIG` 与 dry-run 后，才可按模板
说明设置 `RUN_PIPELINE=True`。离线 HTML 地图使用镜像内置 Leaflet 资源，不访问 CDN 或
底图服务。

## 两县隔离

东兴区和璧山区分别使用不同 `data-root`，分别融合、训练、规划和审计。不得共享
`input/working/outputs`，也不得把一个县的模型用于另一个县后直接作为正式结果。

## 保护区行为

生态保护红线和永久基本农田重叠图斑以 `EXCH_LOCK=1` 排除在两个互换方向之外。Notebook
可以显示和统计锁定图斑，但没有解除锁定的入口。任何经审批的例外都需要新的规则版本和完整
审计，不能在现场修改融合结果。

## 诊断入口

- 融合来源、图层选择、DEM 覆盖和锁定统计：`DATA_ROOT/input/fusion_report.json`。
- 每阶段命令、耗时、返回码和日志：`DATA_ROOT/outputs/logs/run_full_pipeline-*.json`。
- 最终硬门禁：`DATA_ROOT/outputs/audit_summary.json`。
- 权威约束空间核查：`DATA_ROOT/input/authority_constraints.gpkg`。

客户真实 GDB 不在发布仓库中，因此镜像和模拟数据测试只证明工程链路可运行。正式业务结论
必须以客户内网两县各自的融合报告、运行 manifest 和审计结果为准。
