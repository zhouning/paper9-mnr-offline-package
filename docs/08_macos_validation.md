# 08 macOS 验证

这份离线包的代码层面不依赖 ArcGIS，适合在算力更强的 macOS 机器上做模型训练和规划验证。建议 macOS 侧先只验证包装层和环境，再接入真实数据。

## Clone 后的第一步

```bash
git clone <repo-url>
cd paper9-mnr-offline-package
```

## Conda 环境

Apple Silicon 和 Intel Mac 都建议使用 conda-forge：

```bash
conda env create -f environment.yml
conda activate paper9-mnr-offline
python -m pip install -e .
```

如果 `pytorch` 在 `environment.yml` 中解析较慢，可以先用 mamba：

```bash
mamba env create -f environment.yml
```

## 先做轻量验证

```bash
python scripts/00_check_env.py --no-heavy
python -m pytest tests -q
python scripts/run_full_pipeline.py configs/real_data_from_authority_slope.yml --dry-run
```

如使用本机代理数据验证自然资源部两类输入结构，可参考：

```bash
python scripts/run_full_pipeline.py configs/local_macos_mnr_proxy.yml
python scripts/05_audit.py configs/local_macos_mnr_proxy.yml --write
```

`configs/local_macos_mnr_proxy.yml` 使用本地 DLTB 坡度数据和由 DLTB 权属代码 dissolve
得到的代理行政区图层，只用于验证接口和流程，不可替代正式自然资源部权威行政区数据。

## 再做完整环境验证

```bash
python scripts/00_check_env.py
```

这一步会导入 GeoPandas、Rasterio、Torch 和 ONNX Runtime。只有完整环境检查通过后，再移动真实数据到 `data/input/` 并运行 `prepare/sample/train/plan`。

正式数据要求和客户运行步骤见 `docs/09_mnr_customer_runbook.md`。

## macOS 路径注意事项

配置模板使用相对路径，可直接跨平台使用。真实数据放入：

```text
data/input/
```

不要把真实数据提交到 GitHub；`.gitignore` 已经排除了 `data/input/`、`data/working/` 和 `outputs/`。

## Apple Silicon 注意事项

如果 ONNX Runtime 或 PyTorch 出现架构问题，优先保证整个环境都是同一架构：

- Apple Silicon 原生：arm64 conda/miniforge。
- Rosetta：x86_64 conda 环境，所有依赖保持 x86_64。

不要在同一个环境中混装 arm64 和 x86_64 包。
