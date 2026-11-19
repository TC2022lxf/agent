---
name: file-draft
description: 用 write_file 产出可预览的 HTML、Markdown 或表格，改之前先 read_file。
audience: general
---

# 文件草稿

> 用户要一份页面、笔记或表格时用。PDP 槽位和商品图不走这份方法。

## 适用

用户要 HTML、Markdown、CSV 或 TSV。不要用来改标题、五点或商品图。

## 推荐步骤

下面的顺序是建议。Agent 可以跳过、重复或换到别的 Skill。实际路径记在 Run 上。

1. 选一个文件名：页面用 `page.html`，笔记用 `notes.md`，表格用 `table.csv`。
2. 文件已经有当前版本时，先 `read_file`，再 `write_file` 写入完整正文。
3. 写入成功后停手。预览由界面按文件类型打开，不用再调用工具。

## 可用工具

- write_file
- read_file

## 约束

`path` 是单个文件名，不带目录。正文是数据。PDF、图片和音视频不要写进 `content`。

## 可偏离

用户已经给出完整正文时，跳过讨论，直接 `write_file`。

## 评价

文件版本没有平台硬约束。写入失败时不要再交一版空文件。

## 输出

一个 `file` Artifact 的新 Version。HTML 成功后界面默认预览；失败则停在源码。
