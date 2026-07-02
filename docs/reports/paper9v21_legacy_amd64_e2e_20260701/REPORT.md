# Paper9v2.1 Legacy AMD64 Docker E2E 验证报告

日期：2026-07-01  
对象：`paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64`  
用途：自然资源部 deepin server 16 / 老 x86_64 CPU 内网测试候选包

## 结论

`paper9v2.1 legacy-amd64` 离线部署包已完成本机 Docker 真实数据端到端验证，
并已在 Windows Intel Docker 环境完成从 GitHub 源码重新构建后的测试。当前可作为
自然资源部内网下一轮测试候选包继续交付，但最终验收仍应以自然资源部内网目标机器上的
`check -> dry-run -> run -> audit` 结果为准。

本次 legacy amd64 版本针对现场 `lscpu` 显示缺少 `sse4_1` 和 `popcnt` 的 x86_64
CPU 重新制作。容器内 NumPy SIMD baseline 为 `SSE/SSE2/SSE3`，没有把 x86-64-v2
作为运行基线。

## 交付物

| 项 | 值 |
| --- | --- |
| 容器镜像 | `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64` |
| 轻量离线包 | `dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz` |
| 镜像 tar | `dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar` |
| Manifest | `dist/MANIFEST-paper9v2-2.1.0-legacy-amd64.json` |
| SHA256SUMS | `dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt` |
| 默认配置 | `configs/paper9v2_no_net_loss_authority_slope.yml` |
| 包版本 | `0.2.1` |
| 算法版本 | `paper9v2 2.1.0` |
| CPU 兼容性 | `legacy-x86_64-without-x86-64-v2` |

SHA256：

```text
7e86853d2bb7462022ef385bdde6587e452de209b149ad0341be7f41f2e7cd56  dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
0b3fcacc69291109e73a71bb248f1c308a9a683396e49e36e5c8ece754c33da1  dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
```

容器内关键版本：

```text
paper9_mnr 0.2.1
typer 0.12.5
click 8.1.7
numpy 1.26.4
SIMD baseline: SSE, SSE2, SSE3
```

## 本机 Docker 真实数据 E2E

本机为 Apple Silicon，验证时使用 Docker `--platform linux/amd64` 运行 legacy amd64 镜像。

| 项 | 值 |
| --- | --- |
| run_id | `20260701-123848` |
| 状态 | `ok` |
| 总耗时 | `6771.457s` |
| run manifest | `outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/logs/run_full_pipeline-20260701-123848.json` |
| audit summary | `outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/audit_summary.json` |
| plan summary | `outputs/paper9v21_legacy_docker_e2e_20260701-2038/outputs/plan_paper9v2_no_net_loss/mpc_summary.json` |

阶段结果：

| 阶段 | 状态 | returncode | 耗时 |
| --- | --- | ---: | ---: |
| prepare | ok | 0 | 289.024s |
| sample | ok | 0 | 4728.314s |
| train | ok | 0 | 1442.745s |
| plan | ok | 0 | 311.198s |
| audit | ok | 0 | 0.167s |

核心规划结果：

| 指标 | 值 |
| --- | ---: |
| `cultivated_area_change_ha` | `446.19924145582917` |
| `cultivated_area_change_pct` | `0.5708407917014762` |
| `slope_change_pct` | `-0.36905155519800664` |
| `cont_change` | `0.0482791796037958` |
| `baimu_count_change` | `-20` |
| `baimu_area_change_ha` | `669.1730569538712` |
| `swaps_completed` | `476` |
| `total_reward` | `46.777267824435874` |

Audit：

```text
all_expected_outputs_exist: true
hard_constraint_passed: true
required_cultivated_area_delta_ha: 0.0
failure_reasons: []
```

Shapefile 输出统计：

```text
n_input: 134369
n_in_env: 76377
n_farm_to_forest: 476
n_forest_to_farm: 476
n_unchanged: 75425
```

## Windows Intel 重建验证

Windows Intel 机器已从 GitHub 拉取源码，使用 Docker Desktop Linux containers 重新构建
`paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64` 并完成真实数据测试。对应配置已提交：

```text
configs/windows_dongxing_real_docker_e2e.yml
```

该验证说明不拷贝本机镜像 tar、由 Intel Windows 机器从源码重新构建 legacy amd64 镜像的路径可用。
注意该路径是联网构建验证，不等同于自然资源部目标内网机器上的离线 `docker load` 流程。

## 已修复阻塞问题

1. Click/Typer CLI 兼容性  
   `typer==0.12.5` 与 `click==8.4.2` 组合会导致 CLI help 阶段 TypeError。legacy 约束已固定
   `click==8.1.7`，并增加 `tests/test_farmland_cli_entrypoint.py`。

2. Shapefile datetime 字段  
   真实 GPKG 中 `BGRQ` 被解析为 datetime，ESRI Shapefile/DBF 不支持 datetime 字段。导出前已将
   datetime/date-like 字段转换为 ISO 字符串，并增加回归测试。

代码侧验证：

```text
61 passed
```

## 现场继续测试建议

自然资源部内网继续测试时，应使用：

```text
paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64
configs/paper9v2_no_net_loss_authority_slope.yml
```

现场顺序：

```text
check -> dry-run -> run -> audit
```

现场报告至少记录 run_id、镜像引用、配置文件、各阶段耗时、`audit_summary.json` 三项 hard gate、
`mpc_summary.json` 业务指标和 `DLTB_optimized.shp` 路径。

## 非阻塞告警

- Fiona 对 GeoPackage v1.4 的 partial support 提示。
- Shapefile/DBF 字段名长度限制导致字段名截断。
- 个别乡镇无有效 blocks 或图斑数过少，被跳过。
- libpysal disconnected components/islands 提示。
- `county_env.py` 中若干 `invalid value encountered in divide` RuntimeWarning，当前未导致阶段失败。
- plan 阶段关于 `baimu_area_penalty` reward override 的提示需要在解释结果时保留。
