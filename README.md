# 每日 AI Builders 简讯

一个面向个人认知积累的 AI builders 信息追踪系统。默认调用 [zarazhangrui/follow-builders](https://github.com/zarazhangrui/follow-builders) skill，消费它集中维护的 X builders、播客访谈和博客 feed，合并手动日报，生成可溯源的结构化 JSON 和 GitHub Pages HTML 页面，并通过飞书机器人推送当天链接和核心摘要。

## MVP 范围

- 默认来源：Follow Builders skill。
- 内容类型：AI builder 的 X 动态、YouTube / podcast 访谈、博客/长文 feed。
- 调用方式：优先下载并运行 `follow-builders` 的 `scripts/prepare-digest.js`；如果 Node 或脚本执行失败，回退到同一仓库的公开 feed。
- 支持 `data/manual_input/YYYY-MM-DD.md` 或 `.txt` 手动日报。
- 支持去重、可信度标记、可溯源标记、待核实标记、多源确认。
- 生成 `docs/daily/YYYY-MM-DD.html` 和近 7 天首页 `docs/index.html`。
- GitHub Actions 每天北京时间 09:00 自动运行。
- 飞书机器人推送摘要和 GitHub Pages 链接。

## 目录结构

```text
config/
  sources.yaml
  settings.yaml
  feishu.yaml.example
data/
  raw/
  processed/
  manual_input/
docs/
  index.html
  daily/
scripts/
  fetch_sources.py
  parse_manual_input.py
  verify_and_dedupe.py
  generate_brief.py
  render_html.py
  send_feishu.py
  run_daily.py
templates/
  daily_template.html
  index_template.html
.github/workflows/
  daily.yml
```

## 本地运行

```bash
python3 -m pip install -r requirements.txt
python3 scripts/run_daily.py --no-feishu
```

指定日期：

```bash
python3 scripts/run_daily.py --date 2026-06-01 --no-feishu
```

只处理手动日报，不联网抓取：

```bash
python3 scripts/run_daily.py --date 2026-06-01 --offline --no-feishu
```

## 手动日报输入

把当天日报放到：

```text
data/manual_input/YYYY-MM-DD.md
data/manual_input/YYYY-MM-DD.txt
```

脚本会自动拆分条目、提取链接、推断公司、标记可信度，并和 Follow Builders 自动内容做去重。没有可靠来源的内容会标记为 `unverified` 和待核实。

## GitHub Pages

推荐在 GitHub 仓库设置中启用 Pages：

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/docs`

页面链接通常是：

```text
https://<github-username>.github.io/ai-daily-brief/daily/YYYY-MM-DD.html
```

如果你使用自定义域名或不同仓库名，可以在 GitHub Actions Variables 中设置：

```text
SITE_BASE_URL=https://<your-domain-or-pages-root>
```

## GitHub Secrets

飞书推送至少需要：

```text
FEISHU_WEBHOOK_URL
```

如果飞书自定义机器人开启了签名校验，再添加：

```text
FEISHU_SECRET
```

OpenAI API 增强目前预留为可选能力。注意：ChatGPT Plus / Pro 订阅不会自动变成 GitHub Actions 可用的 API key。如果后续要让 Actions 调用 OpenAI API，需要在 OpenAI 平台创建 API key，并添加：

```text
OPENAI_API_KEY
OPENAI_MODEL
```

## 可信度规则

- `official`: 官方 blog、docs、release notes、官方仓库或官方模型页。
- `media`: 媒体报道。
- `community`: X builders、社区、非官方 GitHub 项目、二手来源。Follow Builders 中的 builder 原帖会标记为可溯源，但不等同于公司官方确认。
- `unverified`: 手动日报或转述中无法找到可靠来源的信息。
- `conflicting`: 多个来源说法冲突，需要人工复核。

系统不会补写无法确认的模型参数、价格、发布时间、上下文长度或 benchmark。缺少更新前后对比时，页面会标记为“信息不足”。

## 信息源配置

默认 `config/sources.yaml` 只启用 `follow_builders`。如需恢复公司官方 RSS / changelog 抓取，可以继续新增旧版支持的 `rss`、`html`、`github_releases`、`huggingface_models` 或 `github_search` 来源类型。

## 自动化

`.github/workflows/daily.yml` 默认每天 UTC 01:00 运行，也就是北京时间 09:00。你也可以在 GitHub Actions 页面手动触发，并指定日期。
