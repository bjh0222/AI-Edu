# 模块 M3：管道与对象（掌握版）

> 状态：**已审查**（L1/L2 已过；L3 执行验证待你完成——不跑完不升级为「已验证」）
> 定位：你在原教程学完了管道但自报「未掌握」、主要卡在缺前置。本模块针对这两点重设计：前置先修、每步带预期结果、概念到用时才引入。
> 前置：原教程第 2 章等价能力（`Set-Location` / `Get-ChildItem` / `New-Item` / `Set-Content` 基本用法）
> 环境前提：`D:\桌面\AILab` 已建成。每次学习开头先执行：
>
> ```powershell
> $root = "D:\桌面\AILab"
> ```
>
> 纪律：单节 ≤40 分钟；卡住 → 用 `templates/question.md` 组装提问（经 AI Hub 复制+打开），30 秒记一行 `learning-log.md`。

## 本模块验收标准（S1–S6）

| ID | 标准（可判定） | 证据形式 |
|---|---|---|
| S1 | 能够不看资料说出 `Get-ChildItem` 的输出是「对象」并列举 ≥3 个属性名；能够对任意命令的输出用 `Get-Member` 查属性 | 口头解释 + 命令输出 |
| S2 | 能够解释 `$_` 的指代；对给定文件列表预测 `Where-Object` 筛选结果 ≥4/5 正确，并跑通验证 | 预测答案 + 运行结果比对 |
| S3 | 能够用一条管道完成「按属性排序 + 取前 N + 指定列」，并逐段解释每一段在做什么 | 命令 + 逐段一句话解释 |
| S4 | 能够用 `Group-Object` / `Measure-Object` 完成分组计数与求和，并解释「统计结果要再 `.Sum` 取数」 | cat/dog 计数输出 = 500/500 |
| S5 | 能够写出一个计算属性列（字节→KB），解释 `@{Name;Expression}` 两个键；会调用 `[math]::Round` | 命令 + 预期数值比对 |
| S6 | 不看本模块内容，在 ≤A2（提示）辅助下完成两个变式任务，并能说出用了哪几条已学经验 | 产物 + 复盘说明 |

> ⚠️ **G1 门槛备注**：按流程应先由你逐条确认这些标准再生成内容。你指示「直接完成」，故由 AI 定稿——**你的第一个学习动作就是复核它们**：不同意哪条就现在改，内容跟着改。

## 第 0 节 诊断（先做这个，10 分钟）

不看任何资料作答，写下方括号里。目的：决定你从哪节开始，并实测你的自报水平。

- **D1（概念）**：`Get-ChildItem` 在屏幕上打印的是一行行文字，但 PowerShell 内部把这些东西当作什么传递？[A 一段文本 / B 一个个带属性的对象 / C 一个个路径字符串]
- **D2（实操）**：运行 `Get-Date | Get-Member -MemberType Property`，从输出里写下 3 个属性名。
- **D3（你自报「可以写出来」的那条，现在实测）**：不看资料，写出「统计 `raw` 下 cat 开头的 jpg 有多少张」的命令并运行。
- **D4（概念）**：`Where-Object { $_.Length -gt 100 }` 里的 `$_` 指什么？
- **D5（实操）**：写出「递归找出 AILab 下所有 .log 文件」的命令并运行。

**路由表**：

| 你的结果 | 从哪开始 |
|---|---|
| D1 或 D2 未对 | 从第 1 节开始，别跳 |
| D1/D2 对，D4 答不出 | 从第 2 节开始 |
| D3/D4/D5 全对（D3 输出 500） | 第 1–3 节只做练习快读，重点第 4–5 节 |

---

## 第 1 节 对象与属性（约 20 分钟，对应 S1）

要解决的问题：管道的一切都建立在一个事实上——命令之间传的**不是文字，是对象**。

### 1.1 看见对象

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" | Select-Object -First 1
```

预期输出（表头 + 一行）：

```text
    目录: D:\桌面\AILab\data\cats_dogs\raw

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a----        （时间）                    0 cat.1.jpg
```

你看到的这行"表格"只是对象的**展示形式**。对象本体带着一整套属性数据。

### 1.2 看见属性（本节核心命令）

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" | Select-Object -First 1 | Get-Member -MemberType Property
```

预期输出（节选）：

```text
   TypeName: System.IO.FileInfo

Name          MemberType Definition
----          ---------- ----------
Attributes    Property   System.IO.FileAttributes Attributes {get;set;}
CreationTime  Property   datetime CreationTime {get;set;}
Extension     Property   string Extension {get;}
FullName      Property   string FullName {get;}
LastWriteTime Property   datetime LastWriteTime {get;set;}
Length        Property   long Length {get;}
Name          Property   string Name {get;}
...
```

两个要点：
- `TypeName: System.IO.FileInfo`——对象的类型；下面的 `Name` 列就是**属性名清单**（`Length`、`Name`、`LastWriteTime`……后面全要用）。
- 类比：一个对象 = 表格的一行；属性 = 列名。屏幕默认只显示其中几列，**列全都在**。

### 1.3 换个对象验证

```powershell
Get-Date | Get-Member -MemberType Property
```

预期：`TypeName` 变成 `System.DateTime`，属性含 `Year / Month / Day / Hour / Minute / Second`……（数十个，看到名单即可）。

### 检查点（口答）

1. `Get-ChildItem` 输出的每个文件是一个 ______；想看它有哪些属性，把它管道给 ______。
2. `FileInfo` 对象表示「文件大小」的属性叫什么？

### 练习（通过线：输出里出现 `WS`）

用 `Get-Member` 找出 `Get-Process` 输出对象中表示物理内存的属性名。
参考路径：`Get-Process | Get-Member -MemberType Property`，找 W 开头那行。

### 常见报错

- `Get-Member` 报「必须指定对象」→ 管道左边没有输出（路径写错/目录为空）。先单独跑左边，确认有结果。

---

## 第 2 节 `$_` 与 Where-Object（约 20 分钟，对应 S2）

### 2.0 准备三个大小不同的文件（第 2、3、5 节都用它们）

```powershell
Set-Content "$root\temp\a.log" -Value ("x" * 300)
Set-Content "$root\temp\b.log" -Value ("x" * 700)
Set-Content "$root\temp\c.log" -Value ("x" * 120)
```

预期：无输出（`Set-Content` 成功时安静）。三个文件实际 302 / 702 / 122 字节（内容 300/700/120 个 x，加 2 个换行字节）。
注意：若你的 `temp` 下还有其他文件（基线库实测有 2 个多余文件），把它们的实际大小一并观察——先跑下面这条**看清现场**再做题：

```powershell
Get-ChildItem "$root\temp" -File | Select-Object Name, Length
```

### 2.1 概念：脚本块与 `$_`

- `Where-Object { ... }` 花括号里是一小段代码，叫**脚本块**。
- `$_` 读作「当前这一个」：管道里的对象**一个一个**流过 Where，轮到谁，`$_` 就是谁。
- Where 像**门口安检**：条件为真的放行，其余拦下。

### 2.2 第一次筛选

```powershell
Get-ChildItem "$root\temp" -File | Where-Object { $_.Length -gt 200 }
```

预期输出：2 行——`a.log`（302）与 `b.log`（702）；`c.log`（122）被拦下。
（若目录混了进来——那是忘了 `-File`，目录没有 Length。）

### 2.3 常用比较运算符（小抄）

| 运算符 | 含义 | 例 |
|---|---|---|
| `-eq` / `-ne` | 等于 / 不等于 | `$_.Extension -eq ".log"` |
| `-gt` / `-lt` | 大于 / 小于 | `$_.Length -gt 200` |
| `-like` | 通配符匹配 | `$_.Name -like "cat.*"` |
| `-match` | 正则匹配 | `$_.Name -match "\d{3}"` |

### 2.4 预测 → 验证（先写答案再跑）

不运行，先写下下面命令会留下哪些文件：

```powershell
Get-ChildItem "$root\temp" -File | Where-Object { $_.Length -gt 500 }
```

你的预测：______。然后运行。**答案：只有 b.log（702）。预测对不对，就是 S2 的掌握证据。**

### 检查点（口答）

2.2 的命令里，`$_` 先后变成了哪几个对象？（答：a.log、b.log、c.log 三个 FileInfo 对象，逐个流过。）

### 练习（通过线：输出只有 c.log 一行）

写一条命令：列出 temp 下**小于** 200 字节的文件。
（卡住允许看 2.2 改一个运算符；先预测再跑。）

### 常见报错

- `$ _`（中间有空格）→ 解析错误；`$_` 必须连写。
- 条件没错但没输出 → 先单独跑管道左边，确认有东西可筛。

---

## 第 3 节 Sort 与 Select：排序取列（约 25 分钟，对应 S3）

### 3.1 三连（本节主命令）

```powershell
Get-ChildItem "$root\temp" -File |
  Sort-Object Length -Descending |
  Select-Object -First 2 Name, Length
```

预期输出：

```text
Name  Length
----  ------
b.log    702
a.log    302
```

逐段拆解（传送带）：
- `Get-ChildItem ... -File`：把 temp 下 3 个文件对象放上传送带；
- `Sort-Object Length -Descending`：按 `Length` 属性从大到小。注意这里直接写属性名 `Length`，**不写** `$_.Length`——Sort 吃的是属性名，不是表达式；
- `Select-Object -First 2 Name, Length`：只放行前 2 个，且只展示这两列。

### 3.2 三个常用形

```powershell
Select-Object -First 3           # 前 3 个
Select-Object Name, Length       # 只看这两列
Select-Object -First 1 Name      # 组合：只看第一个的名字
```

### 3.3 用时间属性排序

```powershell
Get-ChildItem $root -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name
```

预期：你刚创建的 a.log / b.log / c.log 都应出现在结果里（若三个创建时间在同一秒内，顺序可能并列，属正常）。

### 检查点（口答）

想「从小到大」，去掉哪个参数？（答：`-Descending`。）

### 练习（通过线：输出仅 1 行，是 b.log）

一条管道：temp 下**最大的 1 个**文件的 Name 和 Length。（与 3.1 只差一处。）

### 常见报错

- 结果「反了」→ 忘了 `-Descending`（默认从小到大）。
- `Sort-Object $_.Length` 行为怪 → Sort 后面直接写属性名。

---

## 第 4 节 Group 与 Measure：分组与统计（约 25 分钟，对应 S4）

### 4.1 分组计数（数据集质检的标准动作）

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File |
  Group-Object { $_.Name.Split('.')[0] } |
  Select-Object Name, Count
```

预期输出：

```text
Name Count
---- -----
cat    500
dog    500
```

拆解：
- `$_.Name.Split('.')`：把 `cat.123.jpg` 按 `.` 切成 `('cat','123','jpg')`，`[0]` 取第一个 → `"cat"`；
- `Group-Object { ... }`：花括号返回**分组键**——和 Where 不同，它不是筛选条件，是「按什么归类」；
- 每组是一个对象（`Name` 组键、`Count` 数量），所以最后还要 `Select-Object` 挑出来看。

### 4.2 求和（以及一个诚实的「意外」）

```powershell
Get-ChildItem "$root\data\cats_dogs\raw" -File | Measure-Object Length -Sum
```

预期输出：

```text
Count    Sum
-----    ---
 1000       0
```

`Sum` 是 **0**——不是你命令错了：建库脚本用 `New-Item` 造的 1000 个占位 jpg 全是**空文件**（0 字节）。
> 原教程的招牌示例「找出 raw 下最大的 3 个文件」在同样的空文件上跑，排序结果毫无意义——它从未被实际执行验证过（已追加进 [diagnosis-基线诊断.md](diagnosis-基线诊断.md)）。**预期与实际不符时，先怀疑数据，再怀疑命令。**

### 4.3 取数陷阱（Measure 的结果不是数字）

```powershell
(Get-ChildItem "$root\data\cats_dogs\raw" -File | Measure-Object Length -Sum).Count
```

预期输出：`1000`

`Measure-Object` 输出的是一个**统计对象**（带 `Count / Sum / Average` 属性），要用 `.Count` / `.Sum` 把数字抠出来才能当数用。

### 检查点（口答）

`Group-Object` 的花括号和 `Where-Object` 的花括号，返回的东西有什么区别？（答：Where 返回真假做筛选；Group 返回分组键做归类。）

### 练习（通过线：`.jpg` 一行显示 1000）

一条命令：全库递归，按扩展名分组统计文件数。
参考骨架：`Get-ChildItem $root -Recurse -File | Group-Object ______ | Select-Object Name, Count`
（`Group-Object` 直接写属性名 `Extension` 即可。）预期：`.jpg` 1000；`.log` / `.py` / `.txt` 的数量以你的实际输出为准并记录——基线库实测总文件数 1005，比建库脚本承诺的「>1000」多 2 个来源不明的文件，正好练一下 4.2 的教训：先查数据。

### 常见报错

- 想要数字却拿到一张表 → 你拿到的是统计对象，加 `.Sum` / `.Count`。
- 组太多看不过来 → 管道末尾接 `Sort-Object Count -Descending`（第 3 节技能直接复用）。

---

## 第 5 节 计算属性：现造一列（约 30 分钟，对应 S5）

原教程把本章最难的概念（计算属性）和两个没教过的前置（哈希表、`[math]::Round`）压在同一个例子里——这是你「缺前置」感受的直接来源。这里拆开：先补前置，再上主菜。

### 5.1 前置一：哈希表 = 键值对清单

```powershell
$cat = @{ Name = "小白"; Age = 3 }
$cat.Name
$cat["Age"]
```

预期输出：

```text
小白
3
```

`@{ 键 = 值; ... }` 是哈希表：一种「名字 → 值」的清单，用 `.键名` 或 `["键名"]` 取值。

### 5.2 前置二：`[math]::Round` 四舍五入

```powershell
[math]::Round(0.2949, 2)
```

预期输出：`0.29`

语法 `[类名]::方法名(参数)` = 调用 .NET 类的静态方法（细节在原教程第 5 章，现在会照用即可）。`1KB` / `1MB` 是 PowerShell 内置常量（1024 / 1048576）。

### 5.3 主菜：给文件表现造一列 SizeKB

```powershell
Get-ChildItem "$root\temp" -File |
  Select-Object Name, @{ Name = 'SizeKB'; Expression = { [math]::Round($_.Length / 1KB, 2) } }
```

预期输出：

```text
Name  SizeKB
----  ------
a.log   0.29
b.log   0.69
c.log   0.12
```

拆解（现在全是旧知识）：
- `@{ Name = ...; Expression = ... }` 就是一个**哈希表**（5.1），PowerShell 约定这两个键的含义：`Name` = 新列的表头；`Expression` = 这一列每行怎么算；
- `Expression` 的脚本块里，`$_` 还是「当前这一个」（第 2 节）；`$_.Length / 1KB` 取字节数换算成 KB（第 1 节的属性 + 5.2 的常量）；`[math]::Round(..., 2)` 保留两位（5.2）；
- 对象本身没有 `SizeKB` 这个属性——这一列是**现造的**，所以叫计算属性。

### 检查点（口答）

`@{Name='SizeKB'; Expression={...}}` 两个键各管什么？（答：Name=新列叫什么；Expression=每行怎么算。）

### 练习（通过线：出现 `MemMB` 列且数值为 MB 量级）

给进程表造一列内存（MB）：`Get-Process | Select-Object -First 5 Name, @{ ______ }`，表达式用 `WS / 1MB`（`WS` 是第 1 节练习找到的属性名）。

### 常见报错

- 新列全是空白 → `Name` / `Expression` 拼错时**不报错只出空列**（第 1 节讲过：属性拼错静默失败）。逐字核对键名。
- 数值一堆小数 → 忘了 `[math]::Round(..., 2)`。

---

## 第 6 节 综合变式（约 25 分钟，对应 S6）

**规则：不看第 1–5 节的命令，≤A2（提示）辅助。完成后各写一句「用了哪几节的经验」。**

### 变式 1（组装）

需求：列出 AILab 全库中**大于 300 字节**的文件，显示 `Name` 和按 KB 保留 2 位的大小列 `SizeKB`，按大小降序，取前 3。

预期：结果中至少有 `b.log`（0.69）与 `a.log`（0.29）；若出现其他文件，先查它们的实际大小再下结论。

### 变式 2（诊断）

同事写了这条命令，说想找**全库最大的文件**，但结果不对：

```powershell
Get-ChildItem $root -Recurse -File | Sort-Object Length | Select-Object -First 1
```

指出问题、修复，并用一句话解释为什么结果恰好是「反的」。

### 复盘 4 问（写进 `evidence/`，这就是证据采集）

1. 这次不依赖逐步提示，我能独立完成什么？
2. 哪里仍需要提示？卡在哪？
3. 出了什么错、有什么规律？（同步追加一行到 `profile.md` 错误模式表）
4. 下一步最值得做的一件事是什么？

---

## 中途提问

任何一节卡住超过 5 分钟：`templates/question.md` 组装 → AI Hub 复制+打开 → 30 秒记 `learning-log.md`。**提问不是失败，是流程的一部分**——但要把问题类别记对（解释不清 / 步骤失败 / 缺前置 / 环境差异）。

---

## 审查记录（G4，生产端留痕）

| 项 | 内容 |
|---|---|
| 拦截 1 | 初稿沿用原教程「在 raw 上按大小排序」的示例——建库脚本造的 1000 个占位文件全是 0 字节，该类示例永远无意义。→ 大小类示例全部改为 temp 下已知大小文件。原教程缺陷追加进诊断文件。 |
| 拦截 2 | S5 初稿把计算属性与哈希表、`[math]::Round` 压在同一段（重蹈原教程 L321–329 前置堆叠的覆辙）。→ 拆为 5.1/5.2 先修前置，5.3 再上主菜。 |
| 拦截 3 | D3 与用户自报能力重合 → 保留，作为自报的实测验证点。 |
| 状态 | 草稿 → **已审查**（L1 九项自查全过；L3 待用户执行） |
| G1 备注 | 验收标准定稿由 AI 代行（用户指示「直接完成」）；用户复核标准 = 第一个学习动作。 |
