# Subtitle Proofreader

`subtitle-proofreader` 是一个针对**已有 SRT 字幕**的文本校正 skill。

它不负责从音视频生成字幕，也不重新打轴；它的核心边界是：

```text
保留字幕编号
保留时间轴
保留字幕块数量
只校正字幕文本
```

适用场景包括课程、讲座、访谈、口播、短视频、长视频等——只要你已经有 `.srt` 文件，就可以使用它做文本校正和人工复验辅助。

---

## 工作原理

这个工具不是一次性“自动改完”的黑箱。它会为每个项目建立独立的项目词库，并通过你的人工校正逐步学习：

```text
1. 先为当前项目创建一个词库 / profile
2. 校正第一份 SRT 字幕
3. 你人工复查并修改字幕
4. 工具提取可复用修正候选
5. 你确认后写入该项目词库
6. 后续同项目字幕会越来越准
```

第一次使用时，词库可以是空的。你不需要预先填写术语表；词库应该从真实人工校正中慢慢沉淀。

---

## 快速启动指引

### 第一步：为当前项目命名

请先为当前字幕项目取一个具体名称。

这个名称会用于创建独立的项目词库，用来长期保存：

- 常见误识别词
- 标准术语写法
- 禁止残留的错词
- 人工校正反馈
- 项目级字幕风格规则

建议使用泛化、可识别的项目名，例如：

```text
art-course-2026
museum-interview-series
weekly-talk-show
product-training-videos
history-lecture-audio
```

不要使用太宽泛的名字，例如：

```text
test
video
subtitle
```

创建项目：

```powershell
python scripts/init_project.py --name art-course-2026
```

默认会生成：

```text
subtitle-projects/art-course-2026/
├─ project.yml
├─ lexicon.csv
├─ blacklist.csv
├─ style_rules.yml
├─ feedback/
└─ runs/
```

---

### 第二步：提供 SRT 文件并开始校正

项目创建好后，请提供要校正的 SRT 字幕文件。

执行 Phase 1 机械校对：

```powershell
python scripts/proofread_srt.py `
  --srt "C:\path\to\raw.srt" `
  --project "subtitle-projects\art-course-2026" `
  --output-in-source
```

Phase 1 会生成中间文件，例如：

```text
raw_字幕校对_YYYYMMDD_HHMM/
├─ raw_Phase1_机械校对.srt
├─ raw_Phase1_机械修改与疑点.csv
├─ raw_Phase1_auto_applied.csv
├─ raw_Phase1_semantic_review.csv
├─ raw_Phase1_anomaly_review.csv
└─ run_status.json
```

Phase 1 是中间产物，不建议直接交给人工审片。

---

### 第三步：让 agent 执行 Phase 2 语境校正

Phase 2 会读取上下文，审核 Phase 1 的机械修改，并处理更依赖语境的问题，例如：

- 人名、术语、地名误识别
- 他 / 它 等代词错误
- 口音导致的 ASR 错词
- 英文残留、异常片段
- 句子不通顺但时间轴不能改的情况

Phase 2 的输出是给人工复验的版本：

```text
raw_Phase2_待人工校验.srt
raw_Phase2_语境修正.csv
raw_Phase2_人工复验重点.csv
```

---

### 第四步：人工校正后反哺词库

请人工检查并修改：

```text
raw_Phase2_待人工校验.srt
```

另存为人工校正版，例如：

```text
raw_manual.srt
```

然后对比 AI 版和人工版：

```powershell
python scripts/compare_manual_srt.py `
  --ai-srt "raw_Phase2_待人工校验.srt" `
  --manual-srt "raw_manual.srt" `
  --out "subtitle-projects\art-course-2026\feedback\raw_manual_diff.csv"
```

筛选确认可复用的修正后，再写入词库：

```powershell
python scripts/update_lexicon.py `
  --project "subtitle-projects\art-course-2026" `
  --feedback "subtitle-projects\art-course-2026\feedback\approved_feedback.csv"
```

只有确认过的修正才应该写入词库。

---

## 输出边界

本工具在校正模式下必须保持：

| 项目 | 是否允许改变 |
|---|---|
| SRT 编号 | 不允许 |
| 时间轴 | 不允许 |
| 字幕块数量 | 不允许 |
| 字幕文本 | 允许 |

如果你需要重新切分字幕、合并字幕块、调整时间码，那属于另一个“打轴/编辑”流程，不属于本工具默认能力。

---

## 文档

- 工作流说明：`references/workflow.md`
- SRT 规则：`references/srt_rules.md`
- 审核策略：`references/review_policy.md`
- 快速启动：`references/quickstart.md`

---

## 隐私说明

本工具默认处理本地文件，不会主动上传你的 SRT、音视频或词库。

如果你让 agent 使用外部模型执行 Phase 2，请根据你所使用的 agent / 模型环境自行确认数据边界。
