# 06 常见问题

## 找不到 `paper9_mnr`

未安装包或没有设置 `PYTHONPATH`。推荐在工程根目录执行：

```powershell
python -m pip install -e .
```

也可以直接使用 `scripts/*.py`，这些脚本会自动把 `src/` 加入路径。

## GDAL/PROJ/Rasterio 导入失败

通常是 DLL 或数据目录不一致。优先使用同一个 conda-forge 环境安装 GeoPandas、
Rasterio、Fiona、PyProj。不要混用 ArcGIS Pro 自带 GDAL 和 conda/pip 的 Rasterio。

## `slope.field` 缺失

真实数据默认要求图斑自带权威坡度字段：

```yaml
slope:
  source: field
  field: slope_mean
```

如果部里字段名不是 `slope_mean`，改为真实字段名。

## dry-run 中没有 `--reference-layer`

正式自然资源部输入应包含村级行政区图层。检查配置是否包含：

```yaml
data:
  admin_units: data/input/admin_units.gpkg

fields:
  admin_name: XZQMC
```

然后重新运行：

```powershell
python scripts\run_full_pipeline.py <config> --dry-run
```

`prepare` 命令应出现 `--reference-layer` 和 `--reference-name-field`。

## 行政区名称没有正确映射

常见原因：

- 行政区图层没有 `XZQDM` 或名称字段。
- `fields.admin_name` 与真实名称字段不一致。
- DLTB 的 `QSDWDM` 前缀与行政区 `XZQDM` 编码体系不一致。
- 行政区图层没有覆盖 DLTB 项目区。
- 行政区图层或 DLTB 缺失 CRS，导致空间匹配失败。

优先确认 `data/working/prepared/townships.json` 中的名称是否来自行政参考层。

## Phase B 生成 0 个 block

常见原因：

- `QSDWDM` 前 9 位不能形成足够图斑的乡镇组。
- `min_parcels_per_township` 对测试小样本过高。
- DLBM 中缺少耕地或林地编码。
- 图斑几何无效或 CRS 错误。

小样本调试可把 `min_parcels_per_township` 降低到 3 到 10。

## 只改 reward 后 plan 结果没有明显变化

这是预期风险。Paper9 的模型偏好来自采样和训练阶段。改 reward 后必须重新：

```powershell
python scripts\02_sample.py <config>
python scripts\03_train.py <config>
python scripts\04_plan.py <config>
```

## Python 版本问题

建议使用 Python 3.11。当前工程元数据限定为 `>=3.11,<3.13`，因为 GIS 和 Torch 依赖
在 Python 3.11 上最稳。
