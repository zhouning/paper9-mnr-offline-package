# 02 数据契约

## 客户原始输入

Paper9v2.2.3 的内网现场入口按县接收四个独立 FileGDB 目录：

1. 2025 地类图斑 DLTB。
2. 坡度图 PDT。
3. 生态保护红线 STBHHX。
4. 永久基本农田 YJJBNTBHTB。

四个图层都必须是带 CRS 的面数据。客户不提供 DEM、县名、图层名或 CRS 参数。融合器
支持用户给出的中英文字段，例如 DLTB 的 `标识码/BSM`、`地类编码/DLBM`、
`地类名称/DLMC`、`权属单位代码/QSDWDM`，以及 PDT 的 `PDJB`、`BZPDJB`。

DLTB 必须满足：标识码非空且唯一，地类编码非空，权属或坐落单位代码至少可提取乡镇分组，
几何非空。一个 GDB 只有一个面图层时自动采用；多个候选无法唯一识别时失败。

生产编码按 `GB/T 21010-2017` 和第三次全国国土调查口径识别：耕地为
`0101/0102/0103`，林地为 `0301` 至 `0307`，园地为 `0201` 至 `0204`。编码字段按
标准保留最多五位原值，分类使用前四位基码，不再强制转换成三位。旧测试数据的
`011/012/013`、`031/032/033` 仍可单独识别，但不得与现行四位耕地/林地码混用；缺少可识别
耕地或林地时融合直接失败。

例如永久基本农田图层某要素的地类编码为 `0103`，DLTB 另一要素为 `1104`，两者都是现行
标准中的合法编码，分别表示旱地和坑塘水面，并不要求值相等。Paper9 只用 DLTB 的 `DLBM`
判定现状地类；永久基本农田层按空间叠加生成保护锁，不用其地类编码覆盖 DLTB。

## 包内 DEM

交付包携带 Copernicus DEM GLO-30 `N29E104/N29E105/N29E106` 三个离线瓦片。
PDT 的 `PDJB/BZPDJB` 是坡度等级，只用于与 DEM 推导等级质检，不能写成连续坡度值，
也不参与交换锁定、优化目标或候选图斑筛选。
任何 DLTB 图斑无法获得 DEM 坡度时，融合失败，不用中位数填充。

## 融合后的 Paper9 输入

融合器在每县 `data-root/input` 自动生成：

```text
DLTB_with_authority_slope.gpkg
admin_units.gpkg
authority_constraints.gpkg
DEM_placeholder.tif
fusion_summary.csv
fusion_report.json
```

上述六项是正式运行前的融合输入，不是最终优化矢量。宿主机包装脚本确认六项均存在且非空
后，在 `DATA_ROOT/FUSION_OUTPUTS.txt` 写入每项绝对路径、字节数和 SHA-256；最终优化成果在
`DATA_ROOT/outputs/plan_paper9v22_authority_constraints/`。

`DLTB_with_authority_slope.gpkg` 的 `dltb` 图层至少包含：

- `BSM`：图斑唯一标识。
- `DLBM`：地类编码。
- `DLMC`：地类名称。
- `QSDWDM`：权属/行政分组代码。
- `QSDWMC`：可读名称。
- `slope_mean`：DEM 计算的平均坡度，单位为度。
- `EXCH_LOCK`：`1` 表示不得参与耕地与林地双向自动互换。
- `LOCK_RSN`：`ECO_REDLINE`、`PERMANENT_BASIC_FARMLAND` 或两者。

`admin_units.gpkg` 优先从包内 `xiangzhen_dongxing_bishan.gpkg` 选择当前县的乡镇面，
为名称映射接口提供 `XZQDM/XZQMC`。包内参考层包含东兴区 29 个、璧山区 15 个乡镇/
街道面，源日期为 2021-06-22。源数据没有乡镇代码，`XZQDM` 由运行时 DLTB 最大重叠
关系关联；该层仅作名称和空间参考，不参与保护约束，须结合客户 2025 年行政区资料复核。

`DEM_placeholder.tif` 是融合器生成的合法接口占位栅格。prepare 使用
`slope.source: field` 和 `slope_mean`，不会再次从该占位文件计算坡度。

## 保护层规则

DLTB 与生态保护红线或永久基本农田重叠超过 1 平方米时，写入
`EXCH_LOCK=1`、`LOCK_C2F=1`、`LOCK_F2C=1`。锁定图斑参与现状和结果统计，
但从 sampling 和 MPC 互换候选中排除，成果写出前再次检查未改变。

永久基本农田内的现状林地、生态红线内的现状耕地只标记人工复核，不由算法自动解释为
可以整改或转换。

## 坐标系

融合器读取各图层自身 CRS，并在叠加时转换。面积分析优先使用 DLTB 自身的米制投影；如果
DLTB 是地理坐标，则自动估算当地 UTM。客户现场不填写 CRS。推断结果、图层原始 CRS 和
DEM CRS 都记录在 `fusion_report.json`，正式验收时应核对。

## 配置映射

默认配置固定读取融合输出：

```yaml
data:
  dltb: data/input/DLTB_with_authority_slope.gpkg
  admin_units: data/input/admin_units.gpkg
  dem: data/input/DEM_placeholder.tif

slope:
  source: field
  field: slope_mean

fields:
  dlbm: DLBM
  qsdwdm: QSDWDM
  bsm: BSM
  exchange_lock: EXCH_LOCK
```

修改输入、保护策略、奖励或约束后，应重新执行 `sample -> train -> plan -> audit`，不能只用
旧模型重跑规划并解释为新规则结果。
