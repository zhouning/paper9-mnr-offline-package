# Paper9v2.3 中宁县 DLTB-only 版本说明

## 1. 版本决定

本次不直接复用 Paper9v2.2.3 四源数据模式，而是新增：

- Python 包版本：`0.4.0`；
- 算法版本：`paper9v2 2.3.0`；
- 输入模式：`dltb_dem_only`；
- 证据等级：`exploratory_data_limited`；
- 允许用途：`exploratory_technical_validation_only`。

原因是当前只有地类图斑，缺少坡度图、生态保护红线和永久基本农田。继续使用四源模式会造成
“三类数据已检查”的错误印象。v2.3 在配置、融合报告和审计报告中显式保留缺失状态。

Paper9v2.2.3 的四源融合仍受支持，没有被 v2.3 删除或改变。

## 2. 输入和内置数据

客户现场只提供自治区级 DLTB。数据必须包含可用于筛选中宁县的六位行政区代码前缀
`640521`，优先识别 `QSDWDM`、`ZLDWDM`、权属单位代码或坐落单位代码字段。

离线包内置：

- Copernicus DEM GLO-30 四幅：`N36E105`、`N36E106`、`N37E105`、`N37E106`；
- 中宁县 13 个乡镇面行政参考，图层为 `admin_reference`，坐标系为 `EPSG:4326`；
- 默认配置 `configs/paper9v23_zhongning_dltb_only.yml`。

DEM 是 30 m 数字表面模型。程序通过 Horn 3x3 算法计算连续坡度，再聚合到每个 DLTB 图斑的
`slope_mean` 和 `slope_max`。它能支持本次技术验证，但不能等同于自然资源主管部门提供的法定坡度图。

DEM 来源、范围和逐文件校验值见
`dist/dem/copernicus_glo30_zhongning/DEM_MANIFEST.json`；行政参考见
`reference/admin/MANIFEST_ZHONGNING.json`。

为便于在另一台 Windows 机器上复核，包还内置两套样例 DLTB：

- `datasets/dongxing/DLTB_with_slope.gpkg`：共 134369 个图斑，其中 134368 个图斑属于筛选码 `511011`，推荐作为首个验证集；
- `datasets/bishan/DLTB_with_slope.gpkg`：101657 个图斑，源数据主码为旧码 `500227`，当前行政参考为 `500120`。

两套样例的文件校验值、DEM 瓦片和行政参考关系见 `dist/datasets/MANIFEST.json`。样例仍属于
`dltb_dem_only` 探索性数据，不包含 PDT、生态红线或永久基本农田。

规划输出的 `OPT_DLBM` 会自动保持输入 DLTB 的地类编码体系：三位旧码样例使用 `011/031`，
国标四位地类数据使用 `0101/0301`。如现场有明确编码要求，也可通过
`--farm-dlbm` 和 `--forest-dlbm` 显式覆盖；程序不会静默混用两套编码。

## 3. 缺失约束的处理

v2.3 不推测、不模拟也不补造缺失的管控数据：

| 数据 | 输出状态 | 处理 |
|---|---|---|
| 坡度图 PDT | `not_provided_not_evaluated` | 仅使用内置 DEM 计算连续坡度，不做 PDT 等级一致性检查 |
| 生态保护红线 | `not_provided_not_evaluated` | 不生成红线相交锁定 |
| 永久基本农田 | `not_provided_not_evaluated` | 不生成基本农田相交锁定 |

融合后的 `EXCH_LOCK`、`LOCK_C2F` 和 `LOCK_F2C` 均为零，含义是“没有可用证据进行锁定”，
不是“已核查且不存在限制”。`CONSTR_STA` 固定为 `NOT_EVALUATED`。

模型仍执行三项内部技术门槛：耕地面积不减少、耕地平均坡度下降、连片度上升。即便三项通过，
也不能形成生态红线、永久基本农田或国土空间用途管制合规结论。

## 4. 运行产物

融合阶段额外写出：

- `input/input_availability.json`：输入可用性和用途限制；
- `input/fusion_report.json`：县域筛选、DEM、行政参考、缺失约束和校验值；
- `input/DLTB_with_authority_slope.gpkg`：带 DEM 坡度和显式缺失状态的图斑；
- `input/admin_units.gpkg`：由 DLTB 与内置乡镇参考建立的运行行政单元。

审计结果 `outputs/audit_summary.json` 包含 `input_profile_status`，其中
`regulatory_compliance_claim_allowed` 必须为 `false`。

## 5. 验证状态

截至 2026-08-08：

- 四幅 DEM 已完成字节数、SHA-256、CRS、分辨率、范围和波段校验；
- 中宁县行政参考已验证 13 个有效面、行政区代码 `640521` 和 `EPSG:4326`；
- DLTB-only 融合已通过合成数据测试；
- 已选择内江市东兴区完成本机真实数据冒烟验证：筛出 134368 个 `511011` 图斑，使用
  `N29E104`、`N29E105` 两幅内置 DEM 计算坡度，134368 个图斑均取得坡度值，并匹配
  29 个内置乡镇行政面；
- 在同一份东兴融合结果上，Windows x64 已完成默认参数的 `prepare -> sample -> train -> plan -> audit`：
  6000 条 transition、1000 个 pairwise states（每个 50 个动作）、3 个 ensemble member、100 步 MPC。
  审计确认全部期望输出存在，硬约束通过，耕地面积变化 `+392.60 ha`、平均坡度变化 `-0.3457%`、
  连片度变化 `+0.0487`，farm -> forest 和 forest -> farm 均为 479；
- Windows 原生运行时已在独立 Windows x64 机器上完成 `check`，Python `3.11.15`、GDAL、Rasterio、
  PyTorch、ONNX Runtime 导入通过，完整 pytest 为 `117 passed`；
- 本机 `/Users/zhouning/Downloads/宁夏` 只有 Excel 清单，没有实际 DLTB 空间数据；
- 正式中宁县端到端运行仍需现场 DLTB；
- Windows x64 运行时必须在联网 Windows x64 构建机上生成并做一次冒烟测试，不能在 macOS 上交叉生成。

Windows 构建和现场步骤见 `docs/22_windows_native_airgap.md`。
