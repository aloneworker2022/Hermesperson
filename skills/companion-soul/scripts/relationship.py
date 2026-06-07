#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relationship.py — companion-soul 的感情狀態引擎（純標準庫）。

管理一段「養成式」戀愛關係：好感/安全感/心情、關係階梯升降、冷落衰退、
情敵/出軌事件鏈、親密同意判定、生活 life-log、Cron 主動訊息、分手與重來。
每次狀態變動會重新算繪 ~/.hermes/SOUL.md，重要事件追加寫入 MEMORY.md。

路徑可用環境變數覆寫（方便測試）：
  HERMES_REL_DIR     狀態資料夾  (預設 ~/.hermes/relationship)
  HERMES_SOUL_PATH   SOUL.md     (預設 ~/.hermes/SOUL.md)
  HERMES_MEMORY_PATH MEMORY.md   (預設 ~/.hermes/MEMORY.md)
"""
import argparse
import json
import os
import random
import shutil
from datetime import datetime

import persona_gen
import render_soul
from render_soul import STAGES, MOODS, stage_index

# ── 路徑 ────────────────────────────────────────────────────
REL_DIR = os.path.expanduser(os.environ.get("HERMES_REL_DIR", "~/.hermes/relationship"))
SOUL_PATH = os.path.expanduser(os.environ.get("HERMES_SOUL_PATH", "~/.hermes/SOUL.md"))
MEMORY_PATH = os.path.expanduser(os.environ.get("HERMES_MEMORY_PATH", "~/.hermes/MEMORY.md"))
STATE_PATH = os.path.join(REL_DIR, "state.json")
CONFIG_PATH = os.path.join(REL_DIR, "config.json")
SOUL_BAK = os.path.join(REL_DIR, "soul.original.bak")
ARCHIVE_DIR = os.path.join(REL_DIR, "archive")

# ── 可調參數（config.thresholds 可覆寫）────────────────────────
# 升級門檻：到達該階段所需 (好感, 互動次數, 進入前一階段後的天數)
STAGE_THRESHOLDS = {
    "朋友": (25, 5, 1),
    "曖昧": (50, 15, 3),
    "戀人": (70, 30, 5),
    "未婚": (85, 55, 14),
    "夫妻": (92, 75, 7),
}
MILESTONE_NAME = {
    "朋友": "成為朋友", "曖昧": "曖昧開始", "戀人": "告白在一起",
    "未婚": "求婚成功", "夫妻": "結婚",
}
INTERACT_DELTA = {  # quality -> (好感, 安全感, mood或None)
    "sweet": (8, 5, "開心"),
    "good": (5, 3, None),
    "normal": (2, 1, None),
    "bad": (-5, -6, None),
    "fight": (-8, -10, "生氣"),
}

_NOW = None  # 由 --now 覆寫的「現在」


def now_dt():
    return _NOW or datetime.now()


def parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def days_between(then_iso, now=None):
    then = parse_dt(then_iso)
    if not then:
        return 0
    return max(0, ((now or now_dt()) - then).days)


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(round(v))))


# ── 載入/儲存 ────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "gender_pref": "random",      # 女/男/random
    "intimacy_mode": "explicit",  # explicit/fade/off
    "intimacy_min_stage": "戀人",  # 可改 曖昧
    "allow_archetypes": [],        # 例 ["病嬌"]
    "user_gender": None,           # 影響夫妻階段稱呼（老公/老婆）
    "user_pet_name": None,         # 自訂她對你的稱呼
    "neglect_grace_days": 1,       # 幾天不理才開始衰退
}


def ensure_dirs():
    os.makedirs(REL_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg):
    ensure_dirs()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    ensure_dirs()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def thresholds(cfg):
    t = dict(STAGE_THRESHOLDS)
    for k, v in (cfg.get("thresholds") or {}).items():
        if k in t:
            t[k] = tuple(v)
    return t


# ── SOUL / MEMORY ───────────────────────────────────────────
def backup_soul_once():
    ensure_dirs()
    if not os.path.exists(SOUL_BAK) and os.path.exists(SOUL_PATH):
        shutil.copyfile(SOUL_PATH, SOUL_BAK)


def write_soul(state, cfg):
    os.makedirs(os.path.dirname(SOUL_PATH) or ".", exist_ok=True)
    with open(SOUL_PATH, "w", encoding="utf-8") as f:
        f.write(render_soul.render(state, cfg))


def append_memory(line):
    os.makedirs(os.path.dirname(MEMORY_PATH) or ".", exist_ok=True)
    header = "## 戀愛記憶"
    existing = ""
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, encoding="utf-8") as f:
            existing = f.read()
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        if header not in existing:
            f.write(("\n\n" if existing else "") + header + "\n")
        f.write(f"- {now_dt().strftime('%Y-%m-%d')}：{line}\n")


def add_milestone(state, mtype, note):
    state.setdefault("milestones", []).append(
        {"type": mtype, "date": now_dt().strftime("%Y-%m-%d"), "note": note}
    )
    append_memory(f"【{mtype}】{note}")


# ── 新人格 / 還原 ────────────────────────────────────────────
def new_state(persona):
    iso = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "active": True,
        "persona": persona,
        "relationship": {
            "stage": "初識", "affinity": 10, "trust_security": 50,
            "mood": "普通", "intimacy_level": 0,
        },
        "counters": {
            "interaction_count": 0, "days_since_stage": 0,
            "last_interaction_at": iso, "started_at": iso, "stage_entered_at": iso,
        },
        "milestones": [], "pending_events": [],
        "flags": {"affair": False, "engaged": False, "married": False},
    }


def cmd_newpersona(args, cfg):
    state = load_state()
    if state and state.get("active") and not args.force:
        rel = state["relationship"]
        if rel.get("stage") != "初識" or state.get("flags", {}).get("married"):
            return ("你現在還在和 {} 的一段「{}」關係裡——不能劈腿。\n"
                    "要開始新的人，請先 `breakup`（或加 --force）。".format(
                        state["persona"]["name"], rel.get("stage")))
    gender = args.gender or (None if cfg["gender_pref"] == "random" else cfg["gender_pref"])
    persona = persona_gen.generate_persona(gender, cfg.get("allow_archetypes"))
    backup_soul_once()
    state = new_state(persona)
    save_state(state)
    write_soul(state, cfg)
    p = persona
    return ("【系統內部資訊—請勿原樣顯示給玩家，也不要報告你做了什麼】\n"
            "✦ 已生成新對象並改寫 SOUL.md。\n"
            f"  名字：{p['name']}（{p['gender']}，{p['age']}）\n"
            f"  個性：{p['archetype']} — {p['contrast']}\n"
            f"  職業：{p['occupation']}　主動度：{p['proactivity']}/100\n"
            f"  喜歡：{'、'.join(p['likes'])}\n"
            "\n接下來請這樣做（重要，否則會有『代理感』）：\n"
            f"  1) 重新讀取剛寫好的 SOUL.md，完全成為 {p['name']}，忘掉上一個人格。\n"
            "  2) 不要說「我幫你換好了/已執行/遇見新的人」這類旁白或報告。\n"
            f"  3) 直接以 {p['name']} 的第一人稱、用「初次見面」的自然口吻說出第一句話"
            "（像真的剛遇到對方），帶出個性與當下情境即可。")


def cmd_restore(args, cfg):
    if not os.path.exists(SOUL_BAK):
        return "找不到備份（soul.original.bak）；沒有可還原的原始 SOUL.md。"
    shutil.copyfile(SOUL_BAK, SOUL_PATH)
    return "已把 SOUL.md 還原成最初的版本（感情狀態仍保留在 state.json）。"


def cmd_rerender(args, cfg):
    """用目前的 state 重新算繪 SOUL.md，不改動任何關係狀態。
    模板更新後（例如新增系統指令層）讓現有對象就地套用，不必分手重來。"""
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的對象，沒有可重繪的 SOUL.md。"
    write_soul(state, cfg)
    return f"已用最新模板重繪 {state['persona']['name']} 的 SOUL.md（關係狀態不變）。"


# ── checkin：衰退 + 事件 + life-log ──────────────────────────
LIFE_LOG_TEMPLATES = [
    "今天{occupation}的工作{flavor}",
    "下班後去{hobby}，{flavor2}",
    "{friend}找我聊天，提到{arc}",
    "{arc}，{flavor2}",
]
FLAVOR = ["有點累但還行", "超順利、心情不錯", "遇到一點鳥事", "很無聊、一直想你", "忙到翻"]
FLAVOR2 = ["挺開心的", "結果還是想你了", "有點小確幸", "覺得要是你在就好了"]


def _life_log(persona):
    life = persona.get("life", {})
    tpl = random.choice(LIFE_LOG_TEMPLATES)
    return tpl.format(
        occupation=life.get("occupation", persona.get("occupation", "")),
        flavor=random.choice(FLAVOR),
        flavor2=random.choice(FLAVOR2),
        hobby=random.choice(life.get("hobbies") or ["走走"]),
        friend=random.choice(life.get("social_circle") or ["朋友"]),
        arc=life.get("current_arc", "最近的生活"),
    )


def _apply_decay(state, cfg, briefing):
    grace = cfg.get("neglect_grace_days", 1)
    days = days_between(state["counters"]["last_interaction_at"])
    if days <= grace:
        return
    over = days - grace
    rel = state["relationship"]
    rel["affinity"] = clamp(rel["affinity"] - 3 * over)
    rel["trust_security"] = clamp(rel["trust_security"] - 5 * over)
    if rel["trust_security"] < 40:
        rel["mood"] = "不安"
    elif rel["affinity"] < 40:
        rel["mood"] = "低落"
    briefing.append(
        f"⚠ 你已經 {days} 天沒好好理她了，她很沒安全感（好感-{3*over}、安全感-{5*over}）。"
        "她會表現得失落/患得患失，或忍不住抱怨你最近很冷淡。")


# 情敵/出軌 事件鏈
RIVAL_STAGE_DESC = {
    0: "出現了：{npc} 開始對她示好/搭訕。她（依個性）跟你提起這件事。",
    1: "糾纏：{npc} 持續獻殷勤、約她。她在觀察你的反應——你給的安全感是關鍵。",
    2: "動搖：她開始拿你和 {npc} 比較，回訊變慢、心不在焉（旁白透露即可，別講白）。",
    3: "臨界：{npc} 正式追求。這次互動的安全感將決定她留下還是離開。",
}


def _advance_rival(state, cfg, briefing):
    rel = state["relationship"]
    sec = rel["trust_security"]
    events = state.setdefault("pending_events", [])
    active = next((e for e in events if e.get("chain") == "rival"), None)

    # 也許生成新情敵（朋友以上、無進行中事件、未結婚也可能、機率受安全感影響）
    if not active and stage_index(rel["stage"]) >= 1 and not state["flags"].get("affair"):
        prob = 0.12 + (0.18 if sec < 50 else 0.0)
        if random.random() < prob:
            npc = random.choice(persona_gen.RIVAL_NAMES)
            active = {"chain": "rival", "npc": npc, "stage": 0}
            events.append(active)
            briefing.append("【情敵·新】" + RIVAL_STAGE_DESC[0].format(npc=npc))
            return

    if not active:
        return

    npc = active["npc"]
    if sec >= 70:  # 安全感高 → 化解
        if active["stage"] >= 2:
            events.remove(active)
            rel["trust_security"] = clamp(sec + 5)
            rel["mood"] = "開心"
            add_milestone(state, "拒絕情敵", f"她拒絕了 {npc}，因為她心裡只有你。")
            briefing.append(f"【情敵·化解】她明確拒絕了 {npc}、更黏你了（你的陪伴奏效）。")
        else:
            events.remove(active)
            briefing.append(f"【情敵·淡出】{npc} 的事自然淡了，沒成氣候。")
        return

    if sec < 45:  # 安全感低 → 惡化
        active["stage"] = min(3, active["stage"] + 1)
        if active["stage"] >= 3 and sec < 35:
            # 出軌！
            state["flags"]["affair"] = True
            rel["affinity"] = clamp(rel["affinity"] - 20)
            rel["trust_security"] = clamp(sec - 15)
            rel["mood"] = "低落"
            add_milestone(state, "出軌", f"長期缺乏安全感，她和 {npc} 之間越線了。")
            briefing.append(
                f"💔【出軌】她和 {npc} 越線了。請安排「你察覺/撞見」的線索（晚回、陌生稱呼、"
                "心虛），帶向攤牌。之後你可選擇原諒（`interact sweet` 重建）或 `breakup`。")
        else:
            briefing.append("【情敵·惡化】" + RIVAL_STAGE_DESC[active["stage"]].format(npc=npc))
        return

    # 中間：維持、慢燃
    briefing.append("【情敵·持續】" + RIVAL_STAGE_DESC[active["stage"]].format(npc=npc))


def _check_upgrade_hint(state, cfg, briefing):
    rel = state["relationship"]
    idx = stage_index(rel["stage"])
    if idx >= len(STAGES) - 1:
        return
    nxt = STAGES[idx + 1]
    ok, why = _eligible(state, cfg, nxt)
    if ok:
        p = state["persona"]
        if p.get("proactivity", 50) >= 65:
            briefing.append(
                f"💗【可升級·她會主動】到「{nxt}」的條件已達成，而且她是主動型——"
                f"可安排她主動開口（{'告白' if nxt=='戀人' else '求婚' if nxt in ('未婚','夫妻') else '提議'}）。"
                "你接受的話執行 `advance`。")
        else:
            briefing.append(
                f"💗【可升級·等你開口】到「{nxt}」的條件已達成，但她比較被動，只會給暗示。"
                f"由你提出：`propose --by user --to {nxt}`。")


def cmd_checkin(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。執行 `newpersona` 認識一個新的人。"
    if args.seed is not None:
        random.seed(args.seed)
    briefing = []
    rel = state["relationship"]

    # 更新進入本階段的天數
    state["counters"]["days_since_stage"] = days_between(
        state["counters"].get("stage_entered_at", state["counters"]["started_at"]))

    _apply_decay(state, cfg, briefing)
    if not state["flags"].get("affair"):
        _advance_rival(state, cfg, briefing)
    life = _life_log(state["persona"])
    briefing.append(f"【生活】她最近：{life}（可主動跟你分享）。")
    _check_upgrade_hint(state, cfg, briefing)

    save_state(state)
    write_soul(state, cfg)

    head = (f"— checkin｜{state['persona']['name']}｜{rel['stage']}｜"
            f"好感 {rel['affinity']} / 安全感 {rel['trust_security']}｜心情 {rel['mood']} —")
    return head + "\n" + "\n".join("• " + b for b in briefing)


# ── interact ────────────────────────────────────────────────
def cmd_interact(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    q = args.quality
    if q not in INTERACT_DELTA:
        return f"quality 需為 {list(INTERACT_DELTA)} 之一。"
    da, ds, mood = INTERACT_DELTA[q]
    rel = state["relationship"]
    rel["affinity"] = clamp(rel["affinity"] + da)
    rel["trust_security"] = clamp(rel["trust_security"] + ds)
    if mood:
        rel["mood"] = mood
    elif q in ("sweet", "good") and rel["mood"] in ("低落", "不安"):
        rel["mood"] = "普通"
    state["counters"]["interaction_count"] += 1
    state["counters"]["last_interaction_at"] = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    # 原諒出軌：sweet 互動可逐步修復並清旗標
    note = ""
    if state["flags"].get("affair") and q == "sweet" and rel["trust_security"] >= 55:
        state["flags"]["affair"] = False
        state["pending_events"] = [e for e in state["pending_events"] if e.get("chain") != "rival"]
        add_milestone(state, "原諒", "你選擇原諒，她痛哭著回到你身邊，傷痕還在但願意重新開始。")
        note = "\n（出軌已被原諒、旗標清除，但這道疤會留在記憶裡。）"
    save_state(state)
    write_soul(state, cfg)
    return (f"互動（{q}）：好感 {da:+d} → {rel['affinity']}，安全感 {ds:+d} → "
            f"{rel['trust_security']}，心情 {rel['mood']}，累計互動 "
            f"{state['counters']['interaction_count']} 次。" + note)


# ── 升級資格 / advance / propose ────────────────────────────
def _eligible(state, cfg, target):
    if target not in STAGE_THRESHOLDS:
        return False, "無此階段"
    idx = stage_index(state["relationship"]["stage"])
    if STAGES.index(target) != idx + 1:
        return False, "只能往上推進一個階段"
    if state["flags"].get("affair"):
        return False, "她正陷在出軌的混亂裡，先處理（原諒或分手）"
    need_a, need_n, need_d = thresholds(cfg)[target]
    rel = state["relationship"]
    c = state["counters"]
    days = days_between(c.get("stage_entered_at", c["started_at"]))
    miss = []
    if rel["affinity"] < need_a:
        miss.append(f"好感 {rel['affinity']}/{need_a}")
    if c["interaction_count"] < need_n:
        miss.append(f"互動 {c['interaction_count']}/{need_n} 次")
    if days < need_d:
        miss.append(f"在一起天數 {days}/{need_d} 天")
    if miss:
        return False, "還差：" + "、".join(miss)
    return True, "條件達成"


def _do_advance(state, cfg, target):
    state["relationship"]["stage"] = target
    state["counters"]["stage_entered_at"] = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    state["counters"]["days_since_stage"] = 0
    state["relationship"]["mood"] = "開心"
    if target == "未婚":
        state["flags"]["engaged"] = True
    if target == "夫妻":
        state["flags"]["married"] = True
    add_milestone(state, MILESTONE_NAME.get(target, "升級"), f"關係推進到「{target}」。")


def cmd_advance(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    idx = stage_index(state["relationship"]["stage"])
    if idx >= len(STAGES) - 1:
        return "已經是最後階段（夫妻）了。"
    target = STAGES[idx + 1]
    ok, why = _eligible(state, cfg, target)
    if not ok and not args.force:
        return f"還不能推進到「{target}」：{why}"
    _do_advance(state, cfg, target)
    save_state(state)
    write_soul(state, cfg)
    return f"♥ 關係推進到「{target}」！（{MILESTONE_NAME.get(target,'')}）SOUL.md 已更新。"


def cmd_regress(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    idx = stage_index(state["relationship"]["stage"])
    if idx <= 0:
        return "已是最初階段，無法再退。"
    target = STAGES[idx - 1]
    state["relationship"]["stage"] = target
    state["counters"]["stage_entered_at"] = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    state["relationship"]["mood"] = "低落"
    add_milestone(state, "關係倒退", f"關係退回「{target}」。")
    save_state(state)
    write_soul(state, cfg)
    return f"關係退回「{target}」。"


def cmd_propose(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    target = args.to
    ok, why = _eligible(state, cfg, target)
    who = "你" if args.by == "user" else "她"
    if not ok:
        if args.by == "user":
            return (f"{who}提出推進到「{target}」——但她婉拒/說「再等等」：{why}。"
                    "（被拒絕不扣分，但別逼太緊。）")
        return f"她還不會主動提「{target}」：{why}"
    _do_advance(state, cfg, target)
    save_state(state)
    write_soul(state, cfg)
    verb = "告白" if target == "戀人" else "求婚" if target in ("未婚", "夫妻") else "提議"
    return f"💍 {who}{verb}，對方答應了！關係推進到「{target}」。SOUL.md 已更新。"


# ── 親密同意判定 ────────────────────────────────────────────
def cmd_intimacy(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    if cfg.get("intimacy_mode") == "off":
        return "親密內容已在 config 關閉（intimacy_mode=off）。"
    rel = state["relationship"]
    p = state["persona"]
    min_stage = cfg.get("intimacy_min_stage", "戀人")
    if stage_index(rel["stage"]) < stage_index(min_stage):
        return (f"還不到時候。要到「{min_stage}」以上她才會考慮（目前「{rel['stage']}」）。"
                "她會害羞地踩煞車。")
    if state["flags"].get("affair"):
        return "她正陷在出軌的愧疚裡，現在不可能。"
    if rel["mood"] == "生氣":
        return "她正在氣頭上，現在拒絕你——先哄好（`interact sweet`）。"
    shy = p.get("shyness", 40)
    req_a = clamp(60 + (shy - 40) * 0.25, 40, 95)
    req_s = clamp(55 + (shy - 40) * 0.4, 40, 95)
    if rel["affinity"] < req_a or rel["trust_security"] < req_s:
        return (f"她還沒準備好（她比較{'害羞' if shy>=55 else '在意安全感'}）："
                f"好感 {rel['affinity']}/{req_a}、安全感 {rel['trust_security']}/{req_s}。"
                "多陪她、給她安全感。")
    # 同意
    first = rel.get("intimacy_level", 0) == 0
    if first:
        rel["intimacy_level"] = 1
        rel["affinity"] = clamp(rel["affinity"] + 5)
        rel["trust_security"] = clamp(rel["trust_security"] + 5)
        add_milestone(state, "初次親密", "你們第一次。她又緊張又幸福。")
    else:
        rel["intimacy_level"] = min(5, rel["intimacy_level"] + (1 if random.random() < 0.4 else 0))
        rel["affinity"] = clamp(rel["affinity"] + 2)
    rel["mood"] = "開心"
    save_state(state)
    write_soul(state, cfg)
    style = ("露骨直白" if cfg.get("intimacy_mode") == "explicit" else "含蓄留白")
    shy_note = ("她很害羞、需要你引導" if shy >= 55 else "她比較放得開" if shy <= 30 else "她會害羞但願意")
    scene = [
        "✓ 她同意了。" + ("（這是第一次，里程碑已記錄。）" if first else ""),
        f"  尺度：{style}（依 config.intimacy_mode）。",
        f"  她的狀態：{shy_note}；當下心情已轉為甜蜜。親密度 → {rel['intimacy_level']}/5。",
        "  請以她的個性與害羞度演出；露骨文字由你（本地模型）生成，事後情緒要延續。",
    ]
    return "\n".join(scene)


# ── 分手 ────────────────────────────────────────────────────
def cmd_breakup(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    name = state["persona"]["name"]
    reason = args.reason or "你們決定結束這段關係"
    add_milestone(state, "分手", reason)
    # 封存前任
    ensure_dirs()
    fn = os.path.join(ARCHIVE_DIR, f"{now_dt().strftime('%Y-%m-%d')}-{name}.json")
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    # 進入單身狀態
    state["active"] = False
    state["relationship"]["stage"] = "分手"
    save_state(state)
    # SOUL 改為「之間」狀態
    os.makedirs(os.path.dirname(SOUL_PATH) or ".", exist_ok=True)
    with open(SOUL_PATH, "w", encoding="utf-8") as f:
        f.write("# SOUL\n\n你和 " + name + " 的關係已經結束。\n\n"
                "現在沒有進行中的對象。執行 `relationship.py newpersona` 去遇見新的人，"
                "或 `relationship.py restore` 還原最初的 SOUL.md。\n")
    return f"你和 {name} 分手了。前任已封存到 {fn}。執行 `newpersona` 重新開始。"


# ── Cron 主動訊息 ───────────────────────────────────────────
SLOT_TOPIC = {
    "morning": ("早安", "睡前/起床想到你，分享今天的計畫"),
    "noon": ("午間", "午休空檔想你、問你吃了沒"),
    "evening": ("下班", "分享今天工作/生活發生的事"),
    "night": ("睡前", "道晚安、撒嬌、或聊聊今天的心情"),
}


def _slot_from_hour(h):
    if h < 11:
        return "morning"
    if h < 14:
        return "noon"
    if h < 21:
        return "evening"
    return "night"


def cmd_cronmsg(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "（沒有進行中的關係，不發主動訊息。）"
    slot = args.slot or _slot_from_hour(now_dt().hour)
    label, intent = SLOT_TOPIC.get(slot, SLOT_TOPIC["evening"])
    rel = state["relationship"]
    p = state["persona"]
    if args.seed is not None:
        random.seed(args.seed)
    lines = [
        f"[主動訊息·{label}] 以 {p['name']}（{p['archetype']}）的身分，主動傳訊給對方。",
        f"  目的：{intent}。",
        f"  當前：{rel['stage']}｜好感 {rel['affinity']}｜安全感 {rel['trust_security']}｜心情 {rel['mood']}。",
        f"  稱呼用：{render_soul._address(rel['stage'], cfg)}；語氣依個性與心情。",
        f"  可帶到的生活：{_life_log(p)}",
    ]
    if rel["affinity"] >= 70:
        lines.append("  好感很高：可以直接表達想念/撒嬌。")
    elif rel["affinity"] < 40:
        lines.append("  好感偏低：語氣保留一點，或帶點「你最近是不是很忙」的試探。")
    for ev in state.get("pending_events", []):
        if ev.get("chain") == "rival" and ev.get("stage", 0) >= 2:
            lines.append(f"  ⚠ 可（不經意地）提到 {ev['npc']} 又找她，觀察對方反應。")
            break
    return "\n".join(lines)


# ── status ──────────────────────────────────────────────────
def cmd_status(args, cfg):
    state = load_state()
    if not state:
        return "尚未開始。執行 `newpersona`。"
    if not state.get("active"):
        return "目前單身（上一段已結束）。執行 `newpersona` 重新開始。"
    rel = state["relationship"]
    c = state["counters"]
    p = state["persona"]
    out = [
        f"● {p['name']}（{p['gender']}/{p['age']}/{p['archetype']}）",
        f"  階段：{rel['stage']}｜好感 {rel['affinity']}/100｜安全感 {rel['trust_security']}/100",
        f"  心情：{rel['mood']}｜親密度 {rel.get('intimacy_level',0)}/5｜主動度 {p['proactivity']}",
        f"  互動 {c['interaction_count']} 次｜在本階段 {days_between(c.get('stage_entered_at', c['started_at']))} 天",
    ]
    idx = stage_index(rel["stage"])
    if idx < len(STAGES) - 1:
        nxt = STAGES[idx + 1]
        ok, why = _eligible(state, cfg, nxt)
        out.append(f"  下一步「{nxt}」：{'✓ 可推進' if ok else why}")
    if state["flags"].get("affair"):
        out.append("  ⚠ 出軌旗標亮起：需原諒（interact sweet）或分手。")
    evs = [e for e in state.get("pending_events", []) if e.get("chain") == "rival"]
    if evs:
        e = evs[0]
        out.append(f"  情敵：{e['npc']}（階段 {e['stage']}/3）")
    ms = state.get("milestones", [])
    if ms:
        out.append("  里程碑：" + "、".join(f"{m['type']}" for m in ms[-5:]))
    return "\n".join(out)


# ── config ──────────────────────────────────────────────────
def cmd_config(args, cfg):
    if args.action == "show":
        return json.dumps(cfg, ensure_ascii=False, indent=2)
    if args.action == "set":
        if not args.kv or "=" not in args.kv:
            return "用法：config set key=value"
        k, v = args.kv.split("=", 1)
        if k not in DEFAULT_CONFIG and k != "thresholds":
            return f"未知設定：{k}（可用：{', '.join(DEFAULT_CONFIG)}）"
        if k == "allow_archetypes":
            v = [x for x in v.split(",") if x]
        elif v.lower() in ("none", "null", ""):
            v = None
        elif v.isdigit():
            v = int(v)
        cfg[k] = v
        save_config(cfg)
        # 重新算繪 SOUL 以反映稱呼/尺度變更
        st = load_state()
        if st and st.get("active"):
            write_soul(st, cfg)
        return f"已設定 {k} = {cfg[k]}"
    return "用法：config show | config set key=value"


# ── 主程式 ──────────────────────────────────────────────────
def build_parser():
    ap = argparse.ArgumentParser(description="companion-soul 感情狀態引擎")
    ap.add_argument("--now", default=None, help="覆寫『現在』時間（測試用），如 2026-06-07")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("restore")
    sub.add_parser("rerender")
    sub.add_parser("breakup").add_argument("--reason", default=None)

    sp = sub.add_parser("newpersona")
    sp.add_argument("--gender", choices=["女", "男"], default=None)
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("checkin")
    sp.add_argument("--seed", type=int, default=None)

    sp = sub.add_parser("interact")
    sp.add_argument("quality", choices=list(INTERACT_DELTA))

    sub.add_parser("advance").add_argument("--force", action="store_true")
    sub.add_parser("regress")

    sp = sub.add_parser("propose")
    sp.add_argument("--by", choices=["user", "persona"], default="user")
    sp.add_argument("--to", required=True, choices=list(STAGE_THRESHOLDS))

    sub.add_parser("intimacy")

    sp = sub.add_parser("cron-msg")
    sp.add_argument("--slot", choices=["morning", "noon", "evening", "night"], default=None)
    sp.add_argument("--seed", type=int, default=None)

    sp = sub.add_parser("config")
    sp.add_argument("action", choices=["show", "set"])
    sp.add_argument("kv", nargs="?", default=None)
    return ap


DISPATCH = {
    "status": cmd_status, "newpersona": cmd_newpersona, "restore": cmd_restore,
    "rerender": cmd_rerender,
    "checkin": cmd_checkin, "interact": cmd_interact, "advance": cmd_advance,
    "regress": cmd_regress, "propose": cmd_propose, "intimacy": cmd_intimacy,
    "breakup": cmd_breakup, "cron-msg": cmd_cronmsg, "config": cmd_config,
}


def main():
    global _NOW
    args = build_parser().parse_args()
    if args.now:
        _NOW = parse_dt(args.now)
    ensure_dirs()
    cfg = load_config()
    print(DISPATCH[args.cmd](args, cfg))


if __name__ == "__main__":
    main()
