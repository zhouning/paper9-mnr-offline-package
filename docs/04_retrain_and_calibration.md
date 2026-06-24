# 04 重新训练与奖励校准

Paper1 到 Paper4 再到 Paper9 的核心奖励逻辑是一条清晰主线：

- 耕地平均坡度下降。
- 耕地连片度上升。
- 尽量形成百亩方。

在自然资源部真实数据中，这条主线仍然有价值，但不足以覆盖真实业务。真实业务通常
还需要处理刚性管控线、耕地质量、永久基本农田、生态保护、工程可实施性和政策解释
成本。

## 为什么奖励变化必须重新 sample + train

Paper9 的训练数据来自环境采样。采样时的 reward 决定了 pairwise ranking 标签和
模型学习到的动作偏好。如果修改奖励权重或加入新奖励项，只重新运行 `plan` 会让旧
模型服务新目标，结果不可解释。

因此本包在配置校验中强制：

```yaml
workflow:
  force_resample_and_retrain_on_reward_change: true
```

奖励校准流程应为：

```powershell
python scripts\02_sample.py configs\reward_calibration_template.yml
python scripts\03_train.py configs\reward_calibration_template.yml
python scripts\04_plan.py configs\reward_calibration_template.yml
```

## 可扩展奖励项

建议按业务优先级逐步增加，而不是一次性塞入所有图层：

- 三区三线冲突惩罚：禁止或强惩罚越过生态红线、城镇开发边界等。
- 永久基本农田保护：限制非农化、非粮化方向的动作。
- 耕地质量收益：偏好质量等级更高、土壤条件更适宜的耕地集中。
- 工程可实施性：惩罚破碎边界、过远通达距离、灌排条件差的方案。
- 政策解释成本：减少跨权属、跨行政边界的大规模调整。

## 校准记录

每次校准都应保存：

- 配置文件。
- 输入数据版本和字段字典。
- 采样随机种子。
- 训练日志和模型目录。
- 规划输出和审计报告。
- 业务专家对方案的接受/拒绝理由。

