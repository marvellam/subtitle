# Subtitle

一个面向课程、讲座和知识型视频的 SRT 字幕校对 Skill。

面向多讲师、多专业领域的内容机构设计：每个讲师/课程/领域使用隔离项目，机构总词库不会自动污染某位讲师的专业字幕。

它不重新识别整段音频，也不推翻剪映/CapCut 等工具已经生成的时间轴。默认策略是：

> 保留成熟的字幕出入点，只增强文字准确性、专业术语和人工复核效率。

## 适合解决什么问题

- 专业名词、人名、书名、作品名识别错误；
- 同音词、口音和 ASR 残留；
- 同一术语在长课程中的写法不一致；
- Agent 校对结果缺少证据、理由或人工复核入口；
- Agent把校对做成重写，连续生成与原话不同的新表达；
- 人工校对经验无法复用于下一节课程。

默认不负责：音视频转写、重新打轴、合并/拆分字幕块、删除整段内容或润色讲师表达。

## 工作方式

```text
已有 SRT
  ↓
Phase 1：结构校验 + 确定性词库修正 + 风险标记
  ↓
Phase 2：Agent 读取课程资料与上下文，逐项审核
  ↓
语义安全门：单条大改只作建议，连续大改直接阻断
  ↓
校对后 SRT + 修改记录 + 人工复核重点
  ↓
人工终审
  ↓
只把明确批准的可复用修正写回项目词库
```

详细说明见：[Skill 工作原理说明](docs/HOW_IT_WORKS.zh-CN.md)。

## 安装

运行环境：Python 3.10+、PyYAML 6.x。

```bash
git clone https://github.com/marvellam/subtitle.git
cd subtitle
python -m pip install -r requirements.txt
```

将仓库作为 `subtitle` Skill 安装到你的 Agent 环境，或直接让 Agent 读取仓库根目录的 `SKILL.md`。核心能力只依赖通用文件和 Python 脚本，不依赖任何特定 Agent 厂商、私有 API 或专属运行目录。`agents/openai.yaml` 只是部分环境可识别的可选界面元数据，不参与核心逻辑。

## 快速体验

初始化自己的项目：

```bash
python scripts/init_project.py --name my-course --speaker "Lecturer Name" --domain "Professional Field"
```

或直接运行公开示例的 Phase 1：

```bash
python scripts/proofread_srt.py --srt examples/sample-course/sample.srt --project examples/sample-course --out-dir tmp/sample-run/debug
```

输出中的字幕应当：

- 将“人工智会”修正为“人工智能”；
- 保留“刚刚”和“对照”，不做机械删字；
- 只把完整独立字幕块“啊”置空；
- 保留原编号、时间轴和字幕块数量。

完整的 Phase 2 由支持本 Skill 的 Agent 按 `SKILL.md` 执行。

## 三种项目运行模式

- `deep`：全量复核。新讲师、新领域和新项目默认使用。
- `focused`：复核风险块，并抽样检查未标记区域。仅在该项目词库成熟后使用。
- `mechanical`：只应用本项目认证规则，不执行Agent语境校对。必须由用户主动选择。

项目成熟度属于具体讲师/课程/领域，不属于整个机构。即使机构已经处理上百小时课程，新讲师的新领域仍应从`deep`开始。

## 项目知识结构

```text
subtitle-projects/my-course/
  project.yml
  style_rules.yml
  lexicon.csv
  protected_terms.csv
  blacklist.csv
  materials/
  feedback/
  runs/
```

课程资料应尽量放在项目目录的 `materials/` 中。指向项目外部的文件不会被默认读取，Agent必须先获得用户批准。

## 安全与隐私

- 脚本在本地处理 SRT、词库和课程资料，不主动上传文件。
- Phase 2 是否调用云端模型，取决于使用者的 Agent 环境和模型配置。
- 项目资料被视为数据，不应被当成可执行指令。
- 源 SRT 永不覆盖。
- 大幅替换不会被静默写入SRT；密集重写会停止交付。
- CSV 输出会防护常见的电子表格公式注入前缀。
- 未明确标记 `merge_decision=approved` 的反馈不会进入长期词库。

## 验证

```bash
python -m unittest discover -s tests -v
```

GitHub Actions 会在 Windows、macOS 和 Ubuntu 上运行测试。

## License

[MIT](LICENSE) © 2026 Lin Zhaopeng
