
---

### 虚拟文件库总览：`D:\桌面\AILab`

```text
D:\桌面\AILab\
├── projects\
│   └── digit_cls\
│       ├── train.py
│       ├── eval.py
│       ├── config.yaml
│       ├── requirements.txt
│       ├── .venv\                     ← 第7章创建
│       └── logs\
│           ├── train_20261010.log     ← 含 "ERROR: CUDA out of memory"
│           └── train_20261014.log     ← 含中文 "加载数据完成"
├── data\
│   ├── cats_dogs\
│   │   ├── raw\
│   │   │   ├── cat.1.jpg … cat.500.jpg
│   │   │   └── dog.1.jpg … dog.500.jpg
│   │   ├── train\cat\  \dog\          ← 空目录，待放入
│   │   └── val\  \cat\  \dog\
│   └── my data\                       ← 坑1：目录名带空格
│       └── 图片 备份.zip              ← 坑2：中文名 + 空格
├── scripts\
│   ├── backup.ps1
│   ├── rename_dataset.ps1
│   └── run_train.ps1
├── models\v1\weights.pt
├── temp\cache.tmp
├── temp\old\dump.log
└── notes.txt                          ← 坑3：GBK 编码的旧文件
```

> ⚠️ **注意**：`D:\桌面` 含中文但无空格，本身不会导致解析错误；真正的坑是 `data\my data` 这一层。路径含中文在 PowerShell 中完全正常，只要加引号即可。

#### 一键建库脚本（复制到终端直接执行）

```powershell
$root = "D:\桌面\AILab"

# 1. 建目录树
@(
    "$root\projects\digit_cls\logs",
    "$root\data\cats_dogs\raw",
    "$root\data\cats_dogs\train\cat", "$root\data\cats_dogs\train\dog",
    "$root\data\cats_dogs\val\cat",   "$root\data\cats_dogs\val\dog",
    "$root\data\my data",
    "$root\scripts",
    "$root\models\v1",
    "$root\temp\old"
) | ForEach-Object { New-Item -Path $_ -ItemType Directory -Force | Out-Null }

# 2. 造 1000 个占位文件（raw 下放 cat/dog 各 500）
1..500 | ForEach-Object { New-Item -Path "$root\data\cats_dogs\raw\cat.$_.jpg" -ItemType File -Force | Out-Null }
1..500 | ForEach-Object { New-Item -Path "$root\data\cats_dogs\raw\dog.$_.jpg" -ItemType File -Force | Out-Null }

# 3. 造 UTF-8 日志
@"
INFO epoch 1 loss 0.82
INFO epoch 2 loss 0.45
ERROR: CUDA out of memory
INFO epoch 3 loss 0.31
"@ | Set-Content -Path "$root\projects\digit_cls\logs\train_20261014.log" -Encoding utf8

# 4. 造 GBK 旧笔记（模拟乱码源）
"这是旧笔记，编码是 GBK" | Out-File -FilePath "$root\notes.txt" -Encoding default

# 5. 造训练脚本占位
@"
import sys
print("hello from", sys.argv)
"@ | Set-Content -Path "$root\projects\digit_cls\train.py" -Encoding utf8

# 验证：应输出一个大于 1000 的数字
(Get-ChildItem -Path $root -Recurse -File).Count
```

---

## 第 0 章 一张图看懂 Windows 命令行

**学完能做什么：** 分清"终端"和"Shell"，知道该点哪个图标，不再被一堆名字搞晕。

|名称|角色|本教程定位|
|---|---|---|
|**cmd.exe**|旧 Shell|只用于兼容遗留 `.bat`；本库基本用不到|
|**Windows PowerShell 5.1**|内置 Shell|主讲，`$PSVersionTable.PSVersion` 查版本|
|**PowerShell 7**|新版 Shell|可并行安装，可执行文件名为 `pwsh.exe`，与 5.1 不冲突|
|**Windows Terminal**|终端主机|提供标签页/分屏/主题，本身不解释命令|
|**WSL**|Linux 子系统|暂不装，仅作对照提醒|

### 动手练习

- **必做：** 打开 Terminal，输入 `$PSVersionTable.PSVersion`，确认主版本为 5.x。
- **选做：** 新建一个 PowerShell 标签页和一个 cmd 标签页，对比 `PS D:\>` 与 `D:\>` 提示符差异。

### 常见报错与排查

- **`$PSVersionTable` 报错** → 你在 cmd 里，输入 `powershell` 切换。

### 本章小结

1. Terminal 是容器，PowerShell 才是解释命令的程序。
2. 你只需记住：Terminal 里跑 PowerShell。
3. cmd 只在跑旧 `.bat` 时出现。

---

## 第 1 章 上手

**学完能做什么：** 打开终端、读懂提示符、用内置帮助自学任何命令。

### 打开终端

```powershell
wt                                          # Win+R 或 Terminal 新建标签页
Set-Location "D:\桌面\AILab"                # 进入本库
```

### 提示符拆解

```text
PS D:\桌面\AILab\projects\digit_cls>
```

`PS`=Shell 种类；中间=**当前工作目录**；`>`=等待输入。

### 自学三件套

```powershell
Get-Help Get-ChildItem                      # 查看帮助
Get-Help Get-ChildItem -Examples            # 只看示例（最实用）
Get-Command *item                           # 想不起命令名时搜
Get-ChildItem "$root\data\cats_dogs\raw" | Get-Member   # 看对象有哪些属性
```

> `Update-Help` 可下载最新帮助文档（需联网，默认 24 小时内只更新一次，加 `-Force` 强制更新）。

### 别名真相

```powershell
Get-Alias | Where-Object { $_.Name -in @('ls','dir','cat') }
```

`ls` / `dir` → `Get-ChildItem`；`cat` → `Get-Content`。

⚠️ **注意：** 它们只是别名，参数与 Linux 完全不同，`ls -l` 会报错。

### 动手练习

- **必做：** 对 `Select-String` 执行 `Get-Help -Examples`，照着在本库日志上跑一遍。
- **选做：** `Get-Process | Get-Member`，找出表示内存的属性名（`WS`）。

### 常见报错与排查

- **帮助为空** → `Get-Help xxx -Online` 打开网页版。
- **`ls -l` 报错** → 改用 `Get-ChildItem | Format-List`。

### 本章小结

1. 提示符中间的字符串就是当前目录。
2. `-Examples` 是最快的学习入口。
3. 别名只是"皮肤"，底层仍是 PowerShell 对象模型。

---

## 第 2 章 导航与文件操作

**学完能做什么：** 在本库跳转目录、批量复制数据集、安全删除临时文件、读写配置。

### 命令卡片

```powershell
# ① Set-Location
Set-Location "D:\桌面\AILab\projects\digit_cls"
# 作用：切换工作目录（别名 cd）；cd .. 退回上一级
```

```powershell
# ② Get-ChildItem
Get-ChildItem -Path "$root\data\cats_dogs\raw" -Filter "*.jpg" -File
# 作用：列出文件/目录
# 常用参数：-Filter（文件系统级过滤，快）、-Recurse、-Depth、-File/-Directory
# 场景：数 raw 下有多少张图
(Get-ChildItem -Path "$root\data\cats_dogs\raw" -File -Filter "*.jpg").Count
```

```powershell
# ③ New-Item
New-Item -Path "$root\data\cats_dogs\test\cat" -ItemType Directory -Force
# 作用：建文件或目录；-Force 使父目录不存在也自动建
```

```powershell
# ④ Copy-Item
Copy-Item -Path "$root\data\cats_dogs\raw\cat.1.jpg" -Destination "$root\data\cats_dogs\train\cat\"
# 常用参数：-Recurse（复制目录树）、-Force（覆盖）
```

```powershell
# ⑤ Move-Item / Rename-Item
Move-Item -Path "$root\temp\cache.tmp" -Destination "$root\data\cats_dogs\raw\"
Rename-Item -Path "$root\data\cats_dogs\raw\cache.tmp" -NewName "cat.999.jpg"
```

```powershell
# ⑥ Remove-Item
Remove-Item -Path "$root\temp\*" -Recurse -Force -WhatIf
# ⚠️ 注意：真实删除前必须先跑一遍 -WhatIf
```

```powershell
# ⑦ Get-Content / Set-Content / Add-Content
Get-Content "$root\projects\digit_cls\logs\train_20261014.log" -Tail 5
Set-Content -Path "$root\projects\digit_cls\config.yaml" -Value "lr: 0.001"
Add-Content  -Path "$root\projects\digit_cls\config.yaml" -Value "epochs: 20"
```

```powershell
# ⑧ Test-Path / Join-Path
Test-Path "$root\models\v1\weights.pt"                  # True / False
Join-Path $root "data" "cats_dogs" "raw"                # 避免手拼反斜杠
```

### 引号与空格（有空格，换行，制表符加引号）

```powershell
Set-Location "D:\桌面\AILab\data\my data"               # 必须加引号
$name = "图片 备份.zip"
Join-Path "D:\桌面\AILab\data\my data" $name
```

### 动手练习

- **必做：** 统计 `raw` 下 `cat.*.jpg` 与 `dog.*.jpg` 各多少张；用 `New-Item` 建 `test\cat`、`test\dog`。
- **选做：** 把 `temp\old\dump.log` 移到 `projects\digit_cls\logs\` 并重命名为 `dump_old.log`。

### 常见报错与排查

- **"找不到路径"** → 先用 `Test-Path`；检查空格路径是否漏引号。
- **"项已存在"** → `New-Item` 加 `-Force`。
- **`-Filter` 与 `-Include` 结果不同** → `-Filter` 由文件系统过滤（快），`-Include` 由 PS 过滤且需配 `-Recurse`。

### 本章小结

1. 导航铁三角：`Set-Location` / `Get-ChildItem` / `New-Item`。
2. 删除前先 `-WhatIf`，这是最重要的习惯。
3. 路径含空格必须加引号，拼接用 `Join-Path`。

---

## 第 3 章 管道与对象（核心）

**学完能做什么：** 一行命令找出最大模型文件、按类别分组统计数据集、从日志中提取错误行。

### 对象管道 vs 文本管道（同一任务两种写法）

任务：找出 `raw` 下最大的 3 个文件。

```powershell
# PowerShell：传对象，直接取 Length 属性，文件名带空格也不会错位
Get-ChildItem "$root\data\cats_dogs\raw" -File |
  Sort-Object Length -Descending |
  Select-Object -First 3 Name, @{Name='SizeKB';Expression={[math]::Round($_.Length/1KB,2)}}
```

```batch
REM bash/cmd 风格：文本流，要靠切列（仅作对照，不推荐）
dir /b /s "D:\桌面\AILab\data\cats_dogs\raw\*.jpg"
```

### 核心管道命令（全部用本库数据）

```powershell
# Where-Object：筛选
Get-ChildItem $root -Recurse -File | Where-Object { $_.Length -gt 1MB }

# Select-Object：挑属性 + 计算列
Get-Process python | Select-Object Name, Id, @{Name='MemMB';Expression={[math]::Round($_.WS/1MB)}}

# Sort-Object：排序
Get-ChildItem "$root\models" -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# Group-Object：分组（数据集质量检查利器）
Get-ChildItem "$root\data\cats_dogs\raw" -File | Group-Object { $_.Name.Split('.')[0] }

# Measure-Object：统计
Get-ChildItem "$root\data\cats_dogs\raw" -File | Measure-Object Length -Sum -Average

# ForEach-Object：逐项处理
Get-ChildItem "$root\data\cats_dogs\raw\cat.*.jpg" |
  ForEach-Object { Rename-Item $_ -NewName ("cat_" + $_.Name) }
```

> 简化语法（PS 3.0+）：`Where-Object Name -like "cat.*"`，无花括号时性能更好。

### 文本搜索对照

```powershell
Select-String -Path "$root\projects\digit_cls\logs\*.log" -Pattern "ERROR" |
  Select-Object Path, LineNumber, Line

findstr /s /i "error" "D:\桌面\AILab\projects\digit_cls\logs\*.log"   # 旧工具对照
```

### 输出格式

```powershell
Get-ChildItem $root -Recurse -File | Select-Object FullName, Length | Format-Table -AutoSize
```

⚠️ **注意：** `Format-*` 必须放在管道**末尾**，它会把对象变成格式记录，之后无法再取属性。

### 进阶教学与最复杂例子逐处拆解

#### 3.0 先补概念：管道到底在传什么（举例前必读）

在 bash 里，`|` 右边接的是**一串字符**，所以你得靠 `awk '{print $3}'`、`cut -d' ' -f2` 去"数空格切第几列"——本质是在**猜文本的结构**。PowerShell 的 `|` 右边接的是**活的 .NET 对象**：`Get-ChildItem` 吐出的不是"文件名那行字"，而是一个个 `FileInfo` 对象，自带 `Name`、`Length`、`LastWriteTime`、`Extension` 等**属性（property）**和可调用的**方法（method）**。

由此产生三个必须建立的直觉：

1. **属性即列名**：管道下游想用某个数据，直接写 `.` + 属性名，比如 `$_.Length`。属性名拼错不会报错、只会输出空——所以排查第一步永远是 `| Get-Member` 看真实属性名。
2. **`$_` 是"当前这一个"**：管道是逐个对象流动的，花括号里的 `$_` 就代表"正流到我面前的这个对象"。`$_.Name` 读它的名字，`$_.Length -gt 1MB` 判断它大不大。
3. **计算属性是"现造一列"**：对象本身没有的属性（比如"把字节换算成 MB"），可以用 `@{Name='...';Expression={...}}` 临时造一列，`Expression` 里写怎么算。这是本章最值钱、也最容易看懂的例子。

把这三点想通，下面的命令就不是"要背的咒语"，而是"对象在传送带上依次被加工作业"。

#### 3.1 最复杂例子逐处拆解：计算属性链

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File |
  Sort-Object Length -Descending |
  Select-Object -First 3 Name, @{Name='SizeKB';Expression={[math]::Round($_.Length/1KB,2)}}
```

逐段说明：

- `Get-ChildItem "$root\...\raw" -File`：产出一批 `FileInfo` 对象。`-File` 保证只要文件、把目录排除掉（否则目录也会被当成对象混进后面排序，目录的 `Length` 是 0，会干扰"最大文件"的判断）。
- 第一根 `|`：把这批对象**一个一个**送给右边。此刻传送带上仍是完整的 `FileInfo` 对象，不是文本。
- `Sort-Object Length -Descending`：按对象的 `Length` 属性（字节数）排序，`-Descending` 从大到小。注意它写的是属性名 `Length` 而不是 `$_.Length`——`Sort-Object` 是"按属性排序"，直接吃属性名，不需要 `$_`。这一步会**缓冲全部输入**才输出（排序必须看完全部才知道谁最大）。
- 第二根 `|`：排好序的对象继续往下流。
- `Select-Object -First 3 Name, @{...}`：只放行前 3 个对象，并**只输出你点名的列**——`Name` 是对象自带属性；后面那坨 `@{...}` 是计算属性。
- `@{Name='SizeKB';Expression={...}}`：一个**哈希表**，PowerShell 约定它就是"计算属性定义"。`Name` 是新列的表头（叫 SizeKB）；`Expression` 是"这一列每行怎么算"的脚本块。
- `[math]::Round($_.Length/1KB,2)`：`$_` 是当前这个文件对象，`$_.Length` 取它的字节数，`/1KB`（1KB 是 PowerShell 内置常量 1024）换算成 KB，`[math]::Round(...,2)` 把结果四舍五入到 2 位小数。`[math]::Round` 是 .NET 静态方法调用写法（见第5章教学）。

为什么这个例子最能体现"对象管道"的价值：文件叫 `dog.10.jpg` 还是 `图片 备份.zip` 都无所谓——我们取的是 `.Length` **属性值**，不靠空格切列，所以文件名里带空格、带中文都绝不会错位。这正是文本管道 `dir | sort` 永远做不到的可靠性。

#### 3.2 次复杂例子拆解：按脚本块分组

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File |
  Group-Object { $_.Name.Split('.')[0] } |
  Select-Object Name, Count
```

- `Group-Object { ... }` 的脚本块**不返回布尔值**（那是 `Where`），而是返回一个**"分组键"**：PowerShell 把返回值相同的对象归到同一组。
- `$_.Name.Split('.')[0]`：把 `cat.123.jpg` 按 `.` 切成数组 `@('cat','123','jpg')`，取 `[0]` 得到 `cat`。于是所有前缀是 `cat` 的归一组、`dog` 的归一组。
- 分组后每个组是一个 `GroupInfo` 对象，`Name` 是组键（`cat`/`dog`），`Count` 是组内对象个数。`Select-Object Name, Count` 只留这两列——用来一眼看出 **cat 和 dog 数量是否均衡**（数据集最常见的质量坑）。
- 想更省内存、输出更干净，加 `-NoElement`：`Group-Object ... -NoElement`，只留 `Count` 不留组员。

#### 3.3 `Measure-Object` 结果的"取数"陷阱

```powershell
$totalMB = [math]::Round((Get-ChildItem "$root\data\cats_dogs\raw" -File | Measure-Object Length -Sum).Sum / 1MB, 2)
```

`Measure-Object` 输出的不是一个数字，而是一个带 `.Count/.Sum/.Average/.Maximum` 等属性的**统计对象**。所以外层要 `(...).Sum` 才能把总和抠出来，不能直接当数用。空输入时 `.Sum` 是 0 但 `.Average` 是 `$null`，做除法前要先判空——这是运行期 `null` 报错的高频来源。

（本章其余命令的教学与前一轮"参数展开"中的对应小节衔接，不再重复；新增的"逐处拆解"到这里覆盖了本章最复杂与次复杂的两处。）



### 动手练习

- **必做：** 一行命令输出本库所有 `.log` 文件的总行数（提示：`Get-Content | Measure-Object -Line`）。
- **选做：** 用 `Group-Object` 统计 `raw` 下 cat/dog 文件数，找出数量不等的问题。

### 常见报错与排查

- **管道无输出** → 用 `Get-Member` 确认属性名；条件过严。
- **排序混乱** → 属性是字符串而非数字，先转换类型。

### 本章小结

1. 管道传**对象**不是文本——这是与 bash 的根本差异。
2. `Where → Select → Sort → Group → Measure` 是五件套。
3. `Format-*` 只做最终展示，永远放最后。

---

## 第 4 章 重定向、变量与文本

**学完能做什么：** 把训练输出存成日志、合并标准输出与错误、解决中文乱码。

### 重定向（以跑训练为例）

```powershell
python "$root\projects\digit_cls\train.py" > out.txt            # 成功流覆盖
python "$root\projects\digit_cls\train.py" >> out.txt           # 追加
python "$root\projects\digit_cls\train.py" 2> err.txt           # 仅错误
python "$root\projects\digit_cls\train.py" *> all.log           # 全部流合并（最实用）
Get-ChildItem -Recurse | Measure-Object | Out-Null              # 丢弃输出
```

### 变量与字符串

```powershell
$root  = "D:\桌面\AILab"
$run   = "v1"
$epoch = 20

Write-Output "Run $run, epochs $epoch"        # 双引号：插值
Write-Output 'Run $run, epochs $epoch'        # 单引号：原样
Write-Output "Path: ${root}\models\${run}"    # ⚠️ 变量紧贴字母/反斜杠时用 {}
```

### 编码问题（本库 notes.txt 就是陷阱）

```powershell
Get-Content "$root\notes.txt"                              # 可能乱码
Get-Content "$root\notes.txt" -Encoding default            # GBK 正常
Get-Content "$root\projects\digit_cls\logs\train_20261014.log" -Encoding utf8

Select-String -Path "$root\projects\digit_cls\logs\*.log" -Pattern "ERROR" |
  Out-File -FilePath "$root\errors.txt" -Encoding utf8
```

⚠️ **注意：** PS 5.1 默认编码随系统区域（中文 Windows 多为 GBK），而 Python 3 默认 UTF-8。**跨语言交接处一律显式写 `-Encoding utf8`**。

### 进阶教学与最复杂例子逐处拆解

#### 4.0 先补概念：六条流，以及 `2>&1` 为什么那么绕

PowerShell 里每个命令的输出不是"一股脑"往外冒，而是分**六条流（stream）**同时往外送：

```text
1 = 成功流（Success）   2 = 错误流（Error）    3 = 警告（Warning）
4 = 详细（Verbose）     5 = 调试（Debug）      6 = 信息（Information）
```

平时你看到的"正常结果"走 1 号流，红字报错走 2 号流。重定向的本质就是"把某条流接到文件/另一条流上"。理解了流编号，那些符号就不再神秘。

#### 4.1 最复杂例子逐处拆解：合并流并追加

```powershell
python "$root\projects\digit_cls\train.py" 2>&1 >> all.log
```

- `python train.py`：启动一个**外部程序**。外部程序不是 PowerShell cmdlet，它没有 PowerShell 的流模型——它只有操作系统层面的"标准输出(stdout)"和"标准错误(stderr)"两股。
- `2>&1`：把 **2 号流重定向到 1 号流**（`>` 左边是"要被搬走的流"，`&1` 的 `&` 表示"右边接的是另一条流，而不是文件名"）。作用：让错误也并进正常输出里，两者按发生顺序交织，日志才不失真。
- `>> all.log`：把（已经并好流信息的）输出**追加**写入 `all.log`，`>>` 是追加、`>` 是覆盖。
- 组合结果：训练程序的正常打印和报错**按真实时间顺序**一起进 `all.log`。
- 对比更简单的写法：`python train.py *> all.log`——`*>` 是"全部六条流一把抓"，最省事；`2> err.log` 是"只把错误单独存"。三者按需求选：要分诊用 `2>`，要全留用 `*>`，要正常+错误交织且追加用 `2>&1 >>`。

#### 4.2 字符串插值的"边界"教学与 `${}` 拆解

```powershell
$root = "D:\桌面\AILab"; $run = "v1"
Write-Output "Path: ${root}\models\${run}"     # 正确：Path: D:\桌面\AILab\models\v1
Write-Output "Path: $root\models\$run"          # 可能出问题，见下
```

- 双引号里的 `$名字` 会被替换成变量值，这叫**插值（interpolation）**；单引号原样输出。
- 坑在**变量名的边界**：PowerShell 从 `$` 开始，会一直吞后面合法的变量名字符。`$root\models` 里，`\` 之后它可能把想表达的边界搞混；更典型的 `$run_backup` 会被当成一个叫 `run_backup` 的变量（而不是 `$run` + `_backup`）。
- `${...}` 是**显式圈定变量名边界**：`${root}` 明确"变量名就到 root 为止"。写路径把变量紧贴字母/反斜杠时，养成用 `${}` 的习惯，比事后 debug 省命。

#### 4.3 编码为什么会乱（先懂再修）

字节在磁盘上是一串二进制，"这串字节对应哪个字"取决于用哪本"字典"去读——这就是编码。同一份字节：用 GBK 字典读是"旧笔记"，用 UTF-8 字典读就是乱码方块。

- PS 5.1 读写默认跟随**系统区域**（中文 Windows 常是 GBK），Python 3 默认 **UTF-8**。两个默认值不一致，交接处必乱。
- 唯一的稳妥规则：**读的时候显式 `-Encoding`（猜不准就先 `default` 再 `utf8` 试），写的时候永远显式 `-Encoding utf8`**。
- PS 5.1 的 `utf8` **带 BOM**（文件头三个字节）；下游若拒认 BOM（某些老 Python/工具），升 PS 7 用 `-Encoding utf8NoBOM`，或用 `[System.IO.File]::WriteAllText()` 精确控制。



### 动手练习

- **必做：** 把 `notes.txt` 转存为 UTF-8（读用 `-Encoding default`，写用 `-Encoding utf8`），再用 Python 读取验证。
- **选做：** 运行一个不存在的命令，把错误流单独存到 `err.txt`。

### 常见报错与排查

- **中文变问号** → 写入时没指定编码；或编辑器存成了 UTF-8 BOM。
- **`$var` 没展开** → 误用单引号，或变量后紧跟合法字符需用 `${}`。

### 本章小结

1. `>` 覆盖、`>>` 追加、`2>` 错误、`*>` 全部合并。
2. 双引号插值、单引号原样、变量贴字用 `${}`。
3. 跨语言文件交接显式指定编码。

---

## 第 5 章 环境与系统

**学完能做什么：** 让 Python/pip 在任何窗口都能调用、看懂退出码、监控 GPU、定时跑脚本。

### PATH 与环境变量

```powershell
$env:PATH                                  # 查看
$env:PATH -split ';'                       # 分行看更清楚
$env:PATH -contains "*python*"             # 快速判断 Python 是否在 PATH（实际用 -match 或 -like）

$env:PATH += ";D:\桌面\AILab\scripts"      # 临时生效（当前会话）

# 持久化（用户级，无需管理员）
$userPath = [Environment]::GetEnvironmentVariable("PATH","User")
[Environment]::SetEnvironmentVariable("PATH", "$userPath;D:\桌面\AILab\scripts", "User")
```

⚠️ **注意：** 持久化后**已有终端窗口不会自动生效**，必须重开；且不要反复追加导致 PATH 膨胀（先读出判断是否已存在）。

### 权限与 UAC

```powershell
Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -Command Set-Location 'D:\桌面\AILab'"
```

### 退出码与错误流

```powershell
python "$root\projects\digit_cls\train.py"
$LASTEXITCODE        # 0=成功，非 0=失败
$Error[0]            # 最近一条 PowerShell 错误
$Error.Clear()
```

### 进程与 GPU

```powershell
Get-Process python | Select-Object Id, CPU, @{Name='MemMB';Expression={[math]::Round($_.WS/1MB)}}
Stop-Process -Name python -Confirm
nvidia-smi                                # 外部工具，照样直接调用
```

### 计划任务（每天凌晨 2 点备份 models）

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -File D:\桌面\AILab\scripts\backup.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "AILabBackup" -Action $action -Trigger $trigger -RunLevel Highest
```

### 进阶教学与最复杂例子逐处拆解

#### 5.0 先补两个概念：环境变量的"三个存储层"，和 .NET 静态方法调用

**(a) 环境变量的三层存储**——这是"我改了 PATH 怎么没生效"的根源：

| 层（Target） | 作用范围 | 是否持久 | 需管理员 |
|---|---|---|---|
| `Process` | 只当前这个终端进程 | 否，关掉就没了 | 否 |
| `User` | 当前用户所有新进程 | 是 | 否 |
| `Machine` | 整机所有用户的新进程 | 是 | 是 |

关键：`$env:PATH += ...` 只改 **Process 层**（临时）；`[Environment]::SetEnvironmentVariable(...,"User")` 改的是**注册表里的 User 层**（持久），但**已经在跑的终端读的是自己启动那一刻的快照**，所以必须**重开终端**才看得到持久化的改动。

**(b) 方括号 .NET 静态方法调用语法**：`[类名]::方法名(参数)`。方括号 = "去 .NET 世界找这个类"，`::` = "调它的静态方法"。看懂这个，`[math]::Round`、`[Environment]::SetEnvironmentVariable`、`[Console]::OutputEncoding` 就全是一套路子。不确定类有哪些方法，用 `[Environment] | Get-Member -Static` 查。

#### 5.1 最复杂例子逐处拆解：注册计划任务

```powershell
$action  = New-ScheduledTaskAction  -Execute "powershell.exe" -Argument "-NoProfile -File D:\桌面\AILab\scripts\backup.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "AILabBackup" -Action $action -Trigger $trigger -RunLevel Highest
```

- 这套命令的思想是**"把三块拼图分别做好再组装"**：任务由"做什么(action) + 什么时候(trigger) + 注册(起个名字)"三部分组成，Windows 故意让你分开造再拼。
- `New-ScheduledTaskAction`：造"做什么"对象。`-Execute` 是要跑的程序（这里跑 PowerShell 本身），`-Argument` 是传给它的命令行参数。
  - `-NoProfile`：启动时**不加载 Profile**，避免你的个性化配置（比如自动 `cd`、自定义 Prompt）在无人值守的计划任务里惹出意外，让脚本在干净环境跑。
  - `-File ...backup.ps1`：真正要执行的脚本路径。
- `New-ScheduledTaskTrigger -Daily -At "02:00"`：造"什么时候"对象——每天 02:00 触发。
- `Register-ScheduledTask`：把上面两个对象**拼成一个已注册的任务**。`-TaskName` 是任务计划程序里显示的名字；`-RunLevel Highest` 请求以最高权限运行（等价"以管理员身份"，脚本若要写系统目录就需要它）。
- 常见坑：路径里有空格或中文（`D:\桌面\AILab`）时，`-Argument` 里的路径要确保能被正确解析，必要时给路径再加一层引号。

#### 5.2 计算列再看一例（进程内存）

```powershell
Get-Process python | Select-Object Id, CPU, @{Name='MemMB';Expression={[math]::Round($_.WS/1MB)}}
```

`Get-Process` 吐 `Process` 对象；`WS`（Working Set）是占用的物理内存字节数，对象本身没有"多少 MB"这一列，故用计算属性 `[math]::Round($_.WS/1MB)` 现造一个 `MemMB`。训练进程卡死时先这行看哪个 `Id` 内存暴涨，再 `Stop-Process -Id <那个Id>`——**用 Id 比 `-Name python` 精确**，避免误杀别的 python 进程。



### 动手练习

- **必做：** 用 `$env:PATH -split ';'` 找到 Python 的安装路径；把 `D:\桌面\AILab\scripts` 临时加入 PATH。
- **选做：** `python -c "exit(1)"`，用 `$LASTEXITCODE` 捕获并写进 `status.txt`。

### 常见报错与排查

- **"无法将 python 识别为 cmdlet"** → PATH 里没有；或用 `py` 启动器代替。
- **修改 PATH 后仍找不到** → 重开终端；检查是否写进 Machine 级却被 User 级覆盖。

### 本章小结

1. `$env:VAR` 读写变量，`[Environment]::SetEnvironmentVariable` 持久化，改完重开终端。
2. `$LASTEXITCODE` 看外部程序成败，`$Error` 看 PS 自身错误。
3. `Stop-Process` 和 `nvidia-smi` 是训练卡死/显存溢出时的第一响应工具。

---

## 第 6 章 脚本化

**学完能做什么：** 把零散命令写成可复用脚本，支持传参、调试与开机自载配置。

### 条件与循环（本库版）

```powershell
$logDir = "D:\桌面\AILab\projects\digit_cls\logs"
if (Test-Path $logDir) {
    Get-ChildItem $logDir -Filter "*.log" | ForEach-Object { Write-Output $_.FullName }
} else {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
```

### 函数 + param（统计数据集）

```powershell
function Get-DatasetSummary {
    param(
        [Parameter(Mandatory=$true)][string]$Root,
        [string[]]$Extensions = @(".jpg",".png"),
        [switch]$Verbose
    )
    $files = Get-ChildItem -Path $Root -Recurse -File | Where-Object { $_.Extension -in $Extensions }
    [PSCustomObject]@{
        Root    = $Root
        Count   = $files.Count
        TotalMB = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 2)
    }
}

Get-DatasetSummary -Root "D:\桌面\AILab\data\cats_dogs\raw"
```

### 执行策略（Execution Policy）

```powershell
Get-ExecutionPolicy -List
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

> 执行策略是**防误执行机制**而非安全边界；`RemoteSigned` 允许本地脚本运行，网络下载脚本需签名。

### 调试

```powershell
Write-Verbose "处理文件: $_" -Verbose
Write-Host "进度 50%" -ForegroundColor Cyan      # 只给人看，不进管道
Set-PSBreakpoint -Script "D:\桌面\AILab\scripts\rename_dataset.ps1" -Line 8
```

### Profile（每次开终端自动进本库）

```powershell
notepad $PROFILE.CurrentUserCurrentHost
# 写入：
Set-Location "D:\桌面\AILab"
function Prompt { "AILab [$((Get-Location).Path.Split('\')[-1])]> " }
```

### PSReadLine 快捷键

```text
Ctrl+R   反向搜索历史    Alt+.  插入上一条命令最后一个参数
Tab      补全命令/路径/参数名    Shift+Tab  反向补全
```

### 进阶教学与最复杂例子逐处拆解

#### 6.0 先补三个概念：`param` 属性、开关参数、`PSCustomObject`

1. **`param()` 是脚本/函数的"参数契约"**：写明了就能传参、有默认值、能强制必填。`[Parameter(Mandatory=$true)]` 让调用者不传就直接报错并提示，比脚本里手写 `if(-not $x){throw}` 规范。
2. **`[switch]` 开关参数**：声明成 `[switch]` 后，调用时"写 `-Recurse` 就等于 `$true`，不写就是 `$false`"——**不要写成 `-Recurse $true`**。
3. **`[PSCustomObject]@{...}`**：把一堆散变量**打包成一个带命名属性的对象**返回。好处是调用方能 `.Count`、`.TotalMB` 直接取字段，也能直接丢进 `Format-Table` 成一张表。这是 PowerShell 里"自定义返回结构"的标准做法。

#### 6.1 最复杂例子逐处拆解：`Get-DatasetSummary` 函数

```powershell
function Get-DatasetSummary {
    param(
        [Parameter(Mandatory=$true)][string]$Root,
        [string[]]$Extensions = @(".jpg",".png"),
        [switch]$Verbose
    )
    $files = Get-ChildItem -Path $Root -Recurse -File | Where-Object { $_.Extension -in $Extensions }
    [PSCustomObject]@{
        Root    = $Root
        Count   = $files.Count
        TotalMB = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 2)
    }
}
Get-DatasetSummary -Root "D:\桌面\AILab\data\cats_dogs\raw"
```

逐处：

- `param(...)` 必须是函数**第一条语句**（注释、空行除外）。
- `[Parameter(Mandatory=$true)][string]$Root`：`$Root` 必填、且约束成字符串。调用者漏传就报错。
- `[string[]]$Extensions = @(".jpg",".png")`：`[string[]]` 是字符串**数组**类型；给了默认值，不传就用这两个扩展名；传 `-Extensions ".jpg"` 可覆盖。
- `[switch]$Verbose`：开关，调用时 `-Verbose` 即开。
- `$files = Get-ChildItem ... | Where-Object { $_.Extension -in $Extensions }`：先递归列出所有文件对象，再用 `Where` 只保留扩展名**落在 `$Extensions` 数组里**的对象。`-in` 是"值是否在集合中"，等价于多个 `-or` 的简写。
- `[PSCustomObject]@{ Root=...; Count=...; TotalMB=... }`：把结果打包成一个对象。
  - `Count = $files.Count`：数组的 `.Count` 属性即文件个数。
  - `TotalMB = [math]::Round((... | Measure-Object Length -Sum).Sum / 1MB, 2)`：注意**两层括号**——`( $files | Measure-Object Length -Sum )` 先得到一个统计对象，紧跟的 `.Sum` 抠出总字节，再 `/1MB` 换 MB、`Round(...,2)` 保留两位。这里是"先管道统计、再点属性取数"的嵌套，是最容易看花眼的一处，务必拆成两步理解。
- 最后一行调用：只传必填的 `-Root`，扩展名用默认，返回对象可直接 `Format-Table`。



### 动手练习

- **必做：** 编写 `D:\桌面\AILab\scripts\count_logs.ps1`，接受 `-LogDir` 参数，输出含 `ERROR` 的行数。
- **选做：** 在 Profile 里加一个函数，一键进入 `digit_cls` 并激活 `.venv`。

### 常见报错与排查

- **"无法加载文件…禁止运行脚本"** → `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`。
- **脚本中文乱码** → 保存为 UTF-8。
- **`param()` 无效** → `param` 必须是脚本或函数的**第一行**。

### 本章小结

1. 用 `param()` 声明参数，脚本才有复用价值。
2. `Write-Output` 进管道、`Write-Host` 只给人看、`Write-Verbose` 可开关。
3. Profile + PSReadLine 是长期效率投资。

---

## 第 7 章 AI 学生实战

**学完能做什么：** 一条龙完成环境配置→训练→日志排查→数据集整理→Git 提交，并绕开国内网络常见坑。

### 虚拟环境与 pip

```powershell
Set-Location "D:\桌面\AILab\projects\digit_cls"
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # 提示符前出现 (.venv) 即成功
pip install -r requirements.txt
deactivate
```

⚠️ **注意：** 激活本质是修改 `$env:PATH`，**关掉终端就失效**；激活脚本受执行策略限制。

```powershell
pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple                 # 临时
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple      # 永久
```

### 命令行传参跑训练

```powershell
python train.py --data "D:\桌面\AILab\data\cats_dogs" --epochs 20 --batch-size 32 `
  *> ".\logs\train_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
```

### 批量整理数据集（实战核心脚本）

```powershell
$src = "D:\桌面\AILab\data\cats_dogs\raw"
$dst = "D:\桌面\AILab\data\cats_dogs\train"

Get-ChildItem $src -File -Filter "*.jpg" | ForEach-Object {
    $label = if ($_.Name -like "cat.*") { "cat" } else { "dog" }
    $destDir = Join-Path $dst $label
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item -Path $_.FullName -Destination $destDir -WhatIf     # 先 -WhatIf 试跑！
}
```

### 日志排查（grep 式）

```powershell
Select-String -Path ".\logs\*.log" -Pattern "ERROR|Exception" -CaseSensitive:$false |
  Select-Object Filename, LineNumber, Line | Format-Table -Wrap

Get-Content (Get-ChildItem ".\logs\*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName -Tail 30
```

### Git 常用命令行

```powershell
git init; git add .; git status; git commit -m "init digit_cls"; git log --oneline -5
# .gitignore：__pycache__/  *.pt  .venv/  data/  *.log  temp/
```

### 国内环境常见坑

|现象|解法|
|---|---|
|pip 安装超时|`pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`|
|终端中文乱码|`chcp 65001`；Terminal 配置中把编码改为 UTF-8|
|代理导致连不上|`$env:HTTP_PROXY=""; $env:HTTPS_PROXY=""`|
|`Activate.ps1` 被拦截|`RemoteSigned -Scope CurrentUser`|

### 进阶教学与最复杂例子逐处拆解

#### 7.0 先补三个概念：管道当循环、条件赋值、子表达式 `$()`

1. **管道即隐式循环**：`Get-ChildItem ... | ForEach-Object { ... }` 等于"对每个文件执行花括号里的代码"，花括号里 `$_.xxx` 指当前文件。
2. **条件表达式赋值**：`$label = if (条件) {"cat"} else {"dog"}`——PowerShell 里 `if` 是**能返回值的表达式**，可直接把分支结果赋给变量（这点比很多语言方便，但需要知道）。
3. **子表达式 `$()`**：在双引号字符串里，`$()` 会**先执行括号里的命令、再把结果文本插入字符串**。想在文件名里塞一个动态生成的时间戳/命令结果，就靠它。

#### 7.1 最复杂例子逐处拆解：批量整理数据集

```powershell
$src = "D:\桌面\AILab\data\cats_dogs\raw"
$dst = "D:\桌面\AILab\data\cats_dogs\train"

Get-ChildItem $src -File -Filter "*.jpg" | ForEach-Object {
    $label = if ($_.Name -like "cat.*") { "cat" } else { "dog" }
    $destDir = Join-Path $dst $label
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Copy-Item -Path $_.FullName -Destination $destDir -WhatIf
}
```

逐处：

- `Get-ChildItem $src -File -Filter "*.jpg"`：先把 raw 下所有 jpg 作为文件对象产出（`-File` 排除目录，`-Filter` 文件系统级快过滤）。
- `| ForEach-Object { ... }`：对这些对象**逐个**执行花括号——这就是"对每张图做一遍归类"的循环。
- `$label = if ($_.Name -like "cat.*") {"cat"} else {"dog"}`：读当前文件名 `$_.Name`，用 `-like`（通配符，`cat.*` 匹配 cat 开头）判断是猫是狗，把标签字符串赋给 `$label`。这是上面说的"条件表达式赋值"。
- `$destDir = Join-Path $dst $label`：把目标根目录和标签拼成完整子目录路径（`...\train\cat` 或 `...\train\dog`），用 `Join-Path` 避免手拼反斜杠出错。
- `if (-not (Test-Path $destDir)) { New-Item ... -Force | Out-Null }`：**先判断目录在不在**（`Test-Path` 返回假再 `-not` 取反），不在就建。`| Out-Null` 是因为 `New-Item` 会吐一个对象，不丢掉的话它会顺着管道继续往下搅乱流程。
- `Copy-Item -Path $_.FullName -Destination $destDir -WhatIf`：把当前文件（`$_.FullName` 是完整路径，确保来源无歧义）复制到对应类别目录。`-WhatIf` 让这次**只演示不真动**——这是第8章安全三步走的第一拍，确认可复制对了，去掉 `-WhatIf` 再真跑。

#### 7.2 动态日志文件名拆解（子表达式实战）

```powershell
python train.py --epochs 20 *> ".\logs\train_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
```

- `*> ...`：把训练程序的**全部流**重定向进文件。
- 文件名里的 `$(Get-Date -Format 'yyyyMMdd_HHmm')`：子表达式先跑 `Get-Date` 按格式生成如 `20261016_2233` 的时间戳，再拼进引号里，最终文件名形如 `train_20261016_2233.log`。这样每次训练自动落一份不覆盖、可排序的日志。
- 反例：若不用 `$()` 而写 `"train_Get-Date.log"`，那只会得到字面的 `train_Get-Date.log`——理解"`$()` 是执行、纯文字是照抄"是关键。



### 动手练习

- **必做：** 去掉 `-WhatIf` 运行整理脚本，把 `raw` 分到 `train/cat`、`train/dog`，再统计两边数量是否相等。
- **选做：** 写 `run_train.ps1`：激活虚拟环境→带参训练→日志按时间戳落盘→非零退出码打印告警。

### 常见报错与排查

- **`ModuleNotFoundError`** → 忘记激活虚拟环境，或 VS Code 选的解析器不是 `.venv` 里的。
- **Git 提交大文件失败** → `data/` 与 `*.pt` 未加入 `.gitignore`。

### 本章小结

1. 激活虚拟环境 = 改 PATH，会话级生效。
2. 数据集整理脚本务必先 `-WhatIf` 试跑。
3. 日志排查首选 `Select-String`，比 `findstr` 可组合性强得多。

---

## 第 8 章 安全与效率

**学完能做什么：** 养成"先模拟后执行"的肌肉记忆，避免一条命令毁掉整个数据集。

### 危险操作防范

```powershell
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force -WhatIf     # 第一步：只看会删什么
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force -Confirm    # 第二步：逐条确认
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force             # 第三步：真删
```

通用规则：**任何含 `-Recurse` 的删除/覆盖操作，都按 WhatIf → Confirm → 执行三步走**。

### 安全试错技巧

```powershell
Set-StrictMode -Version Latest          # 未定义变量直接报错
$ErrorActionPreference = "Stop"         # 配合 try/catch 使用
```

### 速查表

|我要…|命令|
|---|---|
|进目录|`Set-Location` (`cd`)|
|列文件|`Get-ChildItem -Filter -Recurse -Depth`|
|建目录/文件|`New-Item -ItemType Directory -Force`|
|复制/移动/删除|`Copy-Item` / `Move-Item` / `Remove-Item -WhatIf`|
|读/写/追加|`Get-Content -Tail` / `Set-Content` / `Add-Content`|
|筛/选/排/分/统|`Where` / `Select` / `Sort` / `Group` / `Measure`|
|搜文本|`Select-String -Pattern`|
|环境变量|`$env:VAR` / `[Environment]::SetEnvironmentVariable`|
|退出码/错误|`$LASTEXITCODE` / `$Error[0]`|
|执行策略|`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`|

### 延伸资源

- Microsoft Learn PowerShell 官方文档 【待补充】
- PowerShell 7 发行说明（GitHub）【待补充】
- Windows Terminal 官方配置文档 【待补充】
- 《Learn PowerShell in a Month of Lunches》【待补充】

### 自测问题

1. 在 `D:\桌面\AILab\data\cats_dogs\raw` 下，用**一条管道命令**输出 cat 与 dog 两类文件各自的数量与总大小（MB），并说明为什么这里不能用 `findstr` 风格的文本管道做法。
2. 你写了 `D:\桌面\AILab\scripts\train.ps1`，双击闪退；在 Terminal 里运行提示"无法加载文件，因为在此系统上禁止运行脚本"。请给出完整排查步骤与修复命令，并说明为什么修改后要重开终端。
3. 执行 `python train.py *> all.log` 后 `all.log` 中文乱码，而 `train_20261014.log` 正常。请分析可能的两处成因，写出对应的验证命令与修复写法。

---

**本文假设核对：** ①主讲 PowerShell 5.1；②虚拟文件库建于 `D:\桌面\AILab`；③未装 WSL，Linux 对比仅作提醒；④Python 已通过 `python` 命令可调；⑤`D:\桌面` 为你手动建立或映射的真实目录（Windows 默认桌面在 `C:\Users\...\Desktop`，若你实际用的是默认桌面，请把 `$root` 改为 `$env:USERPROFILE\Desktop\AILab`）。若你的实际环境不同（如只有 `py` 启动器、或已装 PS 7），告知我，我把对应章节的命令替换为你的版本。

---

下面把前文所有「常用参数」全部展开：先讲 PowerShell 的参数机制（理解这套规则，任何命令的 `Get-Help -Parameter` 你都能自己读懂），再按章节逐条给出**参数含义、默认行为、典型坑与本库实例**。文件库仍用 `D:\桌面\AILab`。

---

### 参数机制总览（先懂这个，后面全是套用）

| 概念                          | 说明                                                                                                    | 例子                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **开关参数（Switch）**            | 写了即生效，不写即关闭，不能赋值                                                                                      | `-Recurse`、`-Force`、`-File`、`-WhatIf`                        |
| **具名参数（Named）**             | `-名 值`，顺序无关                                                                                           | `-Path .\data`、`-Depth 2`                                    |
| **位置参数（Positional）**        | 可省略参数名，靠位置匹配                                                                                          | `Get-ChildItem .\data`（`.` 就是 `-Path`）                       |
| **值类型约束**                   | 字符串要引号，数组用逗号，布尔一般不写 `$true`                                                                           | `-Extensions @(".jpg",".png")`                               |
| **通配符支持**                   | `-Filter` 只认 `* ? []`；`-Pattern`（正则）是另一套                                                              | `-Filter "cat.*"` ≠ `-Pattern "cat\.\d+"`                    |
| **通用参数（Common Parameters）** | 所有 cmdlet 自带：`-WhatIf`、`-Confirm`、`-Verbose`、`-Debug`、`-ErrorAction`（可简写 `-ea`）、`-OutVariable`（`-ov`） | `Remove-Item ... -WhatIf`、`Get-Process -ea SilentlyContinue` |

> 两条铁律：**① 破坏性操作一律先跑 `-WhatIf`；② 不确定参数名就用 `Get-Help 命令 -Parameter 参数名`。**

---

### 第 1 章：自学三件套的参数

#### Get-Help

**这条命令是干什么的：** 查看某个命令的官方帮助文档，是你自学新命令的总入口——告诉你命令怎么用、有哪些参数、并附带示例。

```powershell
Get-Help Get-ChildItem -Full        # 完整帮助（含所有参数说明）
Get-Help Get-ChildItem -Examples    # 只看示例（最省时间）
Get-Help Get-ChildItem -Parameter Filter   # 只看某一个参数的解释
Get-Help Get-ChildItem -Online      # 打开网页版（帮助未更新时最有用）
```

- `-Full`：输出极长，适合初次陌生命令。
- `-Examples`：**日常首选**，直接照抄改路径即可。
- `-Parameter <名>`：精准查某个参数的取值与坑。
- `-Online`：绕过本地帮助库过期问题。

#### Get-Command

**这条命令是干什么的：** 按关键词搜索命令。当你只知道"想干什么"、却想不起命令叫什么名字时，用它把候选命令都列出来。

```powershell
Get-Command *item                   # 名称模糊匹配
Get-Command -CommandType Cmdlet     # 只看 cmdlet（还有 Function/Application/Alias/ExternalScript）
Get-Command python -CommandType Application   # 确认调的是哪个 python.exe
```

- `-CommandType`：区分"PowerShell 内置命令"和"外部程序"，排查"命令找不到"时必用。

#### Get-Member

**这条命令是干什么的：** 查看一个对象都有哪些属性（property）和方法（method）。管道里下一步能用 `$_.谁` 取数据，全靠它查出来的真实属性名。

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" | Get-Member -MemberType Property
Get-Process | Get-Member -Static    # 看静态方法（如 [Environment]::SetEnvironmentVariable 就是这么查出来的）
```

- `-MemberType Property/Method`：缩小输出，避免被几十行方法淹没。
- ⚠️ **注意**：管道左侧必须先有对象，空管道下 `Get-Member` 会报错。

---

### 第 2 章：导航与文件操作参数详解

#### Set-Location

**这条命令是干什么的：** 切换当前工作目录，等同于熟悉的 `cd`。命令里所有相对路径，都以它切到的目录为基准。

```powershell
Set-Location -Path "D:\桌面\AILab\data\my data"
Set-Location -LiteralPath "D:\桌面\AILab\data\my data[old]"   # 路径含 [ ] 等通配符元字符时必须用它
Set-Location ..                                               # 相对跳转
```

- `-Path`：支持通配符（一般不用）。
- `-LiteralPath`：**原样解释路径**，文件名带 `[ ]` 时唯一正确写法。
- 无 `-Recurse`、无 `-Force`——它只是"进目录"。

#### Get-ChildItem（参数最多，也最容易用错）

**这条命令是干什么的：** 列出某个目录下的文件和子目录，等同于 `ls` / `dir`。它是文件操作里用得最频繁、参数也最多的一条命令。

```powershell
Get-ChildItem -Path "$root\data\cats_dogs\raw" `
  -Filter "*.jpg" -File -Recurse -Depth 2 -Force
```

| 参数                      | 作用                       | 默认/坑                                              |
| ----------------------- | ------------------------ | ------------------------------------------------- |
| `-Path`                 | 目标路径，可多个                 | 位置参数，可省略                                          |
| `-LiteralPath`          | 不通配符解析的路径                | 含 `[ ]` 时用                                        |
| `-Filter`               | **文件系统级**过滤，速度最快         | 只支持一个模式（`*.jpg`），不支持正则；`*.*` 会漏掉无扩展名文件            |
| `-Include` / `-Exclude` | **PowerShell 级**过滤，可多个模式 | ⚠️ 必须配合 `-Recurse` 或路径末尾带 `\*` 才生效，这是最常见的"为什么没结果" |
| `-Recurse`              | 递归子目录                    | 深层目录树会很慢，优先用 `-Depth` 限深                          |
| `-Depth n`              | 递归深度上限（PS 5.1 可用）        | 需与 `-Recurse` 同用                                  |
| `-File` / `-Directory`  | 只取文件或目录                  | PS 3.0+；比 `Where {$_.PSIsContainer}` 快且准          |
| `-Name`                 | 只返回名字字符串                 | ⚠️ 返回的是**字符串不是对象**，后续无法取 `.Length`，管道二次处理时别加它     |
| `-Force`                | 显示隐藏/系统文件                | 默认隐藏文件不出现                                         |

```powershell
# 本库实例：数 raw 下 cat/dog 各多少张
(Get-ChildItem -Path "$root\data\cats_dogs\raw" -File -Filter "cat.*").Count
# 本库实例：找整个库里的日志
Get-ChildItem -Path $root -Recurse -Depth 3 -Include "*.log","*.txt" -File
```

#### New-Item

**这条命令是干什么的：** 新建文件或新建文件夹，相当于资源管理器里的"右键 → 新建"。

```powershell
New-Item -Path "$root\data\cats_dogs\test\cat" -ItemType Directory -Force
New-Item -Path "$root\notes.txt" -ItemType File -Value "hello" -Force
```

- `-ItemType`：`Directory` / `File` / `SymbolicLink` / `Junction`。
- `-Value`：新建文件时写入初始内容（等价 `Set-Content`）。
- `-Force`：**目录**时自动创建缺失的父目录；**文件**时覆盖已存在文件的内容（不会报错）。
- `-WhatIf`：建之前先看会建在哪。

#### Copy-Item

**这条命令是干什么的：** 复制文件或文件夹，相当于"复制 + 粘贴"。

```powershell
Copy-Item -Path "$root\data\cats_dogs\raw\cat.*" -Destination "$root\data\cats_dogs\train\cat\" -Force
Copy-Item -Path "$root\models" -Destination "$root\models_bak" -Recurse -Force
```

- `-Destination`：目标；末尾加 `\` 明确表示"放进该目录"，不加且目标不存在时会**改名**。
- `-Recurse`：复制目录树。⚠️ 目标已存在时可能多出一层同名子目录，建议先用 `-WhatIf` 看结构。
- `-Force`：覆盖只读/已存在项。
- `-PassThru`：复制后把新对象输出到管道（做审计日志时有用）。

#### Move-Item / Rename-Item

**这两条命令是干什么的：** `Move-Item` 把文件移动到别处（同一磁盘内移动时等价于改名），`Rename-Item` 专门用来给文件重命名。

```powershell
Move-Item -Path "$root\temp\cache.tmp" -Destination "$root\data\cats_dogs\raw\" -Force
Rename-Item -Path "$root\data\cats_dogs\raw\cache.tmp" -NewName "cat.999.jpg" -PassThru
```

- `-NewName`：**只要名字，不要路径**（写全路径会被当成 Move）。
- 同盘 Move ≈ 重命名（瞬间完成）；跨盘 Move = 复制后删除（慢，且失败时可能留一半）。
- `-Force`：覆盖同名目标。

#### Remove-Item（危险，参数要看清）

**这条命令是干什么的：** 删除文件或文件夹。它是全文最危险的命令——删掉的内容不进回收站，参数用错可能把整棵目录树一次性清空。

```powershell
Remove-Item -Path "$root\temp\*" -Recurse -Force -WhatIf     # 试跑
Remove-Item -Path "$root\temp\*" -Recurse -Force -Confirm    # 逐条确认
Remove-Item -Path "$root\temp\old" -Recurse -Force           # 真删
```

- `-Recurse`：非空目录必须加，否则报错"目录不为空"。
- `-Force`：删除隐藏/只读项；不加时隐藏文件会 silently 留下。
- `-Exclude`：排除某些项，如 `-Exclude "*.bak"`。
- `-LiteralPath`：路径含 `[ ]` 时防误删。
- ⚠️ **三条纪律**：先 `-WhatIf` → 再 `-Confirm` → 最后裸跑；路径用引号包死；绝不写 `Remove-Item \ -Recurse`。

#### Get-Content / Set-Content / Add-Content

**这三条命令是干什么的：** `Get-Content` 读取文件内容（相当于 `cat`），`Set-Content` 覆盖写入文件，`Add-Content` 在文件末尾追加内容。

```powershell
Get-Content "$root\projects\digit_cls\logs\train_20261014.log" -Tail 20 -Encoding utf8
Get-Content "$root\projects\digit_cls\logs\train_20261014.log" -Wait      # 类似 tail -f，实时追日志
Get-Content "$root\notes.txt" -Raw -Encoding default                      # 整个文件读成一个字符串
Set-Content -Path "$root\projects\digit_cls\config.yaml" -Value "lr: 0.001" -Encoding utf8 -NoNewline
Add-Content -Path "$root\projects\digit_cls\config.yaml" -Value "epochs: 20" -Encoding utf8
```

|参数|作用|
|---|---|
|`-Tail n`|只读末尾 n 行（**读大日志必备**，避免把几 GB 日志全塞进内存）|
|`-TotalCount n`（别名 `-Head`）|只读前 n 行|
|`-Raw`|返回**单个字符串**而非字符串数组（要做多行正则匹配时必须加）|
|`-Encoding`|见第 4 章；PS 5.1 可选 `utf8/Unicode/ASCII/default/OEM` 等，`utf8` **带 BOM**|
|`-Wait`|文件增长时持续输出（盯训练进度用）|
|`-ReadCount`|每次吐出的行数，0=一次全吐（提速技巧）|
|`-NoNewline`|写入时不追加换行（写 JSON/单行配置时用）|
|`-Force`（Set/Add）|目标为只读时强制覆盖；创建缺失的中间目录|

#### Test-Path / Join-Path

**这两条命令是干什么的：** `Test-Path` 判断一个路径是否存在（返回 True/False），`Join-Path` 把多个路径片段安全地拼成一个完整路径（自动处理反斜杠）。

```powershell
Test-Path -Path "$root\models\v1\weights.pt" -PathType Leaf          # 是否是"文件"
Test-Path -Path "$root\data" -PathType Container                     # 是否是"目录"
Test-Path -Path "$root\data\cats_dogs\raw" -IsValid                  # 只校验语法合法性，不检查是否存在
Join-Path -Path $root -ChildPath "data" -AdditionalChildPath "cats_dogs","raw"
```

- `-PathType Leaf/Container/Any`：区分文件还是目录（脚本里判断"该不该建目录"的关键）。
- `-IsValid`：**只检查路径格式**是否合法，不碰磁盘；返回 True 不代表文件存在。
- `-Include`/`-Filter`：可配合通配符批量判断。
- `Join-Path`：自动处理反斜杠，跨平台/拼接变量时比 `"$a\$b"` 可靠；`-Resolve` 可顺便验证路径存在。

---

### 第 3 章：管道五件套参数详解

#### Where-Object（两种写法）

**这条命令是干什么的：** 从管道里流过的对象中"筛选"出符合条件的，留下、其余丢弃——相当于 SQL 的 `WHERE`、bash 的 `grep`。

```powershell
# 写法A：脚本块（灵活，可做复杂运算）
Get-ChildItem $root -Recurse -File | Where-Object { $_.Length -gt 1MB -and $_.Extension -in @(".pt",".zip") }
# 写法B：比较语句（PS 3.0+，无花括号，速度快）
Get-ChildItem $root -Recurse -File | Where-Object Extension -in ".jpg",".png"
```

- 比较运算符：`-eq`、`-ne`、`-gt`、`-lt`、`-like`（通配符）、`-match`（正则）、`-in`。
- ⚠️ `-like` 用 `*`，`-match` 用正则；`$_.Name -match "\.jpg$"` 与 `$_.Name -like "*.jpg"` 等价但后者更快。

#### Select-Object

**这条命令是干什么的：** 从对象里挑出你需要的几个属性输出，还能现场算出一个新列——相当于表格里的"选列 + 加公式列"。

```powershell
Get-Process python |
  Select-Object Name, Id, @{Name='MemMB';Expression={[math]::Round($_.WS/1MB,2)}} -First 5
Get-ChildItem $root -Recurse -File | Select-Object -ExpandProperty FullName   # 展开成纯字符串
```

- **计算属性** `@{N='';E={}}`：从现有属性派生新列（单位换算、路径截取最常用）。
- `-First n` / `-Last n` / `-Skip n`：分页取数据；放在管道**越靠前越省内存**。
- `-Unique`：去重（先 `Sort-Object` 再去重更稳）。
- `-ExpandProperty`：把某个属性"剥出来"变成裸值（取纯路径列表传给外部程序时必用）。
- `-ExcludeProperty`：隐藏噪声属性。

#### Sort-Object

**这条命令是干什么的：** 按你指定的属性，对管道里的对象排序（升序或降序）。

```powershell
Get-ChildItem "$root\models" -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

- `-Property`：可多个，如 `Sort-Object DirectoryName, Name`（先按目录再按文件名）。
- `-Descending`：降序。
- `-Unique`：排序同时去重。
- `-CaseSensitive`：大小写敏感。
- ⚠️ 排序会**缓冲全部输入**，对几万条文件对象很慢；能先用 `Where`/`-First` 缩集就先缩。

#### Group-Object

**这条命令是干什么的：** 按某个属性或自定义规则把对象分组，并统计每组的数量——是检查数据集各类别是否均衡的利器。

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File | Group-Object { $_.Name.Split('.')[0] } |
  Select-Object Name, Count | Format-Table -AutoSize
Get-ChildItem $root -Recurse -File | Group-Object Extension -NoElement
```

- `-Property`：可按属性名**或脚本块**分组（按类别名前缀分组检查数据集均衡性，是本库最实用的一招）。
- `-NoElement`：不保留组成员，只留 Count（省内存，输出清爽）。
- `-AsHashTable -AsString`：返回哈希表，后续 `$hash["cat"]` 直接查（写整理脚本时很好用）。

#### Measure-Object

**这条命令是干什么的：** 对管道里的对象做数值统计（求和、平均、最大、最小、计数），或对文本统计行数 / 词数。

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File | Measure-Object Length -Sum -Average
Get-Content "$root\projects\digit_cls\logs\train_20261014.log" | Measure-Object -Line -Word
```

- `-Sum`/`-Average`/`-Max`/`-Min`：数值聚合；结果在 `.Sum` 等属性里，**不是直接输出的数字**，要用 `(...).Sum` 取。
- `-Line`/`-Word`/`-Character`：文本统计（`.Lines`）。
- ⚠️ 空输入时 `.Sum` 为 0 但 `.Average` 为 `$null`，做除法前先判空。

#### ForEach-Object

**这条命令是干什么的：** 对管道流过的每一个对象依次执行一段代码，本质是"对每个东西都做一遍"的循环。

```powershell
Get-ChildItem "$root\data\cats_dogs\raw\cat.*" |
  ForEach-Object -Begin { $i=1 } -Process {
      Rename-Item $_ -NewName ("cat_{0:D4}.jpg" -f $i++) -WhatIf
  } -End { Write-Verbose "共处理 $i 个" -Verbose }
```

- `-Begin`/`-Process`/`-End`：初始化→逐项→收尾（编号重命名、累加统计必需）。
- `-MemberName xxx`（PS 4.0+）：简写 `... | ForEach-Object ToString`。
- `-Parallel`（PS 7+）：并行执行，5.1 没有。
- ⚠️ 性能：处理上万文件时 `foreach($x in $list){}`（语句）比 `| ForEach-Object`（管道）快一个量级；数据量大时改用语句式循环。

#### Select-String（grep 替代品）

**这条命令是干什么的：** 在文件或文本里按正则表达式搜索内容，返回命中的行及其所在的文件名、行号——等价于 Linux 的 `grep`。

```powershell
Select-String -Path "$root\projects\digit_cls\logs\*.log" -Pattern "ERROR|Exception" `
  -CaseSensitive:$false -Context 2,3 -AllMatches | Select-Object Path, LineNumber, Line
```

|参数|作用|
|---|---|
|`-Pattern`|正则表达式（默认），多个模式用逗号|
|`-SimpleMatch`|关闭正则，当纯文本搜（搜 `CUDA out of memory.` 这种带点的原文时推荐）|
|`-CaseSensitive`|默认不区分大小写；加此开关才区分|
|`-Context 前,后`|输出匹配行的前后各 N 行（**定位报错上下文第一选择**）|
|`-AllMatches`|一行多命中全返回|
|`-Quiet`|只返回 True/False（脚本里做"日志是否有错"的判断）|
|`-Encoding`|读中文日志乱码时指定 `utf8`/`default`|
|`-List`|每文件只返回第一个命中（快速筛查哪些文件有问题）|

#### 格式化与输出

**这一组命令是干什么的：** 决定前面处理完的结果"最后长什么样、存到哪里"——以表格 / 列表展示，或写入文件。

```powershell
... | Format-Table -AutoSize -Wrap          # 表格，自动列宽 + 长文本换行
... | Format-List *                         # 全部属性列表
... | Out-File -FilePath "$root\report.txt" -Encoding utf8 -Append -Width 200
... | Tee-Object -FilePath "$root\report.txt" -Append   # 既显示又落盘
... | Out-Null                              # 丢弃输出（比 > $null 更明确）
```

- `Format-*` 参数：`-AutoSize`（算列宽，慢）、`-Wrap`（不换行截断）、`-GroupBy`（分组标题）、`-HideTableHeaders`。
- `Out-File`：`-Append` 追加、`-Width` 控制折行宽度（默认截断很宽的输出）、`-NoClobber`（不覆盖已有文件）。
- ⚠️ **`Format-*` 只能放管道最后**；`Out-File` 会改变对象为文本，也不能再接 `Select-Object`。

---

### 第 4 章：重定向与编码参数

本节涉及的 `>`、`>>`、`2>`、`*>` 不是"命令"，而是**重定向操作符**——控制命令的输出（正常结果、报错等）流向哪个文件；`-Encoding` 则控制文件以哪种字符编码读写。下面逐条说明各自作用。

```powershell
python "$root\projects\digit_cls\train.py" > out.txt            # 成功流(1)覆盖
python "$root\projects\digit_cls\train.py" >> out.txt           # 追加
python "$root\projects\digit_cls\train.py" 2> err.txt           # 仅错误流(2)
python "$root\projects\digit_cls\train.py" *> all.log           # 全部 6 条流合并
python "$root\projects\digit_cls\train.py" 2>&1 >> all.log      # 错误合并到成功流再追加
```

- PowerShell 有 6 条流：1=成功、2=错误、3=警告、4=详细、5=调试、6=信息；`*>` 一把抓，训练脚本最爱用。
- `| Out-Null` vs `$null = ...`：前者走管道（慢但明确），后者直接丢弃（大批量循环里更快）。

编码参数（PS 5.1 可用值：`utf8`(带BOM)、`Unicode`(UTF-16 LE)、`BigEndianUnicode`、`UTF7`、`UTF32`、`ASCII`、`Default`(系统区域，中文=GBK)、`OEM`）：

```powershell
Get-Content "$root\notes.txt" -Encoding default     # 旧 GBK 文件读对
... | Out-File "$root\out.txt" -Encoding utf8       # 写出 UTF-8+BOM，Python 3 通常能认
```

- ⚠️ PS 5.1 的 `-Encoding utf8` **写 BOM**；若下游工具拒认 BOM，可在脚本里用 `[System.IO.File]::WriteAllText()` 或升级到 PS 7 使用 `-Encoding utf8NoBOM`。
- 原则：**读的时候猜不如显式指定，写的时候永远显式指定**。

---

### 第 5 章：环境与系统参数

本节是几条**系统级命令与方法**：读写环境变量（让 Python/pip 在任何窗口都能调用）、以管理员身份启动新窗口、停止进程、查看显卡——用来配置环境和排查程序。逐条说明如下。

```powershell
[Environment]::SetEnvironmentVariable("PATH", $newPath, "User")     # Target: User / Machine / Process
[Environment]::GetEnvironmentVariable("PATH", "User")
Start-Process powershell -Verb RunAs -ArgumentList "-NoExit","-Command","cd 'D:\桌面\AILab'"
Stop-Process -Name python -Confirm -PassThru
nvidia-smi --query-gpu=name,memory.used --format=csv
```

- `[Environment]` 第三个参数：`User`（当前用户，无需管理员）、`Machine`（系统级，需管理员，且会被 User 级同名变量覆盖）、`Process`（仅当前进程，立刻生效但不持久）。
- `Start-Process`：`-Verb RunAs`（提权）、`-Wait`（等它结束）、`-NoNewWindow`、`-RedirectStandardOutput`（把外部程序输出接管进来）。
- `Stop-Process`：`-Confirm`（确认）、`-PassThru`（返回被停掉的进程对象）、`-Id`（比 `-Name` 精确，杀训练进程推荐用 Id）。

---

### 第 6 章：脚本化参数

#### param() 参数特性

**这个东西是干什么的：** 在脚本或函数的开头声明"接受哪些参数"，让脚本能传参、带默认值、还能强制某些参数必填。

```powershell
param(
    [Parameter(Mandatory=$true, Position=0)][string]$LogDir,
    [string[]]$Ext = @(".log"),
    [switch]$Recurse,
    [int]$Top = 10
)
```

- `Mandatory=$true`：不传就报错并提示（比脚本内手写 `if(!$x)` 更规范）。
- `Position=n`：允许省略参数名按位置传。
- `[switch]`：开关参数，传了即 `$true`（调用时写 `-Recurse`，不要写 `-Recurse $true`）。
- 默认值：给合理默认值，脚本才可复用。
- ⚠️ `param()` 必须是脚本/函数的**第一条语句**（注释和空行除外）。

#### 执行策略

**这个东西是干什么的：** 控制 PowerShell 允不允许运行 `.ps1` 脚本文件，是一道防止你误跑恶意 / 未经审核脚本的安全闸门。

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
```

- `-ExecutionPolicy` 可选值：`Restricted`（默认，禁止脚本）、`AllSigned`（全部需签名）、`RemoteSigned`（本地可跑，网络下载需签名）、`Unrestricted`、`Bypass`、`Undefined`。
- `-Scope` 优先级（高→低）：`MachinePolicy` > `UserPolicy` > `Process` > `CurrentUser` > `LocalMachine`。**低优先级设了会被高优先级覆盖**，这就是"设了没用"的主因；用 `Get-ExecutionPolicy -List` 逐层排查。
- `-Force`：跳过确认提示。
- 说明：它是**防误触机制，不是安全边界**，管理员本机仍可绕过。

#### 调试相关

**这一组命令是干什么的：** 在脚本运行过程中打印详细信息、设置断点，帮你看清代码执行到哪一步、变量此刻是什么值。

```powershell
Write-Verbose "正在处理 $f" -Verbose        # 配合脚本调用时的 -Verbose 开关
Write-Debug "断点信息" -Debug
Set-PSBreakpoint -Script "$root\scripts\rename_dataset.ps1" -Line 12 -Action { Write-Host "hit" }
Set-PSBreakpoint -Variable count -Mode ReadWrite
```

- `-Verbose`/`-Debug`：既是 `Write-*` 的开关，也是调用脚本时的通用参数（`.\script.ps1 -Verbose` 全脚本 verbose 生效）。
- `-Action`：断点命中时执行脚本块而不中断（打计数/日志用）。
- `-Mode Read/Write/ReadWrite`：变量断点按访问方式触发。

---

### 第 7 章：AI 实战参数

本节汇总 **AI 学生最常碰的 Python / pip / 虚拟环境命令与参数**：创建虚拟环境、切换国内镜像源、给训练脚本传参并生成带时间戳的日志。下面解释每个参数是干什么的。

```powershell
python -m venv .venv --system-site-packages          # 复用全局包（省空间，但可能污染）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn --no-cache-dir
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

- `--system-site-packages`：镜像站缺包时可 fallback 到全局环境。
- `--trusted-host`：企业内网/自签证书镜像站需要。
- `--no-cache-dir`：磁盘紧张或缓存损坏导致安装诡异报错时使用。
- `pip config set global.xxx`：写到 `%APPDATA%\pip\pip.ini`，一劳永逸。

```powershell
# 时间戳日志名
"...\logs\train_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
Get-Date -Format 'o'          # ISO 8601，排序友好
```

---

### 参数速查表（打印贴显示器旁）

|我要…|关键参数|
|---|---|
|只看文件/只看目录|`-File` / `-Directory`|
|递归但别太深|`-Recurse -Depth 2`|
|过滤（快）|`-Filter "*.jpg"`|
|过滤（多个模式）|`-Include "*.jpg","*.png"`（须配 `-Recurse` 或路径带 `\*`）|
|含隐藏/只读|`-Force`|
|路径含 `[ ]`|`-LiteralPath`|
|删之前看会删啥|`-WhatIf` → `-Confirm` → 裸跑|
|只读日志尾部|`Get-Content -Tail 30`；实时追 `-Wait`|
|多行正则|`Get-Content -Raw`|
|中文不乱码|读写都加 `-Encoding utf8`（GBK 旧文件读用 `default`）|
|筛/选/排/分/统|`Where` / `Select`(+计算属性) / `Sort` / `Group`(-NoElement) / `Measure`(.Sum)|
|grep 带上下文|`Select-String -Pattern -Context 2,3`|
|输出又看又存|`Tee-Object -FilePath x -Append`|
|丢输出|`|
|脚本必填参数|`param([Parameter(Mandatory)]...)`|
|允许跑脚本|`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`|
|静默失败继续|`-ErrorAction SilentlyContinue`；反之 `-ErrorAction Stop`|

---

### 进阶教学与最复杂例子逐处拆解

#### 8.0 先补概念：`-WhatIf`/`-Confirm` 到底拦住了什么

`-WhatIf` 和 `-Confirm` 是 PowerShell **通用参数（所有支持"ShouldProcess"的破坏性 cmdlet 自动带）**。它们的机制是：cmdlet 在真正执行前会先问一句"我打算删 X，同意吗？"——

- `-WhatIf`：**永远回答"不同意"**，只把"我打算做什么"打印出来给你看，绝不动手。等于免费彩排。
- `-Confirm`：每次都**现场问你**，逐条 Yes/No。
- 默认行为（都不加）：cmdlet 不问就自己执行。

所以"先 `-WhatIf` 看清范围、再 `-Confirm` 逐条确认、最后才裸跑"三步走，本质是**把'不可逆操作'拆成三次可回头的检查**。

#### 8.1 最复杂例子逐处拆解：安全三步走 + 全局护栏

```powershell
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force -WhatIf     # 第一拍：只看会删什么
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force -Confirm    # 第二拍：逐条确认
Remove-Item "D:\桌面\AILab\temp\*" -Recurse -Force             # 第三拍：真删

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
```

- `-Recurse`：连子目录一起删（不加时非空目录会报"目录不为空"）；`-Force`：连隐藏/只读项也删（不加时隐藏文件会被静默留下，造成"删了又好像没删干净"）。
- 三行**只差结尾那个参数**，路径和动作完全一致——正因为动作一致，第一拍 `-WhatIf` 打出来的清单才精确等于第三拍真删的内容，彩排才有意义。
- `Set-StrictMode -Version Latest`：开启严格模式，引用**未定义变量**时立刻报错，而不是默默当 `$null` 继续——防止你变量名打错（`$dst` 写成 `$ds t`）导致对错误路径执行删除。
- `$ErrorActionPreference = "Stop"`：把"非终止错误"提升为"终止错误"。默认情况下很多错误只是红字提示、脚本继续往下跑，可能拿着半成品继续删；设成 `Stop` 后一遇错就中断（常配合 `try/catch`），避免错误像雪球一样滚下去。

（第8章其余为速查表与自测题，无需再补教学；至此从第3章起的"先教学、再逐处拆解最复杂例子"的扩充全部完成。）



### 动手练习

- **必做**：用一条管道统计 `D:\桌面\AILab\data\cats_dogs\raw` 中 cat/dog 各自的文件数与总 MB，要求输出为表格，且只用 `-File` 与 `-Filter` 完成过滤（不许事后用 `Where` 再筛一遍）。
- **必做**：把 `projects\digit_cls\logs` 下所有含 `ERROR` 的行连同前后各 2 行上下文导出为 UTF-8 文件，并额外生成一份"哪些文件有错"的去重文件名清单。
- **选做**：重写建库脚本中的 `Copy-Item` 部分，加上 `-WhatIf`、`-PassThru` 与 `-ErrorAction SilentlyContinue`，并把实际复制成功的文件数统计出来。

### 常见报错与排查

- **`-Include` 没效果** → 99% 是没配 `-Recurse` 或路径没写成 `...\*\*.jpg`；改成 `-Filter` 最快解决。
- **`Measure-Object` 的 Sum 是空的** → 输入为空集合；或属性是字符串（用 `[int]$_.Length` 强转）。
- **`Select-Object` 之后 `.Length` 没了** → 中间插过 `Format-*` 或 `-Name`，把它们挪到最后或去掉。
- **删不掉隐藏文件** → 补 `-Force`。
- **设置执行策略无效** → `Get-ExecutionPolicy -List` 看哪一层被组策略（`MachinePolicy`/`UserPolicy`）锁死，锁死则改用 `-Scope Process` 临时绕过。

### 本章小结

1. 参数分**开关/具名/位置**三类，通用参数（`-WhatIf`/`-Confirm`/`-ErrorAction`/`-Verbose`）所有 cmdlet 都有，是安全试错的统一入口。
2. `-Filter`（文件系统级、单模式、快）≠ `-Include`（PS 级、多模式、须配 `-Recurse`），这是 `Get-ChildItem` 第一大坑。
3. 凡是"会丢数据"的命令，固定套路是 `-WhatIf` → `-Confirm` → 裸跑；凡是"跨语言交接"的文件，固定动作是显式 `-Encoding`。

### 自测问题

1. 为什么 `Get-ChildItem -Path $root -Include "*.log"` 常常返回空，而加 `-Recurse` 就好了？请从"谁在做过滤"的角度解释，并给出两种等效的正确写法。
2. `Get-ChildItem $root -Recurse -File | Select-Object -First 3 -ExpandProperty FullName` 与去掉 `-ExpandProperty` 的输出，在**类型**和**后续能否继续取属性**上有何区别？用 `Get-Member` 的思路说明。
3. 你在脚本里写了 `Set-ExecutionPolicy RemoteSigned -Scope LocalMachine`，运行不报错但新开终端仍禁止脚本；反过来设 `-Scope Process` 却立刻生效。请解释原因，并给出"只对当前用户永久生效且不被覆盖"的正确写法。

---

参数都看明白了，要不要我帮你把前7章压缩成一份4周学习计划？按周划分每日练习，方便你循序渐进地过一遍。