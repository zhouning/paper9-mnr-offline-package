# 自然资源部内网客户运行手册

适用版本：Python 包 `0.3.3`，算法 `paper9v2 2.2.3`，镜像
`paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64`。

## 1. 客户需要提供什么

每个县（区）只需要提供四个 File Geodatabase 目录路径：

1. 2025 地类图斑（DLTB）GDB。
2. 坡度图（PDT）GDB。
3. 生态保护红线（STBHHX）GDB。
4. 永久基本农田（YJJBNTBHTB）GDB。

不要求客户提供县名、图层名、坐标系参数、DEM 或 Python 环境。FileGDB 是以
`.gdb` 结尾的完整目录，不能只复制其中几个文件。

DLTB 生产编码按 `GB/T 21010-2017` 和第三次全国国土调查口径识别：耕地
`0101/0102/0103`、林地 `0301` 至 `0307`、园地 `0201` 至 `0204`。旧三位编码仅用于兼容
既有测试数据，不能与四位耕地/林地码混在同一县。系统若识别不到耕地或林地会直接失败，
不会再把全县静默归为 `Other`。

永久基本农田图层出现 `0103`、DLTB 出现 `1104` 并不表示编码体系冲突：两者在现行标准中
分别是旱地和坑塘水面。系统以 DLTB 编码判定地类，以永久基本农田图层的空间范围生成保护
锁定，不要求两个图层逐条编码相等。

交付包已携带覆盖四川省内江市东兴区和重庆市璧山区的 Copernicus DEM GLO-30
离线瓦片，以及从客户 `xiangzhen.shp` 提取的 44 个乡镇/街道行政参考面。容器全程以
`--network none` 运行，不下载数据，不安装 ArcPy，也不调用 ArcGIS。

## 2. 解包、校验和加载

```bash
tar -xzf paper9-mnr-offline-container-paper9v2-2.2.3-legacy-amd64.tar.gz
cd paper9-mnr-offline-container-paper9v2-2.2.3-legacy-amd64
sha256sum -c SHA256SUMS.txt
docker load -i images/paper9-mnr-offline-paper9v2-2.2.3-legacy-linux-amd64.tar
```

如果系统只提供 `shasum`，校验命令改为：

```bash
shasum -a 256 -c SHA256SUMS.txt
```

## 3. 一条命令融合一个县

首次已完成镜像加载后，以下四个值替换为客户实际 GDB 目录。融合命令只需要填写这四个
客户数据路径，不需要填写运行时、CPU 架构、镜像名、县名、图层名、CRS、DEM 或行政数据：

```bash
./bin/run-paper9-container.sh fuse \
  --dltb-gdb /客户数据/东兴区/DLTB.gdb \
  --pdt-gdb /客户数据/东兴区/PDT.gdb \
  --eco-redline-gdb /客户数据/东兴区/STBHHX.gdb \
  --permanent-basic-farmland-gdb /客户数据/东兴区/YJJBNTBHTB.gdb
```

脚本会自动完成：

- 检查四个路径并以只读方式挂载 GDB。
- 在每个 GDB 中自动选择唯一面图层；存在多个图层时按业务图层名和权威字段识别。
- 从 DLTB 行政代码或路径推断县区，不要求填写县名。
- 读取数据自身 CRS；面积计算自动沿用合格米制投影，否则推断当地 UTM。
- 从包内 DEM 计算连续坡度值；PDT 只比较坡度等级，不影响连续坡度、交换锁或优化结果。
- 根据 DLTB 县级代码从包内行政参考层自动选择东兴区 29 个或璧山区 15 个乡镇面。
- 叠加生态保护红线和永久基本农田，写入双向互换锁定字段。
- 生成 Paper9 主输入、行政名称参考层、约束审计层、坡度占位栅格和融合报告。
- 在宿主机逐一校验六个融合文件，并生成 `DATA_ROOT/FUSION_OUTPUTS.txt`。

未指定 `--data-root` 时，脚本会在当前目录的 `paper9-data/` 下按六位行政区码和 DLTB 路径
校验值生成独立目录，例如 `paper9-data/500120-1958875320/`，目录名不会再以 `-` 开头。
脚本在完成时打印实际绝对路径。融合完成后还会直接打印带正确 `DATA_ROOT`
和镜像名的 `check`、`dry-run`、`run`、`audit` 四条命令；现场人员按顺序复制执行即可。

处理璧山区时再次执行同一条最小命令，只替换四个 GDB 路径：

```bash
./bin/run-paper9-container.sh fuse \
  --dltb-gdb /客户数据/璧山区/DLTB.gdb \
  --pdt-gdb /客户数据/璧山区/PDT.gdb \
  --eco-redline-gdb /客户数据/璧山区/STBHHX.gdb \
  --permanent-basic-farmland-gdb /客户数据/璧山区/YJJBNTBHTB.gdb
```

自动目录会根据 DLTB 完整路径隔离两县。只有在客户运维要求成果固定写入指定数据盘时，
才额外增加 `--data-root /data/paper9/dongxing` 或 `--data-root /data/paper9/bishan`；两县不得
使用同一个 `data-root`。所有 `.gdb` 参数必须指向完整目录，路径包含空格时必须用双引号包住。

## 4. 融合后检查

先打开融合命令打印的 `DATA_ROOT/FUSION_OUTPUTS.txt`。其中六行 `file=` 均为宿主机绝对路径，
并附带 `size_bytes` 和 `sha256`。脚本只有在六个文件全部存在且非空时才会打印
`Fusion complete. Host outputs were verified.`。

`DATA_ROOT/input/` 应包含：

```text
DLTB_with_authority_slope.gpkg
admin_units.gpkg
authority_constraints.gpkg
DEM_placeholder.tif
fusion_summary.csv
fusion_report.json
```

必须打开 `fusion_report.json`，至少确认：

- `arcgis_or_arcpy_used` 为 `false`。
- `network_access_used` 为 `false`。
- `source.mode` 为 `four_sources`，四个路径和自动选择的图层均正确。
- `land_use_codes.scheme` 为 `gbt21010_2017_third_survey`，并核对 `code_counts`、
  `category_counts` 中耕地和林地数量不为零。
- `slope.null_count` 为 `0`；否则融合命令会直接失败。
- `constraints.exchange_locked_parcels`、红线重叠数和永久基本农田重叠数有记录。
- `dem.paths` 指向包内三个 GLO-30 瓦片，`cropped_to_dltb_bounds` 为 `true`。
- `pdt.role` 为 `quality_control_only`，三个 `affects_*` 字段均为 `false`。
- `administrative_reference.mode` 为 `bundled_township_spatial_reference`，县级代码和要素数正确。

`DEM_placeholder.tif` 由脚本自动生成，只满足 Paper9 的既有输入接口。真正的坡度已写入
DLTB 的 `slope_mean`，不需要也不能由客户手工复制 DEM 作为占位文件。

## 5. 正式运行

优先直接复制融合命令最后打印的四条命令。以下是等价格式，其中 `DATA_ROOT` 替换为融合
命令打印的实际路径：

```bash
./bin/run-paper9-container.sh check --data-root DATA_ROOT

./bin/run-paper9-container.sh dry-run --data-root DATA_ROOT

./bin/run-paper9-container.sh run --data-root DATA_ROOT

./bin/run-paper9-container.sh audit --data-root DATA_ROOT
```

`dry-run` 中应看到 `--slope-method from_field --slope-field slope_mean`、
`--reference-layer data/input/admin_units.gpkg` 和
`--cultivated-area-floor-delta-ha 0`。任何路径或字段检查失败时都不要执行 `run`。

## 6. 保护约束口径

生态保护红线是生态功能极重要或生态环境极敏感脆弱区域的强制性保护边界；永久基本农田
是为国家粮食安全划定、实行永久特殊保护的耕地。普通空间优化不等于行政审批、生态修复
审批或永久基本农田整改认定。

因此本版采用保守硬约束：DLTB 与任一保护层重叠超过 1 平方米时，写入
`EXCH_LOCK=1`、`LOCK_C2F=1`、`LOCK_F2C=1`，该图斑不参与耕地转林地，也不参与
林地转耕地。永久基本农田内出现现状林地、生态红线内出现现状耕地时只输出人工复核标记，
模型不会自动把它解释为允许整改。

## 7. 成果与验收

默认成果位于：

```text
DATA_ROOT/outputs/plan_paper9v22_authority_constraints/DLTB_optimized.shp
DATA_ROOT/outputs/plan_paper9v22_authority_constraints/mpc_summary.json
DATA_ROOT/outputs/audit_summary.json
DATA_ROOT/outputs/logs/
```

注意路径分工：`DATA_ROOT/input/` 是融合后供算法读取的中间输入；执行 `run` 后形成的最终优化
成果是 `DATA_ROOT/outputs/plan_paper9v22_authority_constraints/DLTB_optimized.shp`。

发生成功或失败都要保留整个 `DATA_ROOT/outputs/logs/`，其中包括：

```text
container-wrapper-*.log
authoritative_fusion-*.log
authoritative_fusion-*.jsonl
authoritative_fusion-*-failure.json      仅失败时生成
run_full_pipeline-*.log
run_full_pipeline-*.json
*-prepare.log / *-sample.log / *-train.log / *-plan.log / *-audit.log
```

向外网支持人员反馈问题时，除敏感数据外应整体带回该日志目录和 `input/fusion_report.json`，
不要只截取终端最后一行。可读日志用于快速定位，JSONL 和 manifest 用于还原阶段、参数、
库版本、图层字段、CRS、范围、数据量、几何修复、DEM 窗口、约束统计、输出哈希及耗时。

`audit_summary.json` 的三项默认硬门禁必须全部通过：县域耕地面积不减少、耕地平均坡度
降低、连片度上升。百亩方数量和面积作为报告与优化指标，不是默认硬门禁。

本地单元测试、模拟数据和镜像验证不能替代客户真实四个 GDB 的正式验收。两县都应分别
保留融合报告、运行 manifest、审计摘要、最终矢量及整套 SHA-256 记录。

## 8. 常见失败

- `not a FileGDB directory`：传入的不是完整 `.gdb` 目录，或容器运行用户没有读取权限。
- `Cannot identify`：一个 GDB 存在多个候选面图层且字段也无法唯一判定，应先由数据提供方
  清理该 GDB；客户正常流程不填写图层名。
- `no local DEM slope`：图斑超出随包 DEM 范围或落在 NoData，脚本不会用全县中位数填充。
- `DLTB ... field`：客户字段与已提供的权威结构不一致，应记录真实字段清单后更新融合版本，
  不能现场随意映射。
- `mixed current four-digit and legacy three-digit`：同一 DLTB 混用了现行四位和旧测试三位
  耕地/林地码，必须由数据提供方统一后重跑。
- `no recognized farmland/forest codes`：地类编码不符合当前契约，先核对 `DLBM` 原始值和标准，
  不得绕过校验继续优化。
- Docker 权限错误：由客户运维配置 Docker 用户组或按其制度使用 `sudo`，不要改变数据权限
  或把四个 GDB 复制进镜像。
