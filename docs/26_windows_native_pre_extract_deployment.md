# Windows 原生离线包解压前部署说明

本文档给负责内网交付的人员使用。它描述 ZIP 解压之前的准备、核验和交接步骤；解压后的运行手册位于 `docs\22_windows_native_airgap.md`。

## 1. 交付物

从构建机向内网 Windows x64 机器拷贝以下两个文件，并保持它们在同一目录：

```text
paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip
paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip.sha256
```

当前构建包的 SHA-256 为：

```text
ad2361f82c80c5956eb6bdcb4dd3465a3e7b80c69ea11f68cfcd30446c8c347a
```

不需要拷贝 Docker 镜像、Python/Conda 安装程序、源码仓库、`cmd.exe` 批处理文件或 WSL 环境。中宁县地类图斑不在包内，需由现场另外提供完整的 Esri File Geodatabase 目录（目录名通常以 `.gdb` 结尾）。

## 2. 目标机器要求

- 64 位 Windows 10/11 或 Windows Server。
- Windows PowerShell 5.1 或更高版本。现场只使用 PowerShell，不依赖 `cmd.exe`、WSL 或 Git Bash。
- 建议至少 16 GB 内存；处理省级地类图斑建议 32 GB 或更高。
- 解压前建议至少预留 40 GB 本地 NTFS 磁盘空间。ZIP 约 1.2 GB，解压后的便携 runtime、内置 DEM 和工作输出会额外占用空间。
- 建议使用短的本地路径，例如 `D:\paper9_zhongning`。不要直接从网络共享、OneDrive、压缩软件临时目录或路径很长的目录运行。
- 不要求管理员权限、Docker、Python、Conda、ArcGIS 或网络连接。

## 3. 解压前核验

在保存 ZIP 的目录中打开 Windows PowerShell，先确认两个文件存在：

```powershell
Get-ChildItem .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip*
```

计算 ZIP 的 SHA-256，并与同目录 `.sha256` 文件中的值比较：

```powershell
(Get-FileHash .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip.sha256
```

两者必须完全一致。若不一致，停止交付并重新从构建机拷贝；不要尝试解压或修改 ZIP。

可选的本地空间检查：

```powershell
Get-PSDrive -Name D | Select-Object Name,Free
```

## 4. 解压

在本地磁盘创建目标目录并解压。以下命令不调用 `cmd.exe`：

```powershell
New-Item -ItemType Directory -Path D:\paper9_zhongning -Force | Out-Null
Expand-Archive `
  -LiteralPath .\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3.zip `
  -DestinationPath D:\paper9_zhongning
Set-Location D:\paper9_zhongning
```

解压后，`D:\paper9_zhongning` 的第一层应直接包含：

```text
app\  bin\  datasets\  dem\  docs\  reference\  runtime\
MANIFEST.json  README.txt  SHA256SUMS.txt
```

不要再进入一个同名的嵌套目录；如果看到 `D:\paper9_zhongning\paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64-r3\bin`，说明解压层级多了一层，应重新选择目标目录。

## 5. 解压后的首次操作

先做包内逐文件校验，再运行环境检查：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\bin\verify-paper9-package.ps1
.\bin\run-paper9-windows.ps1 check
```

首次 `check` 会在当前目录执行便携 Conda runtime 的本机路径修复（`conda-unpack`），因此必须在最终部署路径执行。不要在临时目录先运行 `check`，再把整个目录移动到内网目标路径。

`verify-paper9-package.ps1` 应在首次 `check` 之前运行。`check` 完成后 runtime 中部分可变路径文件会被修改，后续再次校验时脚本会跳过这些文件，但仍会校验应用、DEM、行政区参考和文档文件。

## 6. 中宁县地类图斑准备

中宁县包内已经提供 DEM 和行政区参考，但不提供客户地类图斑。现场应将完整的 FileGDB 目录拷贝到本地磁盘，例如：

```text
E:\authority\2025DLTB.gdb\
```

确认它是目录而不是单个文件或压缩包：

```powershell
Get-Item E:\authority\2025DLTB.gdb | Select-Object FullName,Attributes
Get-ChildItem E:\authority\2025DLTB.gdb | Select-Object -First 10 Name
```

运行时将该目录作为 `-DltbSource` 传入：

```powershell
.\bin\run-paper9-windows.ps1 all `
  -DltbSource "E:\authority\2025DLTB.gdb" `
  -DataRoot "E:\paper9-work\640521"
```

不要把 `.gdb` 压成 ZIP 后直接传给 `-DltbSource`，也不要用 GeoPackage 替代客户 FileGDB。若一个 GDB 包含多个候选面图层，再按手册增加 `-DltbLayer`。

## 7. 内置数据快速确认

- 内江东兴：`datasets\dongxing`，含地类图斑样例、DEM 和行政区参考。
- 重庆璧山：`datasets\bishan`，含地类图斑样例、DEM 和行政区参考。
- 宁夏中宁：`dem\copernicus_glo30_zhongning` 的 4 个 DEM 瓦片，以及 `reference\admin\xiangzhen_zhongning.gpkg` 的 13 个乡镇行政区参考；不含中宁县客户地类图斑。

## 8. 交接记录

至少保存 ZIP 文件名、ZIP SHA-256、目标机器 Windows 版本和架构、解压目标路径、包内校验输出、首次 `check` 输出，以及客户 `.gdb` 的来源和拷贝路径。结果仅用于探索性技术验证；PDT、生态保护红线和永久基本农田未提供、未评估，不能据此作出合规结论。
