# 02 数据契约

本工程包默认服务自然资源部真实图斑数据。关键前提是：图斑已经自带权威坡度字段，
不再从公开 DEM 重新计算坡度。

## 必需输入

自然资源部离线部署场景下，客户侧需要提供两类业务输入：

1. 带权威坡度字段的 DLTB 地类图斑。
2. 可细化到村级的全国行政区数据。

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

### 村级行政区图层

支持 GeoPackage、Shapefile、GeoJSON 等 GeoPandas 可读取格式。推荐 GeoPackage。
该图层用于把 DLTB 权属单位代码映射为可读行政名称，并支撑按行政区解释结果。

推荐路径：

```text
data/input/admin_units.gpkg
```

必需字段：

- `XZQDM`: 行政区代码；建议包含村/社区级代码，并能与 DLTB 的 `QSDWDM` 前缀对应。
- `XZQMC`: 行政区名称；用于日志、`townships.json` 和结果解释。
- `geometry`: 面几何，必须有 CRS，且覆盖 DLTB 项目区。

建议字段：

- `admin_level`: 行政层级。
- `admin_parent_code`: 上级行政区代码。

配置示例：

```yaml
data:
  admin_units: data/input/admin_units.gpkg

fields:
  admin_name: XZQMC
```

如果行政区名称字段不是 `XZQMC`，修改 `fields.admin_name`。正式部署时应使用自然
资源部权威行政区数据，不应使用本机验证阶段从 DLTB dissolve 出来的代理数据。

### DEM 占位文件

Paper9 原始 `prepare` 接口保留了 `--dem` 参数。使用 `slope.source: field` 时，坡度
来自图斑字段，不使用 DEM 计算坡度。配置中仍保留 `data.dem`，用于兼容原接口。

因此客户侧业务输入仍是 DLTB 和行政区两项；`DEM_placeholder.tif` 是部署侧准备的
技术占位文件。

## 可选扩展业务图层

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
