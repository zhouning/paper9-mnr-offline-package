# 03 完整流程

Paper9 离线流程分四步。自然资源部场景默认读取 DLTB 中的权威坡度字段，并使用
村级行政区图层作为行政名称参考层。

1. `prepare`: 读取 DLTB，使用权威坡度字段，定义不规则地块/图斑块。
2. `sample`: 在县域环境中采样状态、动作和奖励标签。
3. `train`: 训练 contrastive world model ensemble，并导出 ONNX。
4. `plan`: 使用 MPC 生成耕地空间布局优化方案。

## 打印命令

先不要直接运行真实任务，先检查命令计划：

```powershell
python scripts\run_full_pipeline.py configs\real_data_from_authority_slope.yml --dry-run
```

输出的 `prepare` 命令应包含：

```text
--slope-method from_field --slope-field slope_mean
--reference-layer data/input/admin_units.gpkg --reference-name-field XZQMC
```

也可以安装后使用：

```powershell
paper9-mnr print-plan configs\real_data_from_authority_slope.yml
```

## 分步运行

```powershell
python scripts\01_prepare.py configs\real_data_from_authority_slope.yml
python scripts\02_sample.py configs\real_data_from_authority_slope.yml
python scripts\03_train.py configs\real_data_from_authority_slope.yml
python scripts\04_plan.py configs\real_data_from_authority_slope.yml
python scripts\05_audit.py configs\real_data_from_authority_slope.yml --write
```

## 关键输出

- `data/working/prepared/dem_slope_analysis/output/DLTB_with_slope.shp`
- `data/working/prepared/townships.json`
- `data/working/prepared/results_real/blocks/...`
- `data/working/prepared/tool2/transitions.npz`
- `data/working/prepared/tool2/pairwise.npz`
- `data/working/prepared/tool3/`
- `outputs/plan_baseline/`
- `outputs/plan_baseline/DLTB_optimized.shp`
- `outputs/plan_baseline/mpc_summary.json`
- `outputs/audit_summary.json`

`DLTB_optimized.shp` 是对外主要空间成果，保留原始图斑属性，并增加优化建议字段：

- `ORIG_DLBM`: 原始地类编码。
- `OPT_DLBM`: 优化建议后的地类编码。
- `OPT_DLMC`: 优化建议后的地类名称。
- `CHG_FLAG`: 0=不变，1=耕地转林地，2=林地转耕地。

`mpc_summary.json` 是指标摘要，记录坡度、连片性、百亩方面积、交换数量和运行参数。
`audit_summary.json` 是文件级审计摘要，记录关键产物是否存在。

如果要保留多个方案，复制一份配置文件，修改 `prepared_dir`、`plan_dir` 和
`optimized_vector`，避免覆盖已有结果。

面向客户的完整操作说明见 `docs/09_mnr_customer_runbook.md`。
