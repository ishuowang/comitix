<div align="center">

# comitix

**commit + mix — 用 53 周，把一段音乐循环写进 GitHub 贡献图。**

[![Paint music loop](https://github.com/ishuowang/comitix/actions/workflows/paint.yml/badge.svg)](https://github.com/ishuowang/comitix/actions/workflows/paint.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-84cc16.svg)](LICENSE)
[![53 weeks](https://img.shields.io/badge/loop-53_weeks-22c55e.svg)](pattern.json)

</div>

## 这是什么

Comitix 是一个透明、可复现的 generative contribution art 实验。GitHub Actions 每晚读取一张 `7 × 53` 点阵乐谱，在默认分支补齐当天以及漏跑日期的确定性提交。

这次把原来的「均衡器 + 双拍」换成了一盘更有辨识度的像素磁带。完整循环是：

> 唱片 → 星点 → 音符 → 节拍点 → **磁带** → 波形 → 闪点 → 耳机 → 回声点 → 播放 → 循环点

```text
·█████··
█·····█·
█·█·█·█·
█·▒▒▒·█·
█·····█·
█·███·█·
·██·██··
```

## 完整点阵

`·` 是留白，`░ / ▒ / ▓ / █` 是四档设计强度。GitHub 会根据账号当天的总贡献动态计算颜色，所以深浅是近似的，轮廓本身保持确定。

```text
··███······███··░·█████········░·░··▒▒▒▒··▒·█······░·
·██·██·▒···█·█···█·····█·····░██···▒▒··▒▒···██·······
██···██····█·█···█·█·█·█·░···█░···▒▒····▒▒··███······
██·█·██····█·█···█·▒▒▒·█·█········▒······▒··████·····
██···██··███·█···█·····█···░█·····█······█··███······
·██·██···██····▒·█·███·█··██░···▒·██····██··██·······
··███···░·█·······██·██···░········█····█·░·█·······▒
```

### 形成过程

| 周 | 组件 | 宽度 | 累计进度 |
|---:|---|---:|---:|
| 1–7 | 唱片 | 7 周 | 7 / 53 |
| 8–9 | 星点 | 2 周 | 9 / 53 |
| 10–15 | 音符 | 6 周 | 15 / 53 |
| 16–17 | 节拍点 | 2 周 | 17 / 53 |
| 18–25 | 磁带 | 8 周 | 25 / 53 |
| 26–32 | 波形 | 7 周 | 32 / 53 |
| 33–34 | 闪点 | 2 周 | 34 / 53 |
| 35–42 | 耳机 | 8 周 | 42 / 53 |
| 43–44 | 回声点 | 2 周 | 44 / 53 |
| 45–51 | 播放 | 7 周 | 51 / 53 |
| 52–53 | 循环点 | 2 周 | 53 / 53 |

第 53 周结束后回到唱片，完整图案以 371 天为周期继续循环。

## 自动绘制

- 起始日：`2026-08-02`（周日）
- 时区：`Asia/Shanghai`
- 执行时间：每天 `20:17`
- 分支：直接写入默认分支 `main`，确保符合 GitHub 贡献归属规则
- 身份：提交作者为 `ishuowang` 的 GitHub noreply 地址；committer 保留为 `github-actions[bot]`
- 自愈：每次从起始日扫描到今天，自动补齐漏跑日期；已存在的标记不会重复提交
- 权限：仅使用仓库内置 `GITHUB_TOKEN` 和最小 `contents: write`，不需要 PAT、SSH 或 GPG 私钥

每个提交对应一个可审计标记：

```text
.contributions/YYYY/MM/DD/01.json
```

同一天重跑是 no-op；定时任务延迟或漏跑时，后续执行会按原日期补回。

## 本地验证

只依赖 Python 3 标准库和 Git：

```bash
python3 scripts/comitix.py validate
python3 scripts/comitix.py preview
python3 scripts/comitix.py plan --through 2026-08-04
python3 -m unittest discover -s tests -v
```

真正创建提交前可以预演：

```bash
python3 scripts/comitix.py paint --through 2026-08-04 --dry-run
```

点阵、分段、作者身份和强度映射集中在 [`pattern.json`](pattern.json)。如果未来更换图案，请新增带 `effective_date` 的版本边界，不要回写已经生成的日期。

## 说明

Comitix 展示的是自动生成的贡献艺术，不代表人工开发活跃度。真实提交也会叠加到个人贡献图上；GitHub 的定时任务可能延迟，贡献记录也可能需要一段时间才显示。

<div align="center">

Made by [ishuowang](https://github.com/ishuowang) · MIT

</div>
