# 03 完整流程

Paper9 离线流程分四步：

1. `prepare`: 读取 DLTB，使用权威坡度字段，定义不规则地块/图斑块。
2. `sample`: 在县域环境中采样状态、动作和奖励标签。
3. `train`: 训练 contrastive world model ensemble，并导出 ONNX。
4. `plan`: 使用 MPC 生成耕地空间布局优化方案。

## 打印命令

先不要直接运行真实任务，先检查命令计划：

```powershell
python scripts\run_full_pipeline.py configs\real_data_from_authority_slope.yml --dry-run
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
- `data/working/prepared/results_real/blocks/...`
- `data/working/prepared/tool2/transitions.npz`
- `data/working/prepared/tool2/pairwise.npz`
- `data/working/prepared/tool3/`
- `outputs/plan_baseline/`
- `outputs/plan_baseline/DLTB_optimized.shp`

如果要保留多个方案，复制一份配置文件，修改 `prepared_dir`、`plan_dir` 和
`optimized_vector`，避免覆盖已有结果。

