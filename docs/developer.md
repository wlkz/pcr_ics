# 开发者指南

## 如何自己生成日历文件

准备一个干净的Python环境（3.7+）

安装依赖

```shell
pip install -r requirements.txt
```

生成日历文件

```shell
python pcr_ics.py
```

## 命令行接口

```text
usage: pcr_ics.py [-h] [--ref-calendar-path REF_CALENDAR_PATH] [--target TARGET]

pcr_ics: A iCalendar generator for Princess Connect! Re:Dive (公主连结Re:Dive), based on 干炸里脊 
资源站.

optional arguments:
  -h, --help            show this help message and exit
  --ref-calendar-path REF_CALENDAR_PATH
                        参考的日历文件（参见：实现细节）
  --target TARGET       输出的日历文件
```

## 实现细节

### 参考的日历文件

为了在日历信息时对日历进行更新，参照了规范文件以及Google日历的实现，对`CREATED`、`DTSTAMP`、`SEQUENCE`以及`LAST-MODIFIED`均需要做特殊处理。而这些信息需要依赖上一个生成的日历文件，所以需要输入参考的日历文件。

当前版本默认获取的地址是[webcal://wlkz.github.io/pcr_ics/dist/pcr_cn.ics](webcal://wlkz.github.io/pcr_ics/dist/pcr_cn.ics)，你也可以手动指定，或者传入`none`，让脚本从零开始重新生成日历文件（即所有事件重新生成，各个域重置为初始值）。

```shell
python pcr_ics.py --ref-calendar-path none
```

### ICS解析器

当前使用的是[ics.py](https://github.com/C4ptainCrunch/ics.py)。为了让这个库生成的日历文件符合标准，我们魔改了许多函数。换句话说，这个脚本的深度耦合了ics.py的某个版本，我们无法预期上游的更改是否会对这个脚本工作带来影响。总之，听我的，乖乖建立独立环境，`pip install -r requirements.txt`完事了（
