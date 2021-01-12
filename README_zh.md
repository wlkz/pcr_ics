# pcr_ics

![banner](docs/banner.png)

一个根据[干炸里脊资源站](https://redive.estertion.win)数据制作的公主连结 Re:dive 活动 iCalendar 日程表。

## 使用方法

### 订阅发布地址

[webcal://wlkz.github.io/pcr_ics/dist/pcr_cn.ics](webcal://wlkz.github.io/pcr_ics/dist/pcr_cn.ics)

在大多数情况下，使用该地址即可。

有时根据日历客户端的不同，可能会因为国际互联网连接不通畅而导致无法更新（常见于iOS系统订阅），这时请使用备用国内镜像地址(试验性)。

[webcal://gitee.com/wlkz/pcr_ics/raw/deploy/dist/pcr_cn.ics](webcal://gitee.com/wlkz/pcr_ics/raw/deploy/dist/pcr_cn.ics)

> 请注意：由于代码重构等原因，原[webcal://gitee.com/wlkz/pcr_ics/raw/master/dist/pcr_cn.ics](webcal://gitee.com/wlkz/pcr_ics/raw/master/dist/pcr_cn.ics)不再使用。

### 日历订阅

由于当前常用日历客户端很多，在此不能一一覆盖。如果没有提到你所用的客户端，你可以以`你的客户端名 ics 在线日历导入`为关键字去查找相关方法。

此外，不推荐直接使用 ics 文件导入。这样会在后续更新的时候，需要手动再次导入。

另外，限于各大客户端同步实现细节不同，日历的更新以及同步可能需要大于 1 天的时间。

#### iOS 用户
  
直接点击订阅地址即可（推荐使用国内镜像地址）。

#### Outlook 用户

> 在实际使用中Outlook似乎不能更新，其机制有待观察。

![outlook](docs/outlook.png)

登录 Outlook 网页版，找到日历选项，点击添加日历，如上图输入相关信息即可。

设置完毕后，在各大支持 Exchange 服务的客户端登录，应该就能各端同步了。

## 更新历史

### Version 1.0.0

Release at 2020/01/12

- 使用Github Actions对日历订阅更新进行持续集成。每6个小时会自动检查一次数据库更新
- 以官方描述为准彻底修订了一次日历描述
- 新增对兰德索尔杯的支持
- 修复：ics文件中`CREATED`、`DTSTAMP`实现与预期不符的问题
- ics文件的各个事件的输出顺序改为以事件开始时间排序输出
- 更新ics文件头，存储数据库版本
- 提供了命令行接口以及日志信息
- 重写了日历生成代码

## 开发者指南

[见此](docs/developer.md)，包含了命令行方法，以及一些技术细节。

## 感谢

- [干炸里脊资源站](https://redive.estertion.win)
- [@yuudi](https://github.com/yuudi) 的 [
pcr-calender](https://github.com/yuudi/pcr-calender)，这个项目基本就是参考了这个项目的相关代码，再过度封装而成。另外如果同步日历麻烦，可以用他的[网页版日历](https://tools.yobot.win/calender/#cn)。

非常感谢以上大佬，如果没有他们就没有这个项目。

## 许可证

MIT License
