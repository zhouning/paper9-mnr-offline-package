# Paper9v2.3 Windows 无容器离线部署

## 1. 采用的部署方式

目标环境是离线 Windows x64 且没有容器，因此交付一个自带运行时的 ZIP：

```text
paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64/
  app/                  Paper9 源码、脚本和配置
  bin/                  PowerShell 启动和校验脚本
  runtime/              Windows x64 conda-pack 便携运行时
  dem/                  中宁县四幅离线 DEM
  reference/admin/      中宁县 13 个乡镇面
  MANIFEST.json
  SHA256SUMS.txt
```

现场机器不需要 Docker、Python、Conda、ArcGIS、管理员权限或互联网连接。运行时只能在
Windows x64 上构建；Linux、WSL 和 macOS 的 Python 环境不能复制到 Windows 使用。

## 2. 在联网 Windows x64 构建机上生成交付包

构建机要求：64 位 Windows 10/11 或 Windows Server、PowerShell 5.1 以上、Conda/Miniforge、
Git、Git LFS，以及能访问 `conda-forge`。仓库中必须已有 Git LFS 实体文件、四幅中宁县 DEM、
三幅东兴/璧山 DEM 和两个数据清单。

克隆仓库后先拉取 LFS 数据（否则大 DLTB 只会是文本指针）：

```powershell
git lfs install
git lfs pull
```

在仓库根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\windows-native\build-windows-runtime.ps1
```

脚本会：

1. 按 `environment-windows-x86_64.yml` 创建独立 Windows 环境；
2. 在 Windows 上运行完整 pytest 和 Ruff；
3. 导出 Conda explicit lock；
4. 用 `conda-pack` 生成便携运行时；
5. 组装 DEM、行政参考、源码、清单和逐文件 SHA-256；
6. 生成 `dist/paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip` 及其 `.sha256`。

如果构建环境已存在且确认可复用，增加 `-ReuseEnvironment`。不要用 `-SkipTests` 制作正式交付包。

## 2.1 包内置数据资产

正式 ZIP 内置三类可复核数据资产，路径和逐文件 SHA-256 见对应 `MANIFEST.json`：

| 数据集 | 内置地类图斑 | 内置 DEM | 内置行政参考 | 运行方式 |
|---|---|---|---|---|
| 内江市东兴区 | `datasets/dongxing/DLTB_with_slope.gpkg`，134369 个图斑，筛选码 `511011` | `N29E104`、`N29E105` | 29 个乡镇面 | `-Dataset dongxing` |
| 重庆市璧山区 | `datasets/bishan/DLTB_with_slope.gpkg`，101657 个图斑，源码 `500227` 映射到 `500120` | `N29E106` | 15 个乡镇面 | `-Dataset bishan` |
| 宁夏中宁县 | **不内置 DLTB**，现场通过 `-DltbSource` 提供 | `N36E105`、`N36E106`、`N37E105`、`N37E106` | 13 个乡镇面，县码 `640521` | `-Dataset zhongning` 或自定义 DLTB |

中宁县是“内置 DEM + 行政参考、现场提供地类图斑”的交付模式；程序不伪造、推测或替代客户 DLTB。
东兴和璧山样例仅用于包内冒烟测试，三套数据均属于 `dltb_dem_only` 探索性技术验证，不包含 PDT、
生态保护红线或永久基本农田。

## 3. 构建机冒烟测试

先在一台不依赖构建环境 PATH 的 Windows x64 机器上解压 ZIP。建议使用短路径：

```text
D:\paper9_zhongning
```

执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd D:\paper9_zhongning
.\bin\verify-paper9-package.ps1
.\bin\run-paper9-windows.ps1 check
```

首次 `check` 会先校验完整运行时，再执行 `conda-unpack` 的本机路径修复。路径修复会按设计修改
运行时内部文件；之后再次校验时，脚本跳过这些可变运行时文件，但仍逐一校验应用、DEM、行政参考和文档。

再用一份包含 `640521` 图斑的脱敏测试 DLTB 完成：

```powershell
.\bin\run-paper9-windows.ps1 fuse -DltbSource "E:\test\DLTB.gdb"
.\bin\run-paper9-windows.ps1 dry-run
```

正式交付前至少记录 Windows 版本、CPU 架构、内存、ZIP SHA-256、`check` 输出和融合报告。

## 4. 内网现场运行

先核对外层 ZIP：

```powershell
Get-FileHash .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip -Algorithm SHA256
```

与同目录 `.sha256` 一致后，解压并运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd D:\paper9_zhongning
.\bin\verify-paper9-package.ps1
.\bin\run-paper9-windows.ps1 check
```

省级 DLTB 是 FileGDB 目录时：

```powershell
.\bin\run-paper9-windows.ps1 fuse `
  -DltbSource "E:\宁夏数据\2025DLTB.gdb"
```

如果 FileGDB 中有多个候选面图层，可增加 `-DltbLayer "实际图层名"`。程序按六位代码
`640521` 筛选中宁县，不要求预先裁县。

包内样例可以直接用于 Windows 冒烟测试。推荐先跑东兴区：

```powershell
.\bin\run-paper9-windows.ps1 all -Dataset dongxing
```

璧山区样例使用源数据旧县码 `500227`，启动器会显式使用当前行政参考码 `500120`：

```powershell
.\bin\run-paper9-windows.ps1 all -Dataset bishan
```

这两条命令不读取外部 DLTB；它们只用于验证包内数据、DEM、行政参考和 Paper9v2.3 流程。

融合后先打印全流程命令：

```powershell
.\bin\run-paper9-windows.ps1 dry-run
```

确认路径和参数后运行及复核：

```powershell
.\bin\run-paper9-windows.ps1 run
.\bin\run-paper9-windows.ps1 audit
```

也可以一条命令完成融合和全流程：

```powershell
.\bin\run-paper9-windows.ps1 all `
  -DltbSource "E:\宁夏数据\2025DLTB.gdb"
```

默认数据目录按数据集隔离在包内 `paper9-data\<dataset>`（例如
`paper9-data\zhongning`、`paper9-data\dongxing`、`paper9-data\bishan`）。可用
`-DataRoot "E:\paper9-work\640521"` 改到空间更大的本地盘；同一次运行的后续命令必须使用相同
`-DataRoot`。

## 5. 输出、重试和故障排查

融合完成后至少检查：

- `<DataRoot>\input\fusion_report.json`：县域筛选、DEM、行政参考和缺失约束状态；
- `<DataRoot>\input\input_availability.json`：输入是否可用及允许用途；
- `<DataRoot>\input\DLTB_with_authority_slope.gpkg`：融合后的运行图斑；
- `<DataRoot>\input\admin_units.gpkg`：运行行政单元；
- `<DataRoot>\outputs\logs\`：每个阶段的日志；
- `<DataRoot>\outputs\audit_summary.json`：最终审计和 `regulatory_compliance_claim_allowed`。

`fuse` 只读取客户 FileGDB，不修改源数据；`run` 必须在同一 `DataRoot` 已完成融合后执行。
一次运行中断时保留 `outputs\logs\` 和 `input\fusion_report.json`，先查看最后一个失败阶段；需要全新运行时，
使用新的 `-DataRoot`，避免覆盖原始证据。省级 DLTB 可通过 `-DltbLayer` 指定实际面图层，
通过 `-CountyCode`、`-ReferenceCountyCode`、`-Config`、`-DemDir` 或 `-AdminReference` 覆盖默认值。

| 现象 | 处理 |
|---|---|
| PowerShell 禁止运行脚本 | 当前会话执行 `Set-ExecutionPolicy -Scope Process Bypass`，不需要管理员权限。 |
| `conda-unpack` 或 DLL 错误 | 把 ZIP 解压到本地短路径（如 `D:\paper9_zhongning`），不要从网络共享目录直接运行，再重跑 `check`。 |
| 找不到 DLTB 图层 | 将 `-DltbSource` 指向完整 FileGDB 目录；多图层时增加 `-DltbLayer`。 |
| 筛选不到县域图斑 | 检查六位行政区代码字段，必要时显式传 `-CountyCode`；字段和 CRS 要求见 `docs/21_paper9v23_dltb_only_release.md`。 |
| 磁盘或内存不足 | 将 `-DataRoot` 放到空间更大的本地 NTFS 磁盘；自治区级数据建议至少 32 GB 内存。 |
| 运行中断或审计失败 | 不删除日志；收集 `outputs\logs\`、`input\fusion_report.json`、`input\input_availability.json` 和 `outputs\audit_summary.json`。 |

## 6. 现场资源和安全边界

建议至少 16 GB 内存、20 GB 可用磁盘；较大的自治区级 DLTB 建议 32 GB 内存。融合阶段只读取
客户 DLTB，不修改源 FileGDB。输出和日志全部位于 `DataRoot`。

运行脚本设置离线标志且算法没有网络调用。若现场制度要求操作系统级断网，应由现场网络或终端策略
实施；程序不申请管理员权限修改 Windows 防火墙。

必须保留以下文件用于问题定位：

- `<DataRoot>\input\fusion_report.json`；
- `<DataRoot>\input\input_availability.json`；
- `<DataRoot>\outputs\logs\`；
- `<DataRoot>\outputs\audit_summary.json`。

本模式不评估 PDT、生态保护红线和永久基本农田，成果只能用于技术验证。三类数据后续补齐后，
应切换到四源权威约束模式重新融合、采样、训练、规划和审计。
