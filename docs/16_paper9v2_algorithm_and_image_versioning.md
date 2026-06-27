# 16 Paper9v2 算法与容器镜像版本化设计

日期：2026-06-27

依据：

- `/Users/zhouning/paper4-mnr-offline/reports/paper4_paper9_result_difference_analysis_20260627.md`
- `docs/reports/paper9_offline_bishan_dongxing_report_20260627/REPORT.md`

## 1. 结论

需要定义 `paper9v2`，但 v2 的第一目标不是重写一个跨区县通用模型，而是把当前 Paper9 离线包升级为“自然资源业务约束版”：

- 县域范围内耕地总面积不减少成为正式模式的硬约束。
- 最终耕地平均坡度降低、连片度上升纳入硬审计门槛。
- 百亩方作为软优化目标：尽量增加百亩方数量和面积，但不作为默认硬约束。
- sample、train、plan、audit 使用同一套面积约束、reward 和验收口径。
- 结果审计从“提示风险”升级为“硬失败”。
- Python 包、算法版本、容器镜像、离线交付 tar 统一版本化管理。

Paper9v2 仍然是区县专属训练流程。跨区县免训练泛化需要改模型结构，不纳入 v2.0 的首要范围。

## 2. 背景问题

Paper4/Paper9 差异分析显示，Paper9 在 Bishan 上坡度和连片性改善更强：

| 指标 | Paper9 Bishan |
| --- | ---: |
| 坡度变化 | -1.326% |
| 连片性变化 | +0.0285 |
| 百亩方数量变化 | +4 |
| 百亩方面积变化 | -174.02 ha |
| 耕地面积变化 | -203.04 ha |

这个结果说明当前 Paper9 的工程链路可用，但默认业务口径还不适合直接作为正式验收方案。自然资源业务通常不能只追求坡度下降，还要满足县域耕地面积不减少、平均坡度降低、连片度上升和可审计要求。百亩方是重要优化方向，但按当前业务口径属于“尽量形成”的软目标。

当前仓库已有 `cultivated_area_floor_delta_ha` 与 `baimu_area_floor_delta_ha` 接口，但正式测试配置 `configs/real_data_from_authority_slope.yml` 未启用耕地面积底线。并且 `sample` 阶段目前只传 reward 权重，没有把耕地面积底线约束传入采样环境，导致训练数据和规划约束口径不完全一致。Paper9v2 默认只启用县域耕地面积底线；百亩方面积底线保留为可选增强项。

## 3. 方案选型

### 方案 A：只启用现有 no-net-loss 配置

做法：

- 使用 `configs/no_net_loss_authority_slope.yml` 重跑 Bishan 和 Dongxing。
- 不修改算法代码。

优点：

- 成本最低。
- 可以快速判断现有约束接口对 Bishan 的改善程度。

缺点：

- sample/train 阶段仍不是完整约束感知。
- MPC rollout 仍可能高估后续约束下不可持续的动作序列。
- 审计和容器版本管理仍不够正式。

结论：适合作为 v2 前置基线，不足以定义正式 paper9v2。

### 方案 B：Paper9v2 约束感知工作流

做法：

- 新增 v2 默认配置 profile。
- 把县域耕地面积底线约束贯穿 sample、train、plan、audit。
- MPC 候选动作排序和实际执行共享耕地面积约束口径。
- 最终坡度降低、连片度上升进入硬审计。
- 百亩方通过 reward 和报告评价尽量优化，不作为默认硬失败条件。
- 增加硬约束审计与多 seed 评估。
- 建立容器镜像和离线包版本化规则。

优点：

- 直接解决 Bishan 暴露的正式业务风险。
- 对现有架构改动可控。
- 可以保留 Paper9 当前 sample -> train -> plan 的工程优势。

缺点：

- 需要重新做 Bishan/Dongxing 端到端测试。
- 耕地面积硬约束变强后，坡度改善幅度可能下降。
- 百亩方是软目标，结果可能出现数量或面积未提升，需要在报告中解释。

结论：推荐作为 paper9v2.0。

### 方案 C：跨区县泛化模型重构

做法：

- 去掉基于 block ID 的 action embedding。
- 改为 block feature/action feature 表达，支持不同 `n_blocks`。
- 使用多区县联合训练和留一区县验证。

优点：

- 有机会实现新县区免全量训练或少量微调。

缺点：

- 改动大，训练数据要求高。
- 当前 Bishan/Dongxing 样本量不足以证明泛化。
- 交付周期和算法风险显著高于方案 B。

结论：不作为 paper9v2.0 范围，可作为后续 paper9v3 研究方向。

## 4. Paper9v2.0 范围

### 4.1 算法目标

Paper9v2.0 使用分层目标：

1. 硬约束先行：县域耕地总面积不低于初始耕地总面积。
2. 最终验收要求：耕地平均坡度必须低于初始值。
3. 最终验收要求：连片度必须高于初始值。
4. 软优化目标：在满足前三项前提下，尽量增加百亩方数量和百亩方面积。
5. 审计不通过的结果不能作为正式输出。

默认正式 profile：

```yaml
algorithm:
  name: paper9v2
  version: 2.0.0

planning:
  constraints:
    cultivated_area_floor_delta_ha: 0
```

默认不设置 `baimu_area_floor_delta_ha`。如果后续现场业务明确要求百亩方面积也不减少，再作为可选硬约束加入配置，并必须写入 manifest 和报告。

### 4.2 约束贯穿流程

Paper9v2.0 的核心要求是同一套约束进入所有阶段：

| 阶段 | v1 现状 | v2 要求 |
| --- | --- | --- |
| prepare | 构建区县 blocks 和图斑映射 | 保持不变，但记录算法版本与 profile |
| sample | 传 reward 权重，不传面积底线 | 传入县域耕地面积底线，采样约束可行空间 |
| train | 学习 v1 采样分布 | 学习 v2 约束分布 |
| plan | 执行环境可接收面积底线 | 候选排序、rollout、执行均使用县域耕地面积约束口径 |
| audit | 检查产物存在和结果指标 | 耕地面积、坡度、连片度硬门槛不满足时直接 fail |

### 4.3 MPC 约束感知

当前真实 `env.step()` 可以按面积底线阻止不可行交换，但 ensemble rollout 使用预测状态排序候选动作，容易对后续不可行路径估值过高。v2 应增加：

- 当前步候选动作必须来自约束后的 `action_masks()`。
- rollout 阶段对预测后的县域耕地面积增加可行性惩罚或过滤。
- 如果约束过滤导致无可行动作，应提前终止，并在 summary 中记录终止原因。
- 百亩方不参与默认可行性过滤，仅通过 reward、tie-breaker 和报告指标尽量优化。

### 4.4 审计与报告

Paper9v2.0 的 audit summary 必须增加：

- `algorithm_name`
- `algorithm_version`
- `profile`
- `constraint_status`
- `cultivated_area_floor_delta_ha`
- `cultivated_area_change_ha`
- `slope_change_pct`
- `cont_change`
- `baimu_count_change`
- `baimu_area_floor_delta_ha`
- `baimu_area_change_ha`
- `hard_constraint_passed`
- `failure_reasons`

硬约束失败示例：

```json
{
  "hard_constraint_passed": false,
  "failure_reasons": [
    "cultivated_area_change_ha=-203.04 < required 0.0",
    "slope_change_pct=0.12 does not satisfy slope_change_pct < 0",
    "cont_change=-0.004 does not satisfy cont_change > 0"
  ]
}
```

正式报告中，硬约束失败结果不能被描述为业务可采用方案。

## 5. 容器镜像版本化管理

### 5.1 三层版本

Paper9v2 需要区分三类版本，不能只靠日期文件名：

| 层级 | 示例 | 含义 |
| --- | --- | --- |
| Python 包版本 | `0.2.0` | 代码包语义版本 |
| 算法版本 | `paper9v2` / `2.0.0` | 业务算法语义和约束口径 |
| 容器镜像版本 | `paper9v2-2.0.0-amd64` | 可运行交付物版本和架构 |

建议新增统一版本来源：

```text
src/paper9_mnr/version.py
```

包含：

```python
PACKAGE_VERSION = "0.2.0"
ALGORITHM_NAME = "paper9v2"
ALGORITHM_VERSION = "2.0.0"
```

构建脚本、CLI、run manifest、audit summary、报告和容器标签都从同一来源读取或注入。

### 5.2 镜像标签规则

保留历史 v1 标签：

```text
paper9-mnr-offline:amd64
paper9-mnr-offline:arm64
```

Paper9v2 使用不可变发布标签：

```text
paper9-mnr-offline:paper9v2-2.0.0-amd64
paper9-mnr-offline:paper9v2-2.0.0-arm64
```

可选维护方便现场使用的浮动别名：

```text
paper9-mnr-offline:paper9v2-amd64
paper9-mnr-offline:paper9v2-arm64
```

正式交付、报告和审计必须记录不可变标签，不能只记录浮动别名。

### 5.3 离线 tar 命名规则

镜像 tar：

```text
dist/paper9-mnr-offline-paper9v2-2.0.0-linux-amd64.tar
dist/paper9-mnr-offline-paper9v2-2.0.0-linux-arm64.tar
```

容器运行时整包：

```text
dist/paper9-mnr-offline-paper9v2-2.0.0-container-amd64-YYYYMMDD.tar.gz
dist/paper9-mnr-offline-paper9v2-2.0.0-container-arm64-YYYYMMDD.tar.gz
```

日期只表示交付批次，不替代语义版本。

### 5.4 OCI labels

Dockerfile 应写入 OCI 元数据：

```text
org.opencontainers.image.title=paper9-mnr-offline
org.opencontainers.image.version=0.2.0
org.opencontainers.image.revision=${GIT_COMMIT}
org.opencontainers.image.created=${BUILD_TIME}
org.opencontainers.image.source=https://github.com/zhouning/paper9-mnr-offline-package
io.paper9.algorithm.name=paper9v2
io.paper9.algorithm.version=2.0.0
```

构建时通过 `--build-arg` 注入 git commit 和 build time。

### 5.5 运行脚本兼容策略

`deploy/container-runtime/run-paper9-container.sh` 当前使用：

```bash
tag="$image:$arch"
```

v2 应增加显式镜像引用：

```bash
--image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64
```

兼容规则：

- 如果传入 `--image-ref`，直接使用完整镜像引用。
- 如果未传入，保持 v1 行为：`$image:$arch`。
- v2 文档推荐始终使用 `--image-ref`，避免 `amd64` 标签指向不清。

### 5.6 Bundle manifest

每个离线包应包含：

```text
MANIFEST.json
SHA256SUMS.txt
```

`MANIFEST.json` 至少包含：

```json
{
  "package_version": "0.2.0",
  "algorithm_name": "paper9v2",
  "algorithm_version": "2.0.0",
  "image_ref": "paper9-mnr-offline:paper9v2-2.0.0-amd64",
  "platform": "linux/amd64",
  "git_commit": "GIT_COMMIT",
  "build_time": "BUILD_TIME_ISO8601",
  "default_config": "configs/paper9v2_no_net_loss_authority_slope.yml"
}
```

## 6. 测试与验收

### 6.1 单元测试

必须覆盖：

- v2 配置校验。
- sample 参数包含县域耕地面积底线约束。
- plan 参数包含县域耕地面积底线约束。
- audit 对耕地面积、坡度、连片度硬门槛失败返回失败。
- run manifest 写入算法版本和镜像版本，并记录 `audit` 作为正式运行最后阶段。
- 容器运行脚本支持 `--image-ref`。
- bundle manifest 和 SHA256SUMS 生成。

### 6.2 工程 smoke 测试

必须覆盖：

- `python -m pytest tests -q`
- `python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml --dry-run`
- Docker arm64 check。
- Docker amd64 check。
- `run-paper9-container.sh check --image-ref ...`

### 6.3 正式端到端测试

至少重跑：

- Dongxing + paper9v2 + amd64。
- Bishan + paper9v2 + arm64 或 amd64。

验收指标：

| 指标 | 要求 |
| --- | --- |
| 流程状态 | prepare/sample/train/plan/audit 全部通过 |
| 耕地面积变化 | `>= 0 ha` |
| 坡度变化 | `< 0` |
| 连片性变化 | `> 0` |
| 百亩方 | 尽量增加数量和面积；不作为默认硬失败条件，但必须报告 |
| 多 seed | 至少 3 个 seed，报告均值、方差、最差值 |
| 容器版本 | 报告记录 image_ref、algorithm_version、git_commit |

## 7. 实施分期

### Phase 1：版本与配置骨架

- 新增 `version.py`。
- 新增 `configs/paper9v2_no_net_loss_authority_slope.yml`。
- CLI、run manifest、audit summary 写入版本元数据。
- 容器脚本支持 `--image-ref`。

### Phase 2：约束贯穿 sample/train/plan

- `build_sample_args` 支持传递 `planning.constraints`。
- `sample.py` 环境构建接收面积底线。
- train summary 记录约束 profile。
- plan 保持同一约束 profile。

### Phase 3：MPC 约束感知增强

- 当前步候选动作使用约束后 action mask。
- rollout 增加县域耕地面积约束 proxy 或惩罚。
- 无可行动作时输出明确终止原因。

### Phase 4：硬审计与报告

- audit 增加耕地面积、坡度、连片度 hard constraint gate。
- 报告模板增加约束状态、失败原因和百亩方软目标表现。
- 输出 Paper4/Paper9v2 统一口径对比表。

### Phase 5：容器 release

- Dockerfile 增加 OCI labels。
- 构建双架构镜像：
  - `paper9-mnr-offline:paper9v2-2.0.0-amd64`
  - `paper9-mnr-offline:paper9v2-2.0.0-arm64`
- 导出对应 tar 和 container-runtime bundle。
- 生成 `MANIFEST.json` 与 `SHA256SUMS.txt`。

## 8. 风险

- 县域耕地面积硬约束会降低坡度优化空间，Bishan 的坡度降幅可能低于当前 `-1.326%`。
- 百亩方不作为默认硬约束，v2 可能出现坡度/连片度/耕地面积全部达标但百亩方提升有限的结果。
- 当前 Paper9 模型仍绑定区县 `n_blocks` 和 action space，v2 不解决新县区免训练泛化。
- 如果 Paper4 和 Paper9v2 的候选乡镇、block 构建规则仍不统一，对比解释仍会受口径差异影响。

## 9. 推荐下一步

先执行 Phase 1 和 Phase 2，形成最小可测的 paper9v2：

1. 版本元数据和镜像标签规则落地。
2. 新增 v2 no-net-loss 配置。
3. sample/train/plan 约束口径打通。
4. 以 Bishan 做一次完整 v2 E2E，验证耕地面积不减少、平均坡度降低、连片度上升，并观察百亩方提升情况。

如果 Bishan v2 结果通过三项硬门槛，再补 Dongxing、多 seed 和双架构容器 release。
