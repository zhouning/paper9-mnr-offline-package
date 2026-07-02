# 09 自然资源部客户运行手册

本文面向离线包部署到自然资源部纯内网后的实际操作人员，回答三件事：

1. 客户需要准备哪些数据。
2. 离线包怎么运行。
3. 运行完成后有哪些成果。

如果采用 Docker/Podman 镜像交付，并需要同时说明命令行批处理模式和 Notebook 扩展模式，
先阅读 `docs/14_dual_mode_image_usage.md`。

针对当前自然资源部提供的机器，默认按以下口径部署：

```text
deepin server 16
x86_64
Docker 已重新允许
使用 paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
镜像 paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64
```

如果某台机器尚未安装 Docker，先按 `docs/12_container_runtime_airgap.md` 准备
deepin server 16/CentOS7 兼容的 x86_64 Docker 离线安装包。不要在这批机器上使用 arm64 包，
也不要继续使用历史 `paper9v2-2.0.0-amd64` 镜像。

当前 `paper9v2.1 legacy-amd64` 候选交付包已在本机 Docker 真实数据 E2E 和 Windows Intel
源码重建测试中通过。验证报告见
`docs/reports/paper9v21_legacy_amd64_e2e_20260701/REPORT.md`。

## 一、客户需要提供的数据

客户侧只需要提供两类业务输入数据，建议统一放到 `data/input/`。

### 1. 带权威坡度字段的 DLTB 地类图斑

推荐文件名：

```text
data/input/DLTB_with_authority_slope.gpkg
```

推荐使用 GeoPackage。Shapefile 也可读，但字段名容易被截断，正式交付不建议优先使用。

必需字段：

| 字段 | 含义 | 要求 |
| --- | --- | --- |
| `DLBM` | 地类编码 | 用于识别耕地、林地和其他地类。 |
| `QSDWDM` | 权属单位代码 | 前 9 位用于乡镇/街道分组；如自然资源部数据可到村级，建议保留完整村级代码。 |
| `BSM` | 图斑唯一标识 | 每个图斑应唯一。 |
| `slope_mean` | 权威坡度 | 单位应为度；字段名可在配置中改。 |
| `geometry` | 面几何 | 必须有有效 CRS，建议为适合项目区面积计算的投影坐标系。 |

如真实字段名不同，在配置中修改：

```yaml
fields:
  dlbm: DLBM
  qsdwdm: QSDWDM
  bsm: BSM

slope:
  source: field
  field: slope_mean
```

### 2. 可细化到村级的全国行政区数据

推荐文件名：

```text
data/input/admin_units.gpkg
```

该数据用于把 DLTB 中的行政代码映射为可读行政单元名称，并支撑后续按行政区解释成果。正式环境应使用自然资源部提供的权威行政区数据，不要使用测试代理数据。

必需字段：

| 字段 | 含义 | 要求 |
| --- | --- | --- |
| `XZQDM` | 行政区代码 | 建议包含村/社区级代码；应能与 DLTB 的 `QSDWDM` 前缀对应。 |
| `XZQMC` | 行政区名称 | 用于 `townships.json`、日志和成果解释中的行政区名称。 |
| `geometry` | 行政区面几何 | 必须覆盖 DLTB 项目区。 |

可选但建议保留字段：

| 字段 | 含义 |
| --- | --- |
| `admin_level` | 行政层级，如 province/city/county/town/village。 |
| `admin_parent_code` | 上级行政区代码。 |

如行政区名称字段不是 `XZQMC`，在配置中修改：

```yaml
data:
  admin_units: data/input/admin_units.gpkg

fields:
  admin_name: XZQMC
```

### 技术占位文件：DEM

当前 MNR 离线包默认从 DLTB 字段读取权威坡度，不重新用 DEM 计算坡度。由于原 Paper9 prepare 接口保留 `--dem` 参数，配置中仍需要：

```yaml
data:
  dem: data/input/DEM_placeholder.tif
```

这是接口占位文件，不是客户需要提供的第三个业务输入。部署人员可随包放置一个合法的小 GeoTIFF 占位文件。

## 二、Docker 镜像离线包运行过程（当前推荐）

### 1. 解包和校验

```bash
tar -xzf paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
cd paper9-mnr-offline-container-legacy-amd64-20260701
sha256sum -c SHA256SUMS.txt
```

如系统提供的是 `shasum`：

```bash
shasum -a 256 -c SHA256SUMS.txt
```

### 2. 加载镜像

```bash
docker load -i images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
```

### 3. 准备数据目录

```bash
sudo mkdir -p /data/paper9/input /data/paper9/working /data/paper9/outputs
sudo chown -R "$USER":"$USER" /data/paper9
```

放入数据：

```text
/data/paper9/input/DLTB_with_authority_slope.gpkg
/data/paper9/input/admin_units.gpkg
/data/paper9/input/DEM_placeholder.tif
```

### 4. 检查、预演、运行和审计

```bash
./bin/run-paper9-container.sh check \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh dry-run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh run \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9

./bin/run-paper9-container.sh audit \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

确认 `dry-run` 中 `prepare` 命令包含：

```text
--slope-method from_field --slope-field slope_mean
--reference-layer data/input/admin_units.gpkg --reference-name-field XZQMC
```

### 5. Notebook 扩展模式

```bash
./bin/run-paper9-container.sh notebook \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9 \
  --notebook-port 8888 \
  --notebook-token paper9
```

浏览器访问：

```text
http://服务器IP:8888/lab?token=paper9
```

Notebook 只作为输入核查、过程解释、日志查看和地图可视化入口。正式生产运行仍以
`check -> dry-run -> run -> audit` 为准。

## 三、原生 Python 离线包运行过程（备用）

本节只适用于目标 Linux 已额外交付并验证 Python/GDAL/Torch/ONNX Runtime 运行时包的情况。
当前 Docker 交付不需要在目标机直接运行这些 Python 命令。

### 1. 环境检查

在离线包根目录执行：

```powershell
python scripts\00_check_env.py --no-heavy
python scripts\00_check_env.py
python -m pytest tests -q
```

`--no-heavy` 做轻量检查；完整检查会导入 GeoPandas、Rasterio、Torch、ONNX Runtime 等依赖。

### 2. 检查配置

默认 Paper9v2.1 业务约束配置：

```powershell
python -m paper9_mnr.cli check-config configs\paper9v2_no_net_loss_authority_slope.yml
```

带耕地面积和百亩方面积不降低约束的配置：

```powershell
python -m paper9_mnr.cli check-config configs\no_net_loss_authority_slope.yml
```

### 3. 先打印命令，不直接运行

```powershell
python scripts\run_full_pipeline.py configs\paper9v2_no_net_loss_authority_slope.yml --dry-run
```

确认 `prepare` 命令中包含：

```text
--slope-method from_field --slope-field slope_mean
--reference-layer data/input/admin_units.gpkg --reference-name-field XZQMC
```

### 4. 正式运行完整流程

```powershell
python scripts\run_full_pipeline.py configs\paper9v2_no_net_loss_authority_slope.yml
```

完整流程包括：

| 阶段 | 脚本 | 作用 |
| --- | --- | --- |
| prepare | `scripts\01_prepare.py` | 读取 DLTB、权威坡度和行政区参考层，生成图斑块与县域环境输入。 |
| sample | `scripts\02_sample.py` | 采样状态、动作、奖励标签。 |
| train | `scripts\03_train.py` | 训练 Paper9 world model ensemble，并导出 ONNX。 |
| plan | `scripts\04_plan.py` | 使用 MPC 生成地类空间布局优化方案。 |

如果需要分步排查，可按顺序运行：

```powershell
python scripts\01_prepare.py configs\paper9v2_no_net_loss_authority_slope.yml
python scripts\02_sample.py configs\paper9v2_no_net_loss_authority_slope.yml
python scripts\03_train.py configs\paper9v2_no_net_loss_authority_slope.yml
python scripts\04_plan.py configs\paper9v2_no_net_loss_authority_slope.yml
python scripts\05_audit.py configs\paper9v2_no_net_loss_authority_slope.yml --write
```

修改 reward、约束或业务偏好后，应至少重新运行 `sample -> train -> plan`，不能只用旧模型重跑 `plan`。

## 四、运行后的成果

### 1. 对外主要成果

默认 Paper9v2.1 配置输出：

```text
outputs/plan_paper9v2_no_net_loss/DLTB_optimized.shp
outputs/plan_paper9v2_no_net_loss/mpc_summary.json
outputs/audit_summary.json
```

`DLTB_optimized.shp` 是优化后的 DLTB 图斑成果，保留原始图斑属性，并新增优化字段：

| 字段 | 含义 |
| --- | --- |
| `ORIG_DLBM` | 原始地类编码。 |
| `OPT_DLBM` | 优化建议后的地类编码。 |
| `OPT_DLMC` | 优化建议后的地类名称。 |
| `CHG_FLAG` | 0=不变，1=耕地转林地，2=林地转耕地。 |

### 2. 指标摘要

`mpc_summary.json` 记录本次规划参数和核心指标，包括：

- 平均坡度变化。
- 连片性变化。
- 百亩方面积变化。
- MPC 步数。
- 输入图斑数、进入县域环境的图斑数。
- 耕地转林地数量、林地转耕地数量、不变数量。

`outputs/audit_summary.json` 记录关键产物是否存在，适合做文件级交付检查。
其中 `constraint_status.hard_constraint_passed` 必须为 `true`，并应记录耕地面积、
坡度和连片度三项 hard gate。

### 3. 中间过程产物

```text
data/working/prepared_paper9v2_no_net_loss/dem_slope_analysis/output/DLTB_with_slope.shp
data/working/prepared_paper9v2_no_net_loss/townships.json
data/working/prepared_paper9v2_no_net_loss/results_real/blocks/
data/working/prepared_paper9v2_no_net_loss/tool2/transitions.npz
data/working/prepared_paper9v2_no_net_loss/tool2/pairwise.npz
data/working/prepared_paper9v2_no_net_loss/tool3/
```

这些产物用于复核流程、复现实验和后续模型重训。正式交付时建议与配置文件一起归档，保证结果可追溯。

## 五、交付前检查清单

- DLTB 和行政区数据均来自客户权威数据源。
- DLTB、行政区和 DEM 占位文件均有 CRS，且配置中的 `crs` 与项目区投影坐标系一致。
- `check-config` 通过。
- `run_full_pipeline.py --dry-run` 中 prepare 命令包含行政区参考图层参数。
- `scripts\05_audit.py <config> --write` 显示关键成果均存在。
- 对 `DLTB_optimized.shp` 做面积、坡度、连片度、百亩方、行政区分组和硬约束复核。
