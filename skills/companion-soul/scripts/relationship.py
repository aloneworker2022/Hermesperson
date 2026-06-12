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
from render_soul import STAGES, MOODS, stage_index, ANGER_THRESHOLD

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
ANGER_GAIN = {"bad": 15, "fight": 30, "pester": 20}  # 各種惹怒互動的怒氣增量


def _persona_grade(persona):
    return (persona.get("overall") or {}).get("grade") or "R"


INTERACT_DELTA = {  # quality -> (好感, 安全感, mood或None)
    "sweet": (8, 5, "開心"),
    "good": (5, 3, None),
    "normal": (2, 1, None),
    "bad": (-5, -6, None),
    "fight": (-8, -10, "生氣"),
    "pester": (-10, -4, "生氣"),  # 強人所難：逼她做不來/討厭的事；連續會加重（見 cmd_interact）
    "help": (2, 1, None),         # 她盡心幫了你的忙；好感依階段、邊際遞減（見 cmd_interact）
}

_NOW = None  # 由 --now 覆寫的「現在」
_TZ = None   # 時區快取（config timezone / 環境變數 HERMES_TZ，預設台灣）


def _tz():
    global _TZ
    if _TZ is None:
        name = os.environ.get("HERMES_TZ") or load_config().get("timezone") or "Asia/Taipei"
        try:
            from zoneinfo import ZoneInfo
            _TZ = ZoneInfo(name)
        except Exception:  # 無 tzdata 時退回固定 UTC+8
            from datetime import timezone as _dtz, timedelta as _td
            _TZ = _dtz(_td(hours=8))
    return _TZ


def now_dt():
    """『現在』：依設定時區（預設台灣 Asia/Taipei），回傳 naive datetime 與存檔格式一致。"""
    return _NOW or datetime.now(_tz()).replace(tzinfo=None)


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
    "gender_pref": "女",          # 女/男/random（預設女；除非指定男或設成 random）
    "intimacy_mode": "explicit",  # explicit/fade/off
    "intimacy_min_stage": "戀人",  # 可改 曖昧
    "allow_archetypes": [],        # 例 ["病嬌"]
    "user_gender": None,           # 影響夫妻階段稱呼（老公/老婆）
    "user_pet_name": None,         # 自訂她對你的稱呼
    "neglect_grace_days": 1,       # 幾天不理才開始衰退
    "rare_luck": 0,                # 特殊屬性幸運值 0~100（越高越容易抽到高稀有度）
    "img_tags": "off",             # on 時每則回覆第一行輸出 ⟦標籤⟧ 供外部專案(如 Talkinter)套圖
    "img_tag_avatar": "01",        # 表情標籤的前綴代號，如 ⟦01:smile⟧
    "img_expr_set": "basic",       # basic=只用 5 種心情表情 / full=14 種
    "img_scene": "off",            # off=不輸出場景標籤 / basic=3 種簡單場景 / full=9 種
    "timezone": "Asia/Taipei",     # 人物與玩家共用的時區（影響作息/衰退天數計算）
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
            "mood": "普通", "intimacy_level": 0, "affair_count": 0,
            "anger": 0,
        },
        "counters": {
            "interaction_count": 0, "days_since_stage": 0,
            "last_interaction_at": iso, "started_at": iso, "stage_entered_at": iso,
            "overask_streak": 0, "help_streak": 0, "anger_strikes": 0,
        },
        "milestones": [], "memories": [], "pending_events": [],
        "flags": {"affair": False, "engaged": False, "married": False,
                  "leaving": False, "caught_in_act": False},
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
    luck = int(cfg.get("rare_luck") or 0)
    persona = persona_gen.generate_persona(gender, cfg.get("allow_archetypes"), luck)
    backup_soul_once()
    state = new_state(persona)
    save_state(state)
    write_soul(state, cfg)
    p = persona
    n_traits = len(p.get("special_traits") or [])
    grade = _persona_grade(p)
    limit = ANGER_THRESHOLD.get(grade, 9)
    banner = {"SSR": "🌟🌟 SSR！傳說級的相遇 🌟🌟\n", "SR": "🟣 SR！稀有的相遇 🟣\n"}.get(grade, "")
    # 刻意保留神祕感：只揭露性別、總評與「有幾個特殊」，名字/個性/外貌/特殊內容都靠相處與「觀察」慢慢發現。
    return (banner + "✦ 你遇見了一個新的人。\n"
            f"  性別：{p['gender']}\n"
            f"  人物稀有度：{grade}（綜合評分 {p.get('overall', {}).get('score', '?')}）\n"
            f"  脾氣：被惹怒 {limit} 次就會出大事——稀有度越高越難伺候\n"
            f"  特殊：{n_traits} 個（內容先保密，靠相處和「觀察」自己發現）\n"
            "  SOUL.md 已改寫。請以「初次見面」的口吻開場，但**不要主動報出名字、個性、"
            "外貌或特殊屬性**——這些要讓玩家透過聊天與「觀察」慢慢挖掘，不要一次講白。")


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


MAX_MEMORIES = 60  # state 內最多保留幾則記憶（render 只取最近 N 則，見 render_soul）


def cmd_remember(args, cfg):
    """記住一件聊天中的重要事（玩家偏好/約定/聊過的事/綽號…）。會寫進 state 並重繪進 SOUL.md，
    讓她下次（甚至下個 session）還記得。由扮演的引擎在對話中主動呼叫。"""
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的對象。"
    note = (args.note or "").strip()
    if not note:
        return "用法：remember <要記住的事>"
    iso = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    mems = state.setdefault("memories", [])
    mems.append({"note": note, "at": iso})
    if len(mems) > MAX_MEMORIES:
        del mems[:-MAX_MEMORIES]
    append_memory(f"【記事】{note}")
    save_state(state)
    write_soul(state, cfg)
    return f"（記住了：{note}）目前共記得 {len(mems)} 件事，已寫進 SOUL.md。"


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


def _in_window(h, start, end):
    """h 是否落在 [start, end) 時段（支援跨夜，如 22→3）。"""
    if start <= end:
        return start <= h < end
    return h >= start or h < end


def _routine_now(persona, dt):
    """依現在時間推斷她正在做什麼。回傳 (描述, 是否在睡, 被吵醒反應)；舊存檔無 routine 回 None。"""
    rt = (persona.get("life") or {}).get("routine")
    if not rt:
        return None
    h, wd = dt.hour, dt.weekday()  # wd 0=週一
    sleeping = _in_window(h, rt.get("sleep_at", 0), rt.get("wake_at", 7))
    nap = rt.get("chrono") == "愛睡午覺" and 13 <= h < 15
    working = (_in_window(h, rt.get("work_start", 9), rt.get("work_end", 18))
               and not (rt.get("weekend_off") and wd >= 5))
    if sleeping or nap:
        kind = "睡午覺" if (nap and not sleeping) else "睡覺"
        return (f"正在{kind}（{rt.get('chrono','')}：{rt.get('chrono_desc','')}）",
                True, rt.get("wake_react", "迷糊地醒來"))
    if working:
        return (f"正在工作——{rt.get('work_desc','')}", False, None)
    return (f"下班／休息中（{rt.get('chrono','')}，{rt.get('chrono_desc','')}）", False, None)


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
    0: "{npc} 開始對她示好/搭訕。她（依個性）跟你提起這件事。",
    1: "{npc} 持續獻殷勤、約她。她在觀察你的反應。",
    2: "她開始拿你和 {npc} 比較，回訊變慢、心不在焉。",
    3: "{npc} 正式追求，攤牌在即。",
}


def _rival_name(r):
    return r.get("name") or r.get("npc") or "某人"


def _rival_label(r):
    """情敵身分標籤，如：阿凱（健身教練・金錢攻勢）。"""
    bits = [b for b in (r.get("relation"), r.get("tactic")) if b]
    return f"{_rival_name(r)}（{'・'.join(bits)}）" if bits else _rival_name(r)


def _rival_action(r, stage):
    """這個階段他具體做了什麼（依手段；舊資料退回通用描述）。"""
    seq = persona_gen.RIVAL_TACTIC.get(r.get("tactic"))
    tpl = seq[stage] if seq and 0 <= stage < len(seq) else RIVAL_STAGE_DESC.get(stage, "")
    return tpl.format(npc=_rival_name(r))


def _temptation(rel, persona, rival):
    """誘惑壓力：安全感低、忠誠低、情敵魅力高、出軌前科多 → 越大。"""
    return ((50 - rel.get("trust_security", 50))
            + (55 - persona.get("loyalty", 60))
            + (rival.get("allure", 50) - 50)
            + 8 * rel.get("affair_count", 0))


def _trigger_affair(state, cfg, rival, briefing):
    """觸發出軌：一定發生關係；並依條件決定是『出軌(可攤牌)』還是『她直接離開你』。"""
    rel, persona = state["relationship"], state["persona"]
    name = _rival_name(rival)
    rel["affair_count"] = rel.get("affair_count", 0) + 1
    state["flags"]["affair"] = True
    rel["affinity"] = clamp(rel["affinity"] - 20)
    rel["trust_security"] = clamp(rel["trust_security"] - 15)
    rel["mood"] = "低落"
    idx = stage_index(rel["stage"])
    # 變本加厲：夫妻關係、且已是再犯（原諒過至少一次）→ 可能在自家被當場撞見正在交配
    caught = (idx >= 5 and rel["affair_count"] >= 2 and random.random() < 0.4)
    state["flags"]["caught_in_act"] = caught
    # 她主動離開你的機率：階段越低 / 復發越多 / 忠誠越低 / 魅力越高 → 越高
    leave = (0.10 + max(0, 3 - idx) * 0.12 + (rel["affair_count"] - 1) * 0.15
             + max(0, 50 - persona.get("loyalty", 60)) * 0.006
             + max(0, rival.get("allure", 50) - 60) * 0.008)
    if random.random() < min(0.9, leave):
        state["flags"]["leaving"] = True
        add_milestone(state, "離開", f"她為了 {_rival_label(rival)} 離開你。")
        briefing.append(
            f"💔💔【被奪走】她不只越線——她決定為了 {name} 離開你。請演出她提分手、跟對方走。"
            "此結局極難挽回（需連續高品質 `interact sweet` 把安全感重建到很高），否則只能 `breakup`。"
            "細節見 SOUL 的『現在的危機』。")
    else:
        add_milestone(state, "出軌",
                      f"她和 {_rival_label(rival)} 越線了（第 {rel['affair_count']} 次）。")
        briefing.append(
            f"💔【出軌·第{rel['affair_count']}次】她和 {name} 發生了關係。請安排你察覺/撞見的線索並"
            "帶向攤牌；她面對質問的態度依關係階段不同（見 SOUL 的『現在的危機』）。"
            "之後可原諒（`interact sweet` 重建≥55）或 `breakup`。")
    if caught:
        briefing.append(
            f"🔥【撞見現行】這次更不堪——你回到家，當場撞見她正和 {name} 在自己家裡交媾。"
            "請依 SOUL『現在的危機』演出這個正在進行式的場景（尺度受 intimacy_mode 控）。")


def _anger_blowup(state, cfg):
    """惹怒次數達到稀有度門檻：依關係階段引爆後果。回傳給玩家/LLM 的說明文字。"""
    rel, persona = state["relationship"], state["persona"]
    name = persona["name"]
    idx = stage_index(rel["stage"])
    state["counters"]["anger_strikes"] = 0
    rel["anger"] = 100
    rel["mood"] = "生氣"

    if idx <= 2:  # 初識/朋友/曖昧 → 直接離開（關係結束）
        add_milestone(state, "離開", f"{name} 受夠了你一再惹怒她，頭也不回地離開了。")
        ensure_dirs()
        fn = os.path.join(ARCHIVE_DIR, f"{now_dt().strftime('%Y-%m-%d')}-{name}.json")
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        state["active"] = False
        rel["stage"] = "分手"
        save_state(state)
        os.makedirs(os.path.dirname(SOUL_PATH) or ".", exist_ok=True)
        with open(SOUL_PATH, "w", encoding="utf-8") as f:
            f.write("# SOUL\n\n" + name + " 受夠了你，已經離開。\n\n"
                    "現在沒有進行中的對象。請結束這段對話；"
                    "想認識新的人，執行 `relationship.py newpersona`（或短指令 `newOne`）。\n")
        return (f"\n💢💢【她離開了】你把 {name} 惹怒太多次，她受夠了、頭也不回地走了。"
                "請演出她甩門離去，然後跳出角色提示玩家：目前沒有人了，請用 `newOne` 認識新的人。")

    # 戀人/未婚/夫妻：找異性朋友訴苦 + 50% 出軌
    events = state.setdefault("pending_events", [])
    events[:] = [e for e in events if e.get("chain") != "rival"]
    rival = persona_gen.generate_rival(persona)
    rival["relation"] = "聽她訴苦的異性朋友"
    briefing = []
    cheated = random.random() < 0.5
    if cheated:
        rival["stage"] = 3
        events.append(rival)
        _trigger_affair(state, cfg, rival, briefing)
    else:
        rival["stage"] = 2
        events.append(rival)

    rname = _rival_name(rival)
    if idx <= 4:  # 戀人/未婚 → 跑走
        add_milestone(state, "怒而出走", f"被你惹怒太多次，{name} 奪門而出，跑去找 {rname} 訴苦。")
        text = (f"\n💢💢【她跑走了】你把 {name} 惹怒太多次——她奪門而出、不接電話，"
                f"跑去找 {rname} 訴苦。請演出她甩門離開，**本次聊天就此結束**"
                "（跳出角色提示玩家：她走了，請先冷靜，下次對話再 `checkin` 看後續）。")
    else:  # 夫妻 → 大吵一架（不走）
        add_milestone(state, "大吵一架", f"被你惹怒太多次，{name} 和你大吵一架，跑去找 {rname} 訴苦。")
        text = (f"\n💢💢【大吵一架】你把 {name} 惹怒太多次——她和你激烈大吵，"
                f"之後冷戰，並開始找 {rname} 訴苦取暖。")
    if cheated:
        text += "\n" + "\n".join(briefing)
    else:
        text += f"\n（⚠ {rname} 趁虛而入，她正在動搖——再不哄好，事情會往最糟的方向去。）"
    return text


def _advance_rival(state, cfg, briefing):
    rel, persona = state["relationship"], state["persona"]
    sec = rel["trust_security"]
    events = state.setdefault("pending_events", [])
    active = next((e for e in events if e.get("chain") == "rival"), None)

    # 生成新情敵（朋友以上、無進行中事件、未出軌）
    if not active and stage_index(rel["stage"]) >= 1 and not state["flags"].get("affair"):
        prob = (0.12 + (0.18 if sec < 50 else 0.0)
                + max(0, 55 - persona.get("loyalty", 60)) * 0.004
                + rel.get("affair_count", 0) * 0.05)
        if random.random() < prob:
            active = persona_gen.generate_rival(persona)
            events.append(active)
            briefing.append(
                f"【情敵·新】{_rival_label(active)} 出現了——{active.get('looks','')}，"
                f"{active.get('edge','')}（魅力 {active.get('allure',50)}）。"
                f"{_rival_action(active, 0)}。她（依個性）會跟你提起。")
            return

    if not active:
        return

    name = _rival_name(active)
    T = _temptation(rel, persona, active)

    # 化解：安全感高且誘惑壓力不大（她夠忠誠、情敵沒那麼致命）
    if sec >= 70 and T < 30:
        if active["stage"] >= 2:
            events.remove(active)
            rel["trust_security"] = clamp(sec + 5)
            rel["mood"] = "開心"
            add_milestone(state, "拒絕情敵", f"她當著你的面回絕了 {_rival_label(active)}，心裡只有你。")
            briefing.append(f"【情敵·化解】她明確回絕了 {name}、更黏你了（你的陪伴奏效）。")
        else:
            events.remove(active)
            briefing.append(f"【情敵·淡出】{name} 的事自然淡了，沒成氣候。")
        return

    # 惡化：誘惑壓力大 → 推進，必要時觸發出軌
    if T >= 25:
        active["stage"] = min(3, active["stage"] + 1)
        if (active["stage"] >= 3 and T >= 40) or (active["stage"] >= 2 and T >= 75):
            _trigger_affair(state, cfg, active, briefing)
        else:
            briefing.append(f"【情敵·惡化】{_rival_action(active, active['stage'])}"
                            "（動搖期只用旁白暗示、別講白）。")
        return

    # 中間：維持、慢燃
    briefing.append(f"【情敵·持續】{_rival_action(active, active['stage'])}。")


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

    state["counters"]["help_streak"] = 0  # 每次新對話開頭，幫忙的邊際遞減重置
    # 怒氣：10% 機率自然消氣，否則餘怒未消
    anger = rel.get("anger", 0)
    if anger > 0:
        if random.random() < 0.10:
            rel["anger"] = 0
            briefing.append("【消氣了】她自己想通、氣消了——但別得寸進尺。")
        else:
            if anger >= 40:
                rel["mood"] = "生氣"
            grade = _persona_grade(state["persona"])
            limit = ANGER_THRESHOLD.get(grade, 9)
            strikes = state["counters"].get("anger_strikes", 0)
            briefing.append(
                f"💢【餘怒未消】上次的氣還沒消（怒氣 {anger}/100；惹怒紀錄 {strikes}/{limit}）。"
                "請演出她臭臉/冷淡/翻舊帳，甚至主動繼續吵；要 `interact sweet` 道歉安撫才會消。")
    _apply_decay(state, cfg, briefing)
    if not state["flags"].get("affair"):
        _advance_rival(state, cfg, briefing)
    # 此刻作息：依時區的真實時間推斷她正在幹嘛
    now = now_dt()
    rn = _routine_now(state["persona"], now)
    if rn:
        act, sleeping, react = rn
        wname = "一二三四五六日"[now.weekday()]
        line = f"【此刻】現在 {now.strftime('%H:%M')}（週{wname}），她{act}。"
        if sleeping:
            line += (f" 你這時候敲她等於把她吵醒——被吵醒的反應：{react}。"
                     "請演出剛被挖起來的樣子（迷糊/惱/撒嬌依個性），不是精神奕奕。")
        else:
            line += "請把這個情境融入她的回覆（上班忙就回得短或偷偷回、休息時才有空閒聊）。"
        briefing.append(line)
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
    ctr = state["counters"]
    note = ""
    # 強人所難：連續逼她做不來/討厭的事，好感急遽下滑（每多一次加重）
    if q == "pester":
        streak = ctr.get("overask_streak", 0) + 1
        ctr["overask_streak"] = streak
        ctr["help_streak"] = 0
        da -= 5 * (streak - 1)          # 1次-10、2次-15、3次-20…
        ds -= 2 * (streak - 1)
        if streak >= 3:
            note = (f"\n（你已經連續第 {streak} 次硬逼她——她真的火了，"
                    "好感正在崩，再下去恐影響關係穩定。哄她請改用 `interact sweet`。）")
        else:
            note = f"\n（強人所難第 {streak} 次：她不爽了，再逼下去掉更兇。）"
    elif q == "help":
        # 她盡心幫了你的忙：被依賴的甜→好感升；越深的關係越開心，但一直使喚會邊際遞減
        idx = stage_index(rel["stage"])
        base = {0: 1, 1: 1, 2: 2, 3: 3, 4: 3, 5: 4}.get(min(idx, 5), 2)
        hs = ctr.get("help_streak", 0)
        da = max(0, base - hs)          # 同一輪連續使喚：邊際遞減
        ds = 1 if idx >= 3 else 0       # 戀人以上，被依賴也累積安全感
        liked = getattr(args, "liked", False)
        if liked and da > 0:
            da += 2                     # 剛好是她喜歡/拿手的事 → 做得更起勁
        ctr["help_streak"] = hs + 1
        ctr["overask_streak"] = 0
        if idx >= 4 and da > 0:
            mood = "開心"
        if da == 0:
            note = "\n（你最近一直使喚她，這次幫忙她已經無感了——換個方式對她好一點吧。）"
        else:
            extra = "（剛好是她拿手/喜歡的，她做得特別起勁）" if liked else ""
            note = f"\n（她盡心幫了你，覺得被你依賴、有被需要的感覺，好感 +{da}{extra}。）"
    elif q in ("sweet", "good"):
        ctr["overask_streak"] = 0       # 哄好了就重置連擊
        ctr["help_streak"] = 0
    else:
        ctr["help_streak"] = 0
    # ── 怒氣系統：惹怒累積（達稀有度門檻→引爆）、安撫消氣 ──
    if q in ANGER_GAIN:
        rel["anger"] = clamp(rel.get("anger", 0) + ANGER_GAIN[q])
        strikes = ctr.get("anger_strikes", 0) + 1
        ctr["anger_strikes"] = strikes
        grade = _persona_grade(state["persona"])
        limit = ANGER_THRESHOLD.get(grade, 9)
        if strikes >= limit:
            blow = _anger_blowup(state, cfg)
            if not state.get("active"):
                return f"互動（{q}）：{blow}"
            note += blow
        else:
            note += (f"\n（怒氣 {rel['anger']}/100；惹怒紀錄 {strikes}/{limit}"
                     f"（{grade} 級脾氣）——到達上限會出大事。）")
    elif q in ("sweet", "good"):
        prev = rel.get("anger", 0)
        if prev > 0:
            rel["anger"] = max(0, prev - (50 if q == "sweet" else 25))
            if rel["anger"] == 0:
                if q == "sweet" and ctr.get("anger_strikes", 0) > 0:
                    ctr["anger_strikes"] -= 1
                    note += "\n（她消氣了。誠懇的道歉有用——惹怒紀錄也消了一筆。）"
                else:
                    note += "\n（她氣消了。）"
            else:
                note += f"\n（怒氣降到 {rel['anger']}/100，她還在悶氣，請繼續哄。）"
    rel["affinity"] = clamp(rel["affinity"] + da)
    rel["trust_security"] = clamp(rel["trust_security"] + ds)
    if mood:
        rel["mood"] = mood
    elif q in ("sweet", "good") and rel["mood"] in ("低落", "不安"):
        rel["mood"] = "普通"
    state["counters"]["interaction_count"] += 1
    state["counters"]["last_interaction_at"] = now_dt().strftime("%Y-%m-%dT%H:%M:%S")
    # 原諒出軌：sweet 互動可逐步修復並清旗標（離開結局門檻更高）
    if state["flags"].get("affair") and q == "sweet":
        loyalty = state["persona"].get("loyalty", 60)
        if state["flags"].get("leaving"):
            # 她已決定離開——需把安全感重建到很高才挽回得了
            if rel["trust_security"] >= 75:
                state["flags"]["affair"] = False
                state["flags"]["leaving"] = False
                state["pending_events"] = [e for e in state["pending_events"]
                                           if e.get("chain") != "rival"]
                add_milestone(state, "挽回", "在你拚命的真心下，她最終沒有離開，留了下來。")
                note = "\n（你把她從離開的邊緣拉了回來；但這道疤永遠留在記憶裡。）"
            else:
                note = ("\n（她心已飄向對方，光是甜蜜還不夠——安全感要重建到 75 以上才挽回得了，"
                        f"目前 {rel['trust_security']}。）")
        elif rel["trust_security"] >= 55:
            state["flags"]["affair"] = False
            # 忠誠太低 → 藕斷絲連，情敵不會真正消失（長期關係/NTR）
            if loyalty < 35:
                add_milestone(state, "原諒", "你選擇原諒；她嘴上回到你身邊，但和對方仍藕斷絲連。")
                note = ("\n（出軌旗標清除，但她忠誠太低——情敵沒有真正退場，這段關係仍在暗處延續，"
                        "日後極可能再犯。）")
            else:
                state["pending_events"] = [e for e in state["pending_events"]
                                           if e.get("chain") != "rival"]
                add_milestone(state, "原諒", "你選擇原諒，她痛哭著回到你身邊，傷痕還在但願意重新開始。")
                note = "\n（出軌已被原諒、旗標清除，但這道疤會留在記憶裡。）"
        if not state["flags"].get("affair"):
            state["flags"]["caught_in_act"] = False
        if state.get("relationship", {}).get("affair_count"):
            note += f"（累計出軌 {rel['affair_count']} 次，再犯機率已升高。）"
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
    now = now_dt()
    rn = _routine_now(p, now)
    sleeping = bool(rn and rn[1])
    # 睡著時預設不主動傳訊（排程請挑她醒著的時段）；--force 則演成半夢半醒
    if sleeping and not getattr(args, "force", False):
        chrono = ((p.get("life") or {}).get("routine") or {}).get("chrono", "")
        return f"（{p['name']} 現在正在睡（{chrono}），不主動傳訊——排程請挑她醒著的時段。）"
    # 依此刻活動調整情境
    if sleeping:
        label, intent = "深夜", "睡不著、半夢半醒間想你，傳了句迷糊的訊息"
    elif rn and "工作" in rn[0]:
        label, intent = "偷閒", "上班/值班中偷閒傳一句——會說很忙但想你、晚點再好好聊"
    elif rn:
        intent = f"{intent}（她現在：{rn[0]}）"
    lines = [
        f"[主動訊息·{label}] 以 {p['name']}（{p['archetype']}）的身分，主動傳訊給對方。",
        f"  此刻 {now.strftime('%H:%M')}：{rn[0] if rn else '—'}。",
        f"  目的：{intent}。",
        f"  當前：{rel['stage']}｜好感 {rel['affinity']}｜安全感 {rel['trust_security']}｜心情 {rel['mood']}。",
        f"  稱呼用：{render_soul._address(rel['stage'], cfg)}；語氣依個性與心情。",
        f"  可帶到的生活：{_life_log(p)}",
    ]
    if rel.get("anger", 0) >= 40:
        lines.append(f"  💢 她還在生氣（怒氣 {rel['anger']}）：這則要冷淡/賭氣/翻舊帳，不是甜蜜示好。")
    elif rel["affinity"] >= 70:
        lines.append("  好感很高：可以直接表達想念/撒嬌。")
    elif rel["affinity"] < 40:
        lines.append("  好感偏低：語氣保留一點，或帶點「你最近是不是很忙」的試探。")
    for ev in state.get("pending_events", []):
        if ev.get("chain") == "rival" and ev.get("stage", 0) >= 2:
            lines.append(f"  ⚠ 可（不經意地）提到 {_rival_name(ev)} 又找她，觀察對方反應。")
            break
    return "\n".join(lines)


# ── 玩家對情敵的主導：吃醋警告 / 要她設界線 / 表達信任 ──────────
def cmd_rival(args, cfg):
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    rel, persona = state["relationship"], state["persona"]
    active = next((e for e in state.get("pending_events", []) if e.get("chain") == "rival"), None)
    if not active:
        return "目前沒有情敵在糾纏她，不用緊張。"
    name = _rival_name(active)
    act = args.action

    if act == "warn":
        rel["trust_security"] = clamp(rel["trust_security"] + 8)
        active["stage"] = max(0, active.get("stage", 0) - 1)
        if persona.get("jealousy", 50) < 35:
            rel["affinity"] = clamp(rel["affinity"] - 3)
            msg = (f"你出面警告 {name}、宣示主權。她嫌你管太多、不太需要你出頭（好感-3），"
                   "但心底其實有點被在乎到（安全感+8，情敵退一步）。")
        else:
            msg = (f"你出面警告 {name}、宣示主權。她心裡甜滋滋、覺得被你重視"
                   "（安全感+8，情敵退一步）。")
    elif act == "boundary":
        if rel["trust_security"] >= 45 and rel["affinity"] >= 45:
            state["pending_events"] = [e for e in state["pending_events"] if e is not active]
            rel["trust_security"] = clamp(rel["trust_security"] + 10)
            rel["mood"] = "開心"
            add_milestone(state, "劃清界線", f"她為你和 {_rival_label(active)} 劃清了界線。")
            msg = (f"你請她和 {name} 保持距離。她夠在乎你、也有安全感，於是答應了，"
                   "主動和對方劃清界線（安全感+10，情敵退場）。")
        else:
            rel["trust_security"] = clamp(rel["trust_security"] + 3)
            msg = (f"你請她和 {name} 保持距離。但她現在對你們沒把握，反應為難、敷衍"
                   "（只 +3，情敵仍在）——先把好感/安全感養起來再要求。")
    elif act == "trust":
        wavering_risk = active.get("stage", 0) >= 2 and rel["trust_security"] < 45
        rel["trust_security"] = clamp(rel["trust_security"] + 5)
        if wavering_risk:
            active["stage"] = min(3, active.get("stage", 0) + 1)
            msg = (f"你說你相信她、不干涉。她感動，但她此刻正在動搖——你的大度被當成不夠在乎，"
                   f"反而把她往 {name} 推了一步（風險！）。")
        else:
            if rel["mood"] in ("不安", "低落"):
                rel["mood"] = "普通"
            msg = "你說你相信她、不干涉。她很感動，覺得被尊重，更想對你忠誠（安全感+5）。"
    else:
        return "用法：rival warn|boundary|trust"

    still = active in state.get("pending_events", [])
    save_state(state)
    write_soul(state, cfg)
    tail = (f"情敵 {name} 階段 {active.get('stage')}/3" if still else f"情敵 {name} 已退場")
    return (msg + f"\n（現況：安全感 {rel['trust_security']}、好感 {rel['affinity']}、{tail}。"
            "請以她的個性把上面的反應演出來。）")


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
    grade = _persona_grade(p)
    limit = ANGER_THRESHOLD.get(grade, 9)
    out = [
        f"● {p['name']}（{p['gender']}/{p['age']}/{p['archetype']}）｜稀有度 {grade}",
        f"  階段：{rel['stage']}｜好感 {rel['affinity']}/100｜安全感 {rel['trust_security']}/100",
        f"  心情：{rel['mood']}｜親密度 {rel.get('intimacy_level',0)}/5｜主動度 {p['proactivity']}｜忠誠 {p.get('loyalty',60)}",
        f"  怒氣：{rel.get('anger',0)}/100｜惹怒紀錄 {c.get('anger_strikes',0)}/{limit}（{grade} 級脾氣，達上限會出大事）",
        f"  互動 {c['interaction_count']} 次｜在本階段 {days_between(c.get('stage_entered_at', c['started_at']))} 天",
    ]
    idx = stage_index(rel["stage"])
    if idx < len(STAGES) - 1:
        nxt = STAGES[idx + 1]
        ok, why = _eligible(state, cfg, nxt)
        out.append(f"  下一步「{nxt}」：{'✓ 可推進' if ok else why}")
    if state["flags"].get("caught_in_act"):
        out.append("  🔥 你當場撞見她和情敵正在交配（變本加厲）：見 SOUL『現在的危機』。")
    if state["flags"].get("leaving"):
        out.append("  💔 她正準備為情敵離開你：需 interact sweet 把安全感拉到 75↑ 才挽回，否則只能分手。")
    elif state["flags"].get("affair"):
        out.append("  ⚠ 出軌旗標亮起：需原諒（interact sweet 重建≥55）或分手。")
    if rel.get("affair_count"):
        out.append(f"  出軌前科：{rel['affair_count']} 次（再犯機率已升高）")
    evs = [e for e in state.get("pending_events", []) if e.get("chain") == "rival"]
    if evs:
        e = evs[0]
        out.append(f"  情敵：{_rival_label(e)} 魅力{e.get('allure','?')}｜階段 {e['stage']}/3")
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
        elif v.isdigit() and k != "img_tag_avatar":  # 代號保留字串（如 "01" 的前導零）
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
    sp.add_argument("--gender", choices=["女", "男", "雙性"], default=None)
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("checkin")
    sp.add_argument("--seed", type=int, default=None)

    sp = sub.add_parser("interact")
    sp.add_argument("quality", choices=list(INTERACT_DELTA))
    sp.add_argument("--liked", action="store_true",
                    help="(配合 help) 這次任務剛好是她喜歡/拿手的，好感加碼")

    sub.add_parser("advance").add_argument("--force", action="store_true")
    sub.add_parser("regress")

    sp = sub.add_parser("remember")
    sp.add_argument("note", help="要記住的事（玩家偏好/約定/聊過的事/綽號…）")

    sp = sub.add_parser("propose")
    sp.add_argument("--by", choices=["user", "persona"], default="user")
    sp.add_argument("--to", required=True, choices=list(STAGE_THRESHOLDS))

    sub.add_parser("intimacy")

    sp = sub.add_parser("rival")
    sp.add_argument("action", choices=["warn", "boundary", "trust"])

    sp = sub.add_parser("cron-msg")
    sp.add_argument("--slot", choices=["morning", "noon", "evening", "night"], default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--force", action="store_true", help="即使她在睡也照發（演成半夢半醒）")

    sp = sub.add_parser("config")
    sp.add_argument("action", choices=["show", "set"])
    sp.add_argument("kv", nargs="?", default=None)
    return ap


DISPATCH = {
    "status": cmd_status, "newpersona": cmd_newpersona, "restore": cmd_restore,
    "rerender": cmd_rerender,
    "checkin": cmd_checkin, "interact": cmd_interact, "advance": cmd_advance,
    "regress": cmd_regress, "propose": cmd_propose, "intimacy": cmd_intimacy,
    "rival": cmd_rival, "remember": cmd_remember,
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
