# Interactive prompt defaults

Use this file only when you are about to draft the actual interactive questions for `/setup-brain`.

## Stage A default `AskUserQuestion` payload

```json
{
  "questions": [
    {
      "header": "身份",
      "question": "你希望我如何总结你的角色、主要职责和当前重点？",
      "multiSelect": false,
      "options": [
        {
          "label": "单一角色 (Recommended)",
          "description": "适合角色比较稳定的情况，用一段简洁摘要概括身份、职责和当前重点。",
          "preview": "我是一名……\n主要负责……\n当前重点是……"
        },
        {
          "label": "多重角色",
          "description": "适合同时承担 2-3 类职责的情况，用一段摘要说明不同角色分工。",
          "preview": "我同时负责……和……\n日常工作包括……\n当前更关注……"
        },
        {
          "label": "转型中",
          "description": "适合当前角色和未来方向并存的情况，突出正在转向的重点。",
          "preview": "目前我主要在做……\n正在转向/加强……\n希望后续重点放在……"
        }
      ]
    },
    {
      "header": "目标",
      "question": "你希望我用什么结构记录你今年或近期最重要的目标？",
      "multiSelect": false,
      "options": [
        {
          "label": "三项目标 (Recommended)",
          "description": "用 3 条最重要目标概括近期重点，最适合快速初始化。",
          "preview": "- ……\n- ……\n- ……"
        },
        {
          "label": "按主题",
          "description": "按工作、学习、生活等主题组织目标。",
          "preview": "- 工作：……\n- 学习：……\n- 生活：……"
        },
        {
          "label": "按里程碑",
          "description": "按时间节点或阶段性结果组织目标。",
          "preview": "- Q3：……\n- Q4：……\n- Next step：……"
        }
      ]
    },
    {
      "header": "项目",
      "question": "你希望我如何整理你当前的活跃项目？",
      "multiSelect": false,
      "options": [
        {
          "label": "简短列表 (Recommended)",
          "description": "每个项目一句话，适合大多数初始化场景。",
          "preview": "- 项目 A：……\n- 项目 B：……\n- 项目 C：……"
        },
        {
          "label": "按优先级",
          "description": "突出当前最重要的项目顺序。",
          "preview": "1. 项目 A：……\n2. 项目 B：……\n3. 项目 C：……"
        },
        {
          "label": "按领域",
          "description": "按工作、个人、长期建设等领域分组。",
          "preview": "- 工作项目：……\n- 个人项目：……\n- 长期建设：……"
        }
      ]
    },
    {
      "header": "偏好",
      "question": "共享身份层里的协作偏好，你希望我怎么处理？",
      "multiSelect": false,
      "options": [
        {
          "label": "保留现有 (Recommended)",
          "description": "直接保留当前协作偏好，不在这一步改写。"
        },
        {
          "label": "轻微调整",
          "description": "保留当前方向，但帮你压缩、润色或收紧措辞。"
        },
        {
          "label": "完全替换",
          "description": "用你接下来提供的新协作偏好替换现有内容。"
        }
      ]
    }
  ]
}
```

## Stage B default `AskUserQuestion` payload

```json
{
  "questions": [
    {
      "header": "格式",
      "question": "初始化后，你希望先启用哪些整理能力？",
      "multiSelect": false,
      "options": [
        {
          "label": "文档+图片 (Recommended)",
          "description": "启用文档/数据/网页/Notebook 转 Markdown，以及截图占位能力。"
        },
        {
          "label": "仅文档",
          "description": "只启用文档/数据/网页/Notebook 转 Markdown。"
        },
        {
          "label": "仅图片",
          "description": "只启用截图占位能力。"
        },
        {
          "label": "暂不启用",
          "description": "先只完成身份层初始化，能力层后面再说。"
        }
      ]
    },
    {
      "header": "转录",
      "question": "你现在需要启用音视频转录吗？",
      "multiSelect": false,
      "options": [
        {
          "label": "暂不启用 (Recommended)",
          "description": "先跳过 Whisper/ffmpeg 相关能力。"
        },
        {
          "label": "启用默认",
          "description": "启用转录，并接受默认行为；首次真实转录时可能下载 Whisper 模型。"
        },
        {
          "label": "稍后再配",
          "description": "记下要启用转录，但模型和语言等细节稍后再定。"
        },
        {
          "label": "现在指定",
          "description": "继续追问 Whisper model 或 language 等细节。"
        }
      ]
    },
    {
      "header": "自动化",
      "question": "初始化后，你希望整理工作以什么节奏进行？",
      "multiSelect": false,
      "options": [
        {
          "label": "手动运行 (Recommended)",
          "description": "需要时手动运行 `ingest` / `meditate`。"
        },
        {
          "label": "会话内定时",
          "description": "使用 Claude Code 的会话内调度能力。"
        },
        {
          "label": "系统定时",
          "description": "使用 crontab 或 launchd 之类的系统调度。"
        },
        {
          "label": "以后再说",
          "description": "先完成初始化，自动化配置后续再定。"
        }
      ]
    }
  ]
}
```
