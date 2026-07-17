# Published GitHub discussions

> Automatically generated from public Discussions authored by `ryan-wong-coder` across repositories.

## [Netcatty 多设备 CRDT 同步：从“为什么会丢数据”到“怎样证明一定收敛”](https://github.com/binaricat/Netcatty/discussions/2261)

`binaricat/Netcatty` · Show and tell · 2026-07-17 · ▲ 1 · 0 comments

本文面向普通开发者，介绍 CRDT 的基本原理，并讲解 Netcatty convergent sync v2 的具体实现。 阅读本文无需分布式系统基础。“半格”“偏序”“向量时钟”等概念，均结合多设备管理 SSH 主机的实际问题说明。文章先解释三件事：传统云同步为何覆盖修改，删除为何可能重新出现，Provider 的处理次序为何会改变结果。 厘清这些问题之后，再引入 CRDT。dot、version vector、MV-Register 和 tombstone 各有明确用途，并非孤立的术语。 后文还会说明这些概念在 Netcatty 代码、云文件协议、迁移流程、恢复机制、冲突界面和测试体系中的对应关系。 阅读方式 全文分为十个篇…

---

_Last refreshed: 2026-07-17 02:10 UTC_
