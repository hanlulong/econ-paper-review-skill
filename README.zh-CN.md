<!-- Sync note: this page mirrors the top sections of README.md; English is authoritative. Update both in the same commit. -->
# Econ Paper Review Skill（经济学论文 AI 审稿技能）

**在真正的审稿人看到之前，先给你的经济学论文一份严格而公允的审稿报告。**

[![en](https://img.shields.io/badge/lang-English-red.svg)](./README.md)
[![cn](https://img.shields.io/badge/语言-中文-yellow.svg)](./README.zh-CN.md)

> 本页为中文简介，介绍核心功能与安装方法；英文版 [README](./README.md) 为权威版本，完整文档与最新更新以英文版为准。

*源代码公开，学术、个人及其他非商业研究用途免费 — 详见[许可证](./README.md#license)。*

`econ-review` 是一个面向 Claude Code 和 Codex 的 Agent Skill（智能体技能）。它像一位严谨的期刊审稿人那样阅读你的论文：先厘清你的核心主张以及证据如何支撑这些主张，再逐项核查一切可以验证的内容——识别策略、表格、证明、数值、参考文献、行文——然后给出一份审稿报告，外加一份逐步修改计划，告诉你如何解决发现的问题。它从不代你改写论文；那一部分始终由你完成。

*为经济学而生，也同样适用于金融、会计、政治经济学，以及其他依赖数据、因果推断或形式化模型的社会科学论文。*

> **初次接触 Claude Code 或 Codex？** 它们是在你自己电脑上运行的 AI 智能体，可配合你现有的 Claude 或 ChatGPT 订阅使用，几分钟即可完成安装（[Claude Code](https://docs.anthropic.com/en/docs/claude-code) · [Codex](https://openai.com/index/codex/)）。装好任意一个之后，econ-review 只需粘贴一段话即可安装。

## 你会得到什么

评审完成后，成果会整齐地存放在论文旁边的 `review/` 文件夹中：

- **`paper-review.pdf`** — 主报告：专业排版、带书签的 PDF，包含审稿报告、全部详细意见、编辑性意见和修改计划。
- **`reports/`** — 上述报告的 Markdown 版本。其中的修改计划是一份按优先级排序的待办清单，可直接交给你的 AI 智能体去执行。
- **`README.md`** — 一页纸摘要，告诉你应该先读什么。
- **`supporting/`** — 供 Review Desk 与后续评审轮次使用的工作文件；多数作者从不需要打开。

每条意见都会引用稿件中的相关原文——如果问题出自交叉核对或计算，则直接说明依据——然后解释它为何重要、应当如何处理。**[查看完整示例评审（PDF）](./docs/sample-review/paper-review.pdf)**：对一篇故意植入错误的[演示稿件](./docs/sample-review/demo-paper.pdf)、以默认设置冷启动生成的 25 条意见完整审稿报告。

## 安装

支持 macOS、Windows 和 Linux。推荐以独立技能（standalone skill）方式安装，可在 Claude Code 中保留简短的 `/econ-review` 命令、在 Codex 中保留 `$econ-review` 调用方式。将以下内容原样粘贴到任一客户端即可（安装指令为英文，请勿翻译）：

```text
Install or update Econ Review as a standalone skill for this client. Read and
follow the complete instructions at
https://github.com/hanlulong/econ-paper-review-skill/blob/main/INSTALL.md.
Handle installation, same-client migration, and verification yourself; keep
exactly one active copy for this client, do not change the other client, and do
not ask me to run commands. Report completion or the one genuine blocker.
```

以后需要更新时，粘贴同一段话即可；安装流程是幂等的，并会复用兼容的运行环境。需要本机已有 Python 3.10+（`venv` 与 pip 可用）。完整解析 PDF 稿件还需要 `PATH` 中有 [Poppler](https://poppler.freedesktop.org/)；不需要 TeX、Pandoc、Node.js 或管理员权限。安装细节、迁移与升级请见英文版 [INSTALL.md](./INSTALL.md)。

## 与 Refine.ink 及其他 AI 审稿服务的比较

[Refine](https://www.refine.ink/) 让经济学界认识到"AI 投稿前评审"值得认真对待，这一点值得肯定。两种工具做的是同一件事，但取舍不同，有些作者会两者都用——详细对照表见[英文版 README](./README.md#how-it-compares-to-refineink-and-other-ai-review-services)：econ-review 免费开源、在你自己的智能体内运行（论文不上传给任何人）、为多轮修改而设计；Refine 免安装、按次付费、闭源托管。

## 更多内容

Review Desk 交互式评审面板、工作原理、配置选项、路线图与常见问题，见英文版 [README](./README.md)。
