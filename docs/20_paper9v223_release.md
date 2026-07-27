# Paper9v2.2.3 发布说明

## 发布标识

| 项目 | 值 |
| --- | --- |
| Python 包版本 | `0.3.3` |
| 算法 | `paper9v2 2.2.3` |
| 平台 | `linux/amd64` |
| 镜像 | `paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64` |
| CPU 兼容口径 | `legacy-x86_64-without-x86-64-v2` |
| 独立镜像 tar | `dist/paper9-mnr-offline-paper9v2-2.2.3-legacy-linux-amd64.tar` |
| 轻量部署包 | `dist/paper9-mnr-offline-container-paper9v2-2.2.3-legacy-amd64.tar.gz` |

最终字节数和 SHA-256 以包外
`dist/MANIFEST-paper9v2-2.2.3-legacy-amd64.json` 与
`dist/SHA256SUMS-paper9v2-2.2.3-legacy-amd64.txt` 为准。归档内部文件还必须通过包内
`SHA256SUMS.txt` 校验。

## 本补丁修正

1. 统一地类编码。生产数据按 `GB/T 21010-2017` / 第三次全国国土调查四位基码识别：耕地
   `0101/0102/0103`、林地 `0301-0307`、园地 `0201-0204`。旧三位测试码仍可单独兼容。
2. 增加强校验。同一 DLTB 混用现行四位和旧三位耕地/林地码，或者识别不到耕地、林地时，
   融合直接失败。日志和 `fusion_report.json` 记录编码体系、逐码计数和分类计数。
3. 全链路使用同一分类器。融合、保护冲突复核、候选块、县域环境、BSM 写回对齐和优化成果
   写出不再各自维护不同前缀。
4. 优化成果默认码更新为耕地 `0101`、林地 `0301`，并拒绝输入输出编码体系混用。
5. 自动数据目录优先使用六位行政区码，不再生成以 `-` 开头的目录。
6. `fuse` 完成后在宿主机验证六个融合文件，并在 `DATA_ROOT/FUSION_OUTPUTS.txt` 写出绝对
   路径、字节数和 SHA-256。缺失或空文件会使命令失败，不再误报完成。

## 路径口径

- 融合后供算法读取的六个输入位于 `DATA_ROOT/input/`。
- 宿主机融合成果入口为 `DATA_ROOT/FUSION_OUTPUTS.txt`。
- 执行完整 `run` 后的最终优化矢量位于
  `DATA_ROOT/outputs/plan_paper9v22_authority_constraints/DLTB_optimized.shp`。
- 运行日志位于 `DATA_ROOT/outputs/logs/`。

`YJJBNTBHTB` 中的 `0103` 与 DLTB 中的 `1104` 都属于现行编码体系，分别表示旱地和坑塘
水面。两层不按编码值相等关联；DLTB 编码决定现状地类，永久基本农田图层按空间范围生成
保护锁定。
