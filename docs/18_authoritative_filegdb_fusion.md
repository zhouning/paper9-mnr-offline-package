# 客户权威 FileGDB 融合设计

## 1. 目标输入结构

Paper9 当前自带 `DLTB_with_authority_slope.gpkg` 的业务图层为 `dltb`，面几何，核心字段为
`BSM`、`DLBM`、`DLMC`、`QSDWDM`、`QSDWMC`、`slope_mean`。其中
`slope_mean` 是角度制连续平均坡度，不是坡度等级。`admin_units.gpkg` 的图层为
`admin_units`，核心字段为 `XZQDM` 和 `XZQMC`。

融合器保留客户 DLTB 原始字段，并补齐 Paper9 精确字段名和以下审计字段：

```text
slope_mean, slope_max, slope_pixel_count, slope_assignment
PDT_PDJB, PDT_BZPDJB, PDT_OV_PCT, PDT_GRADE, DEM_GRADE, GRD_MATCH
ECO_OV_M2, ECO_PCT, PBF_OV_M2, PBF_PCT
LOCK_C2F, LOCK_F2C, EXCH_LOCK, LOCK_RSN, REVIEW_REQ, REVIEW_RSN
```

## 2. 现场输入契约

每个县区输入四个独立 FileGDB 目录：DLTB、PDT、生态保护红线、永久基本农田。正常现场
调用不接受也不需要县名、图层名、CRS 或 DEM 参数。

自动识别规则如下：

1. GDB 中只有一个面图层时直接选用，不依赖图层名称。
2. 有多个面图层时，按 `DLTB/地类图斑`、`PDT/坡度`、`STBHHX/生态保护红线`、
   `YJJBNT.../永久基本农田` 名称及已知字段评分。
3. 无法唯一判定时失败，不猜测、不静默选第一个图层。
4. 县区优先从 DLTB 县级行政代码推断；`511011` 映射东兴区，`500120` 映射璧山区。
5. 面积计算优先使用数据自身合格的米制投影；地理坐标数据自动推断当地 UTM。

旧的单容器 API `--source` 仍保留用于回归测试和兼容已有自动化，但不是客户现场主流程。

## 3. DEM 与 PDT 的职责

PDT 的 `PDJB`、`BZPDJB` 是坡度分级描述，不能作为 Paper9 的连续 `slope_mean`。
本交付包固定携带 Copernicus DEM GLO-30 的以下三个离线 COG：

```text
N29E104
N29E105
N29E106
```

它们覆盖东兴区、璧山区所在范围。实际来源 URL、文件字节数、SHA-256、栅格边界、产品
说明与归属信息记录在 `dem/copernicus_glo30/DEM_MANIFEST.json`。

融合时先把 DLTB 转到 DEM CRS，只读取县域外扩三个像元后的窗口，避免在内存中展开三个
整瓦片。随后使用 Horn 3x3 算子计算角度制坡度，按 DLTB 图斑统计均值和最大值。没有像元
中心的微小图斑使用内部代表点附近像元；仍无法获得坡度的任一图斑都会使融合失败，不使用
中位数或 PDT 等级填充。

PDT 与 DLTB 按最大重叠面积匹配，并把 PDT 等级与 DEM 坡度推导等级比较。默认分级为
`<=2`、`(2,6]`、`(6,15]`、`(15,25]`、`>25` 度。`GRD_MATCH` 只用于质量检查，
不覆盖 DEM 连续坡度。PDT 不参与 `EXCH_LOCK`、模型奖励、候选筛选或最终地类决策；保留
它的意义是发现客户权威等级与 DEM 结果之间需要人工解释的差异。

## 4. 包内行政区参考

客户提供的全国 `xiangzhen.shp` 共 43,655 条。本包筛出东兴区 29 条、璧山区 15 条，生成
`reference/admin/xiangzhen_dongxing_bishan.gpkg`，融合时根据 DLTB 县级代码自动选县。
该层源日期为 2021-06-22，仅用于乡镇中文名称和空间归属；源数据没有乡镇代码，输出
`XZQDM` 由 DLTB 最大重叠关系关联。它不参与红线、永久基本农田或耕地林地互换约束，且
需要结合客户 2025 年行政区资料复核可能的乡镇撤并变化。

源数据中璧山区青杠街道包含一个位于约 `107.49E, 30.76N` 的远距离分离面，内置参考层
已移除该离群面并保留璧山区主体范围内的青杠街道面；修复前后范围记录在参考层 manifest。

## 5. 保护区约束

生态保护红线对生态功能极重要、生态环境极敏感脆弱区域实行强制性严格保护。永久基本农田
是为保障国家粮食安全依法划定、实行永久特殊保护的耕地。Paper9 的一般耕地林地布局优化
不构成行政审批、生态修复许可或永久基本农田整改认定。

默认规则是：DLTB 与生态红线或永久基本农田重叠面积大于 1 平方米即双向锁定，既不允许
耕地自动转林地，也不允许林地自动转耕地。锁定图斑仍参与县域现状和成果统计，但从采样与
MPC 互换候选中排除；成果写出前再次检查其地类未改变。

以下冲突只进入人工复核：

- 永久基本农田与现状林地重叠：`FOREST_OVERLAPS_PERMANENT_BASIC_FARMLAND`。
- 生态红线与现状耕地重叠：`CULTIVATED_LAND_IN_ECO_REDLINE`。

有明确审批或专项整治规则时，应另行形成经主管部门确认的版本与白名单，不能临时修改默认
锁定结果后仍沿用本版算法标识。

## 6. 容器调用

```bash
./bin/run-paper9-container.sh fuse \
  --dltb-gdb /path/to/dltb.gdb \
  --pdt-gdb /path/to/pdt.gdb \
  --eco-redline-gdb /path/to/stbhhx.gdb \
  --permanent-basic-farmland-gdb /path/to/yjjbntbhtb.gdb
```

四个 GDB 和 DEM 目录只读挂载，`data-root/input` 在融合动作中可写，容器网络关闭。普通
`check/dry-run/run/audit` 动作重新把 input 只读挂载。未指定 `--data-root` 时 wrapper 根据
DLTB 完整路径自动建立县级隔离目录，并打印后续四条完整命令。

## 7. 高级 Python API

容器 wrapper 是正式客户入口。开发和诊断环境可直接调用：

```bash
python scripts/fuse_authoritative_county_inputs.py \
  --dltb-gdb /path/to/dltb.gdb \
  --pdt-gdb /path/to/pdt.gdb \
  --eco-redline-gdb /path/to/stbhhx.gdb \
  --permanent-basic-farmland-gdb /path/to/yjjbntbhtb.gdb \
  --dem /offline/dem/N29E104.tif /offline/dem/N29E105.tif /offline/dem/N29E106.tif \
  --admin-reference /offline/reference/xiangzhen_dongxing_bishan.gpkg \
  --output-dir data/input
```

该入口同样只使用 GDAL/OpenFileGDB、GeoPandas、Pyogrio、Shapely、Rasterio 和 PyProj，
不包含 ArcPy 代码路径，也不执行网络下载。

## 8. 输出、日志和审计

```text
DLTB_with_authority_slope.gpkg   Paper9 主输入，图层 dltb
admin_units.gpkg                 包内乡镇空间参考生成的名称参考层
authority_constraints.gpkg      PDT、红线、永久基本农田及锁定图斑
DEM_placeholder.tif              自动生成的合法接口占位栅格
fusion_summary.csv               分地类数量、面积、锁定数量
fusion_report.json               来源、自动识别、CRS、DEM、统计、策略和输出 SHA-256
```

`DATA_ROOT/outputs/logs/` 同时保存宿主机 wrapper 日志、融合可读日志、逐事件 JSONL、
失败诊断 JSON，以及完整流水线各阶段日志和 manifest。融合日志记录源目录文件数与大小、
图层候选和字段、CRS、范围、几何修复、DEM 窗口、坡度统计、约束命中、输出哈希及耗时。
发生异常时失败 JSON 保留异常类型、消息、traceback、运行库版本和当次参数。

由于仓库不持有客户真实 GDB，本版只能完成模拟四源、OpenFileGDB 驱动、镜像和脚本验证；
东兴区、璧山区真实权威数据的端到端结果必须在客户内网分别验收。
