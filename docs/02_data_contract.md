# 02 数据契约

本工程包默认服务自然资源部真实图斑数据。关键前提是：图斑已经自带权威坡度字段，
不再从公开 DEM 重新计算坡度。

## 必需输入

### DLTB 图斑

支持 GeoPackage、Shapefile、GeoJSON 等 GeoPandas 可读取格式。推荐 GeoPackage，
减少 Shapefile 字段名截断风险。

必需字段：

- `DLBM`: 地类编码。
- `QSDWDM`: 权属单位代码；前 9 位用于乡镇/街道分组。
- `BSM`: 图斑唯一标识。
- `slope_mean`: 权威坡度字段，单位应为度。
- `geometry`: 面几何，必须有 CRS。

字段名可在 `configs/*.yml` 中改：

```yaml
fields:
  dlbm: DLBM
  qsdwdm: QSDWDM
  bsm: BSM
slope:
  source: field
  field: slope_mean
```

### DEM 占位文件

Paper9 原始 `prepare` 接口保留了 `--dem` 参数。使用 `slope.source: field` 时，坡度
来自图斑字段，不使用 DEM 计算坡度。配置中仍保留 `data.dem`，用于兼容原接口。

## 可选业务图层

后续奖励函数可纳入：

- 三区三线。
- 永久基本农田。
- 土壤质量或耕地质量等级。
- 生态保护红线或建设管制边界。
- 灌排、道路、田块工程可达性等工程约束。

这些图层当前在 `reward_calibration_template.yml` 中登记为 `data.extra_layers`。
真正把它们纳入奖励函数时，需要同步修改环境特征、采样标签和训练流程，不能只改
MPC 规划参数。

## 坐标系要求

面积、连片度和坡度约束应使用适合县域的投影坐标系。默认 `EPSG:32648` 只是模板；
真实项目应改为覆盖研究县域的投影 CRS 或自然资源部门内业统一 CRS。

