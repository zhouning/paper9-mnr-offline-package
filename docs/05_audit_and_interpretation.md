# 05 审计与结果解释

`scripts/05_audit.py` 先做轻量文件级审计，确认关键产物是否存在。真实业务审计还应
进一步做指标审计和空间叠加审计。

## 文件级审计

```powershell
python scripts\05_audit.py configs\real_data_from_authority_slope.yml --write
```

输出会检查：

- prepared 目录。
- `tool2/transitions.npz`。
- `tool2/pairwise.npz`。
- 训练后的 ensemble 目录。
- plan 输出目录。
- 优化后的矢量文件。

## 指标级审计

建议至少统计：

- 优化前后耕地面积。
- 优化前后平均坡度。
- 优化前后连片度。
- 百亩方面积和数量。
- 变更图斑数量、面积和地类转移矩阵。
- 是否满足无净损约束。

`outputs/plan_baseline/mpc_summary.json` 已记录本次 MPC 的核心摘要，包括平均坡度变化、
连片性变化、百亩方面积变化、输入图斑数、进入环境的图斑数、耕地转林地数量、
林地转耕地数量和不变数量。

## 优化矢量成果解释

对外主要空间成果为配置中的 `outputs.optimized_vector`，默认是：

```text
outputs/plan_baseline/DLTB_optimized.shp
```

该文件保留原始 DLTB 属性，并新增：

- `ORIG_DLBM`: 原始地类编码。
- `OPT_DLBM`: 优化建议后的地类编码。
- `OPT_DLMC`: 优化建议后的地类名称。
- `CHG_FLAG`: 0=不变，1=耕地转林地，2=林地转耕地。

客户验收时应至少抽查：

- `DLBM` 与 `ORIG_DLBM` 是否一致。
- `OPT_DLBM` 是否只在允许优化的图斑上变化。
- `CHG_FLAG` 与 `ORIG_DLBM/OPT_DLBM` 是否一致。
- 输出图斑数是否与输入 DLTB 图斑数一致。
- 未进入县域环境的图斑是否按原地类透传。

## 空间叠加审计

与自然资源部真实业务结合时，应叠加：

- 三区三线。
- 永久基本农田。
- 生态保护红线。
- 土壤质量或耕地质量等级。
- 行政边界、权属边界、项目区边界。

输出方案不能只看 reward；必须能解释“哪些图斑改了、为什么改、是否违反硬约束、
对业务指标有什么影响”。
