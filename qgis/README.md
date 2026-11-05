# QGIS 工程体系与自动化脚本 (QGIS 3.44 LTR)

- **基线版本**：开发基线 1.0 (2026-10-29 核验更新)
- **工程文件**：`qgis/xindu_1992_2021.qgz` (统一使用可移植 .qgz 格式，所有数据源采用相对路径)
- **清单文件**：`qgis/project_manifest.json` (自动记录 build_id, 依赖图层, relative_uri, sha256 与 layouts)
- **技术路线**：保持离线科学流水线与 QGIS 工程松耦合，不引入插件架构，通过脚本与标准化文件契约协作。

---

## 一、 目录组织与文件归属

```text
qgis/
├── scripts/                        # QGIS 自动化工具集 (无头模式与 PyQGIS 控制台通用)
│   ├── build_project.py            # 工程候选装配、相对路径图层绑定、清单生成与原子提交
│   ├── check_project.py            # 独立检查工程完整性、CRS、相对路径、图层有效性与布局声明
│   ├── export_layouts.py           # 4 张标准专题图 (300 dpi) 批量导出与模板校验
│   └── join_statistics.py          # 街镇与变化统计表字符串 unit_id 严格关联 (W19 切片)
├── styles/                         # 标准 QML 渲染样式库
│   ├── lulc_5class.qml             # 土地利用 5 类离散色表 (1建设, 2耕地, 3其他植被, 4水域, 5裸地, 0透明)
│   ├── change_4class.qml           # 4 类变化色表 (1持续建设, 2新增建设, 3减少建设, 4持续非建, 0透明)
│   ├── townships.qml               # 街镇行政边界描边与注记样式
│   ├── township_intensity.qml      # 街镇年均建设用地扩张强度分级渲染样式
│   └── study_area.qml              # 新都区研究区外框样式
├── layouts/                        # 4 套标准 A4 横向 QPT 打印布局模板
│   ├── lulc_1992.qpt               # 1992 年土地覆被现状专题图模板
│   ├── lulc_2021.qpt               # 2021 年土地覆被现状专题图模板
│   ├── urban_change.qpt            # 1992—2021 年建设用地扩张时空演化图模板
│   └── township_change.qpt         # 1992—2021 年街镇年均扩张强度专题图模板
├── forms/                          # 样本标注表单与编辑约束
│   ├── sample_form_rules.json      # 样本字段规范 (year, class_id, sample_id, group_id, split)
│   └── sample_labels.qml           # 样本图层分类渲染与表单 ValueMap 绑定配置
├── xindu_1992_2021.qgz             # 生成的可移植 QGIS 工程主文件 (Git 忽略)
└── project_manifest.json           # 构建生成清单
```

---

## 二、 自动化 CLI 命令与用法

所有脚本支持在操作系统命令行（无头 Python 环境）或 QGIS 3.44 内置 Python 控制台中直接执行：

### 1. 构建 QGIS 工程 (`build_project.py`)
```bash
# 开发模式 (允许部分衍生栅格未就绪，生成开发版工程与清单)
python qgis/scripts/build_project.py --config configs/project.toml --project qgis/xindu_1992_2021.qgz --mode development

# 正式发布模式 (必需输入必须 100% 存在且校验通过，否则阻断并列出完整缺口)
python qgis/scripts/build_project.py --config configs/project.toml --project qgis/xindu_1992_2021.qgz --mode release
```

### 2. 独立工程验证 (`check_project.py`)
```bash
python qgis/scripts/check_project.py --project qgis/xindu_1992_2021.qgz --manifest qgis/project_manifest.json
```
检查项包括：
- 工程文件与清单是否存在；
- QGS XML 语法合法性；
- 空间参考系统必须为 `EPSG:32648`；
- 所有图层数据源 relative_uri 跨机器可解析性；
- 4 个标准打印布局完整性。

### 3. 批量制图导出 (`export_layouts.py`)
```bash
python qgis/scripts/export_layouts.py --project qgis/xindu_1992_2021.qgz --export-dir outputs/maps
```
严格导出 4 张交付 PNG（300 dpi）：
- `outputs/maps/lulc_1992.png`
- `outputs/maps/lulc_2021.png`
- `outputs/maps/urban_change_1992_2021.png`
- `outputs/maps/township_change.png`

---

## 三、 QGIS Python 控制台交互操作入口

在 QGIS 3.44 桌面软件中打开内置 Python 控制台（`Ctrl + Alt + P`），可直接加载工具并运行：

```python
import sys
from pathlib import Path

# 获取项目根目录
project_root = Path(r"F:\工程实践3")
sys.path.insert(0, str(project_root / "qgis" / "scripts"))

from build_project import build_project
from check_project import check_project
from export_layouts import export_layouts

# 1. 装配工程
report = build_project(
    project_root / "configs" / "project.toml",
    project_root / ".env",
    project_root / "qgis" / "xindu_1992_2021.qgz",
    mode="development"
)
print("Build:", report.status)

# 2. 验证工程
chk = check_project(report.project_path, report.manifest_path)
print("Check passed:", chk.passed)

# 3. 导出 4 张地图
exp = export_layouts(report.project_path, project_root / "outputs" / "maps")
print("Export:", exp.status)
```

---

## 四、 核心科学约束与契约

1. **绝对相对路径**：所有图层必须相对 `qgis/` 目录组织，禁止在工程文件中写入 `F:\...` 等跨机器失效的绝对物理路径。
2. **图层稳定 ID**：每个图层分配不可变的 `practice3/logical_id` 属性，上层逻辑不依赖用户在界面中修改的图层显示名称。
3. **样本独立性表单约束**：
   - `split` 字段为只读，由算法模块生成的 `split.json` 自动写入，严禁人工手工调整；
   - `group_id` 不设唯一约束（允许多个多边形共属同一空间地块），但严禁同组跨越不同地类。
4. **统计关联严谨性**：街镇矢量图层与 `township_change_1992_2021.csv` 必须通过字符串 `unit_id` 关联（严格区分 `"001"` 与 `"1"`），无共同观测有效区时保持 `NULL`，严禁填 0 伪造指标。
