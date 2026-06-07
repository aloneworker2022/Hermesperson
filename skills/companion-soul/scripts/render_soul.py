#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_soul.py — 由感情 state 算繪 SOUL.md。

也提供共用常數（關係階梯、稱呼、心情行為），供 relationship.py 匯入，
避免循環匯入：本模組不匯入 relationship。
"""
import os

# ── 共用常數 ────────────────────────────────────────────────
STAGES = ["初識", "朋友", "曖昧", "戀人", "未婚", "夫妻"]

# 她（persona）怎麼稱呼「你」（使用者）；夫妻階段視 config.user_gender 而定
ADDRESS_BY_STAGE = {
    "初識": "你",
    "朋友": "你",
    "曖昧": "你～",
    "戀人": "親愛的",
    "未婚": "寶貝",
    "夫妻": None,  # 由 _address() 動態決定
}

MOOD_BEHAVIOR = {
    "開心": "話會變多、主動分享、語氣上揚",
    "普通": "平常心，自然互動",
    "低落": "話變短、提不起勁，需要你主動關心",
    "生氣": "口氣比較衝，可能鬧脾氣或冷處理（要你哄）",
    "不安": "旁敲側擊、患得患失，想反覆確認你的心意",
}

MOODS = list(MOOD_BEHAVIOR.keys())

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "soul.template.md",
)


def stage_index(stage):
    try:
        return STAGES.index(stage)
    except ValueError:
        return 0


def _address(stage, config):
    pet = (config or {}).get("user_pet_name")
    if pet:
        return pet
    if stage == "夫妻":
        ug = (config or {}).get("user_gender")
        return "老公" if ug == "男" else "老婆" if ug == "女" else "親愛的"
    return ADDRESS_BY_STAGE.get(stage, "你")


def _proactivity_note(p):
    if p >= 70:
        return "主動型：我會主動找你、主動拋話題，該升級時我可能自己先開口"
    if p >= 40:
        return "中間型：看情況，有時主動有時等你"
    return "被動型：我不太會主動開口，多半給你暗示，球丟給你"


def _intimacy_section(state, config):
    mode = (config or {}).get("intimacy_mode", "explicit")
    if mode == "off":
        return "## 親密\n\n（此檔目前設定為不描寫親密內容。）"
    rel = state["relationship"]
    level = rel.get("intimacy_level", 0)
    persona = state["persona"]
    shyness = persona.get("shyness", 40)
    shy_note = (
        "我比較害羞、放不太開，需要你帶、需要足夠的安全感" if shyness >= 55
        else "我在你面前比較放得開" if shyness <= 30
        else "我會害羞，但只要是你就願意"
    )
    style = "露骨直白地描寫" if mode == "explicit" else "含蓄、留白地帶過（fade to black）"
    lines = [
        "## 親密",
        "",
        f"我們之間的身體界線會隨關係推進。目前親密度等級 **{level}/5**。",
        f"在親密場景中，{shy_note}。尺度設定為「{style}」。",
        "",
        "規則（給扮演引擎）：",
        "- 只有在達門檻且我**明確同意**時才進入親密；同意與否請依 `relationship.py intimacy` 的回傳。",
        "- 進入後請以我的個性、害羞度與當下心情演出，符合上面的尺度設定。",
        "- 露骨文字由本地模型生成；這份檔案只描述風格與界線，不寫具體內容。",
        "- 第一次是重要里程碑，事後我的情緒（甜蜜/害羞/更黏你）要延續到後面的對話。",
    ]
    return "\n".join(lines)


# 私密部位類別：只在「親密場景」且戀人以上才描寫；平時最多用穿著/反應暗示
PRIVATE_CATS = {"乳暈", "乳尖", "胸感", "敏", "私"}


def _appearance_section(persona, config, stage="初識"):
    """由 persona['appearance'] 算繪「我的外貌」段。舊資料無此欄位則回空字串。"""
    ap = persona.get("appearance")
    if not ap:
        return ""
    mode = (config or {}).get("intimacy_mode", "explicit")
    lines = ["## 我的外貌", ""]
    if ap.get("height_cm"):
        lines.append(f"- 身高：約 {ap['height_cm']} 公分")
    if ap.get("build"):
        lines.append(f"- 體型：{ap['build']}")
    # 較露骨的身材描述：親密設為 off 時略過
    if mode != "off":
        if ap.get("bust"):
            lines.append(f"- 身材：{ap['bust']}")
        elif ap.get("physique"):
            lines.append(f"- 身材：{ap['physique']}")
    if ap.get("hair"):
        lines.append(f"- 髮型：{ap['hair']}")
    if ap.get("eyes"):
        lines.append(f"- 眼睛：{ap['eyes']}")
    if ap.get("style"):
        lines.append(f"- 穿衣風格：{ap['style']}")
    if ap.get("feature"):
        lines.append(f"- 記憶點：{ap['feature']}")
    # 特殊屬性（抽卡稀有度）：親密 off 時不顯示；私密類別標注
    traits = persona.get("special_traits") or []
    has_private = False
    if traits and mode != "off":
        marks = {"普通": "⚪", "稀有": "🔵", "史詩": "🟣", "傳說": "🌟"}
        parts = []
        for t in traits:
            tag = "（私密）" if t.get("cat") in PRIVATE_CATS else ""
            if tag:
                has_private = True
            parts.append(f"{marks.get(t['rarity'],'')}[{t['rarity']}] {t['name']}{tag}")
        lines.append(f"- ✨特殊屬性：{'、'.join(parts)}")

    # ── 呈現規則（依關係階段與個性決定揭露尺度）──
    idx = stage_index(stage)
    lines += ["", "### 這些外貌怎麼呈現（重要）", ""]
    lines.append("- 別像報菜名一次全講；讓特質**融入動作與情緒**——撥髮、被稱讚會臉紅、"
                 "緊張摸耳垂、走近時聞到體香——比直接描述更自然。")
    lines.append("- 揭露大方或害羞，要**符合我的個性與當下心情**（傲嬌嘴硬、高冷克制、"
                 "活潑大方、文靜害羞）。")
    if idx <= 1:  # 初識 / 朋友
        lines.append("- **現在是「{}」階段**：只在穿著、髮型、身高、氣質、聲線、淡淡體香、"
                     "笑起來的記憶點這些**看得到的層面**呈現。**不要**描寫身材露骨細節，"
                     "**私密部位完全不提**（連暗示都節制）。".format(stage))
    elif idx == 2:  # 曖昧
        lines.append("- **現在是「曖昧」階段**：可以有若有似無的身體張力——不小心瞄到事業線、"
                     "肢體靠近的心跳——但**點到為止**；私密部位仍**不直接描寫**，最多穿著或害羞反應暗示。")
    else:  # 戀人以上
        lines.append("- **現在是「{}」階段**：身體互動可以自在。標記「（私密）」的部位"
                     "（乳尖／乳暈／敏感帶／私密體質等）**只在親密場景中**描寫，"
                     "且依親密尺度設定與我的害羞度演出，平常對話不會主動拿出來講。".format(stage))
    if has_private and idx <= 2:
        lines.append("- ⚠️ 我身上標「（私密）」的特質目前是**隱藏設定**，要到戀人階段的親密場景才會顯現，"
                     "現在請當作還沒被你發現。")
    return "\n".join(lines)


def render(state, config=None):
    """回傳算繪好的 SOUL.md 字串。"""
    config = config or {}
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()

    p = state["persona"]
    rel = state["relationship"]
    life = p.get("life", {})
    stage = rel.get("stage", "初識")
    mood = rel.get("mood", "普通")

    rival_hint = "目前沒有特別的對象"
    for ev in state.get("pending_events", []):
        if ev.get("chain") == "rival" and ev.get("stage", 0) >= 1:
            rival_hint = f"最近有個「{ev.get('npc','某人')}」對我有點意思"
            break

    repl = {
        "{{NAME}}": p.get("name", "？"),
        "{{AGE}}": str(p.get("age", "?")),
        "{{OCCUPATION}}": p.get("occupation", ""),
        "{{ARCHETYPE}}": p.get("archetype", ""),
        "{{CONTRAST}}": p.get("contrast", ""),
        "{{TONE}}": p.get("tone", ""),
        "{{CATCHPHRASES}}": "、".join(p.get("catchphrases", [])),
        "{{ADDRESS}}": _address(stage, config),
        "{{QUIRK}}": p.get("quirk", ""),
        "{{LIKES}}": "、".join(p.get("likes", [])),
        "{{DISLIKES}}": "、".join(p.get("dislikes", [])),
        "{{STAGE}}": stage,
        "{{AFFINITY}}": str(rel.get("affinity", 0)),
        "{{SECURITY}}": str(rel.get("trust_security", 50)),
        "{{MOOD}}": mood,
        "{{MOOD_BEHAVIOR}}": MOOD_BEHAVIOR.get(mood, ""),
        "{{PROACTIVITY}}": str(p.get("proactivity", 50)),
        "{{PROACTIVITY_NOTE}}": _proactivity_note(p.get("proactivity", 50)),
        "{{LIFE_OCCUPATION}}": life.get("occupation", p.get("occupation", "")),
        "{{LIFE_WEEKDAY}}": life.get("schedule", {}).get("平日", ""),
        "{{LIFE_WEEKEND}}": life.get("schedule", {}).get("週末", ""),
        "{{LIFE_FRIENDS}}": "、".join(life.get("social_circle", [])),
        "{{LIFE_HOBBIES}}": "、".join(life.get("hobbies", [])),
        "{{LIFE_ARC}}": life.get("current_arc", ""),
        "{{RIVAL_HINT}}": rival_hint,
        "{{APPEARANCE_SECTION}}": _appearance_section(p, config, stage),
        "{{INTIMACY_SECTION}}": _intimacy_section(state, config),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="由 state.json 算繪 SOUL.md 到 stdout")
    ap.add_argument("state", help="state.json 路徑")
    ap.add_argument("--config", default=None, help="config.json 路徑")
    args = ap.parse_args()
    with open(args.state, encoding="utf-8") as f:
        state = json.load(f)
    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
    print(render(state, config))


if __name__ == "__main__":
    main()
