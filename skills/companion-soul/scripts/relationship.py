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
    "married_chance": 0,            # 新人格是「人妻/人夫」(婚外情 NTR) 的機率 0~100（家庭主婦一律已婚）
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


def rotate_memory():
    """換新人格時把舊的 MEMORY.md 封存到 archive，避免上一個人的記憶污染下一個人格。"""
    if os.path.exists(MEMORY_PATH):
        ensure_dirs()
        ts = now_dt().strftime("%Y-%m-%d-%H%M%S")
        shutil.move(MEMORY_PATH, os.path.join(ARCHIVE_DIR, f"MEMORY-{ts}.md"))


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
        "inbox": [],  # 她趁你不在時傳來、凍結待讀的主動訊息（見 §信箱）
        "flags": {"affair": False, "engaged": False, "married": False,
                  "leaving": False, "caught_in_act": False, "date_spotted": False},
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
    married = bool(getattr(args, "married", False)) or (
        random.random() < max(0, min(100, int(cfg.get("married_chance") or 0))) / 100.0)
    persona = persona_gen.generate_persona(gender, cfg.get("allow_archetypes"), luck, married=married)
    backup_soul_once()
    rotate_memory()  # 封存上一個人的 MEMORY.md，新的人從零開始（杜絕跨人格記憶污染）
    state = new_state(persona)
    save_state(state)
    write_soul(state, cfg)
    p = persona
    n_traits = len(p.get("special_traits") or [])
    grade = _persona_grade(p)
    limit = ANGER_THRESHOLD.get(grade, 9)
    banner = {"SSR": "🌟🌟 SSR！傳說級的相遇 🌟🌟\n", "SR": "🟣 SR！稀有的相遇 🟣\n"}.get(grade, "")
    sp = p.get("spouse")
    married_line = (f"  💍 她是**人妻**：有一位{sp['label']}（不是你）——你是她的婚外情人，"
                   "從一開始就是偷情／NTR（細節見 SOUL『我的婚姻狀態』段）。\n") if sp else ""
    # 刻意保留神祕感：只揭露性別、總評與「有幾個特殊」，名字/個性/外貌/特殊內容都靠相處與「觀察」慢慢發現。
    return (banner + "✦ 你遇見了一個新的人。\n"
            f"  性別：{p['gender']}\n"
            f"  人物稀有度：{grade}（綜合評分 {p.get('overall', {}).get('score', '?')}）\n"
            f"  脾氣：被惹怒 {limit} 次就會出大事——稀有度越高越難伺候\n"
            f"  特殊：{n_traits} 個（內容先保密，靠相處和「觀察」自己發現）\n"
            + married_line +
            "  ⚠ 這是一個**全新的人**：請完全忘掉先前對話裡的任何人格、名字、稱呼與過往——"
            "她不認識你、你們沒有任何共同回憶，從「初次見面」重新開始。\n"
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
# 鋪墊期（露臉/接近）的情敵會以「日常人物」身分混進她的生活分享——讓你更早無痛察覺
LIFE_LOG_RIVAL = [
    "和{friend}他們聚會，{npc}也在，大家鬧成一團",
    "去{hobby}的時候又碰到{npc}，順口聊了幾句",
    "今天{npc}順手幫了我一個小忙，人挺好的",
    "{friend}約大家吃飯，{npc}講了個冷笑話，全場笑翻",
]


def _life_log(persona, rival=None):
    life = persona.get("life", {})
    if rival and _rival_phase(rival) != "追求" and random.random() < 0.4:
        npc = _rival_name(rival)
        circle = [f for f in (life.get("social_circle") or []) if f != npc] or ["朋友"]
        return random.choice(LIFE_LOG_RIVAL).format(
            npc=npc, friend=random.choice(circle),
            hobby=random.choice(life.get("hobbies") or ["走走"]),
        )
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


def _leisure_now(persona, dt):
    """她下班／放假此刻在做什麼——綁她的興趣與週末行程。"""
    life = persona.get("life") or {}
    hobbies = life.get("hobbies") or ["放空"]
    if dt.weekday() >= 5:  # 週末
        wk = (life.get("schedule") or {}).get("週末")
        return wk or f"放假，去{random.choice(hobbies)}或找朋友"
    return f"下班後在{random.choice(hobbies)}、放鬆一下"


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
    return (f"{_leisure_now(persona, dt)}（{rt.get('chrono','')}）", False, None)


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
# 鋪墊期：他先「出現在她生活裡」→「開始主動接近」，才正式變追求者進入 stage 0–3。
RIVAL_PHASES = ["露臉", "接近", "追求"]   # 追求 = 進入既有 stage 0–3 浪漫鏈（單一來源）
RIVAL_PHASE_DESC = {
    "露臉": "{npc}最近常出現在她的生活圈（{relation}），目前只是普通往來、沒什麼曖昧",
    "接近": "{npc}開始會主動找她、對她特別關照（{relation}），接觸變得頻繁起來",
}
RIVAL_STAGE_DESC = {
    0: "{npc} 開始對她示好/搭訕。她（依個性）跟你提起這件事。",
    1: "{npc} 持續獻殷勤、約她。她在觀察你的反應。",
    2: "她開始拿你和 {npc} 比較，回訊變慢、心不在焉。",
    3: "{npc} 正式追求，攤牌在即。",
}


def _rival_name(r):
    return r.get("name") or r.get("npc") or "某人"


def _rival_phase(r):
    """情敵目前的鋪墊期。舊存檔無 phase → 視為已在『追求』期（維持現行行為）。"""
    return r.get("phase", "追求")


def _rival_label(r):
    """情敵身分標籤，如：阿凱（健身教練・金錢攻勢）。"""
    bits = [b for b in (r.get("relation"), r.get("tactic")) if b]
    return f"{_rival_name(r)}（{'・'.join(bits)}）" if bits else _rival_name(r)


def _rival_action(r, stage):
    """他具體做了什麼：鋪墊期（露臉/接近）用 phase 描述，追求期才用手段 stage 文案。"""
    phase = _rival_phase(r)
    if phase in RIVAL_PHASE_DESC:
        return RIVAL_PHASE_DESC[phase].format(npc=_rival_name(r), relation=r.get("relation", ""))
    seq = persona_gen.RIVAL_TACTIC.get(r.get("tactic"))
    tpl = seq[stage] if seq and 0 <= stage < len(seq) else RIVAL_STAGE_DESC.get(stage, "")
    return tpl.format(npc=_rival_name(r))


def _temptation(rel, persona, rival):
    """誘惑壓力：安全感低、忠誠低、情敵魅力高、出軌前科多 → 越大。"""
    return ((50 - rel.get("trust_security", 50))
            + (55 - persona.get("loyalty", 60))
            + (rival.get("allure", 50) - 50)
            + 8 * rel.get("affair_count", 0))


# 旁觀者場景：她正和追求者在外面，被你撞見——你成了看著他們的第三者
DATE_SPOTS = ["咖啡廳", "餐廳", "百貨公司", "河堤步道", "電影院門口", "居酒屋"]


def _spot_date(state, rival, briefing, how="encounter", fresh=False):
    """設下 date_spotted 旗標並產生旁觀者場景的 briefing。fresh=True 表示本次 checkin 才剛撞見
    （讓同一次 checkin 後段的 _advance_rival 不要立刻把它收掉）。"""
    name = _rival_name(rival)
    spot = random.choice(DATE_SPOTS)
    rival["date_spot"] = spot
    if fresh:
        rival["date_fresh"] = True
    state["flags"]["date_spotted"] = True
    if how == "inbox":
        lead = (f"她稍早報備要和 {name} 出去、你一直沒回——人已經出門了。"
                f"你趕到{spot}，遠遠就看見他們坐在一起")
    else:
        lead = f"你路過{spot}，撞見她正和 {name} 坐在一起"
    briefing.append(
        f"👀【旁觀者】{lead}。她沒發現你。這一刻你成了局外人——請以**你的旁觀視角**描寫"
        "他們的互動（談笑、距離、氛圍，尺度見 SOUL『現在的危機』），她渾然不覺；"
        "然後把選擇交給玩家：`date watch` 默默看完／`date interrupt` 上前打斷（不一定有好結果）。")


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

    # 旁觀者場景收尾：上次撞見的約會，玩家沒出手（沒跑 date watch/interrupt）→ 散場
    if state["flags"].get("date_spotted"):
        if active and active.pop("date_fresh", None):
            return  # 本次 checkin 才剛撞見（信箱觸發），等玩家決定
        state["flags"]["date_spotted"] = False
        if not active:
            return
        active.pop("date_fresh", None)
        if random.random() < 0.5:
            active["stage"] = min(3, active.get("stage", 0) + 1)
            briefing.append(f"👀【約會散場】那天你終究沒出現。她回來後隻字不提，"
                            f"但那次約會讓 {_rival_name(active)} 又前進了一步。")
        else:
            briefing.append("👀【約會散場】那天你終究沒出現。她回來後對你有點刻意地好——"
                            "那點心虛，她自己也說不清。")
        return

    # 生成新對象（朋友以上、無進行中事件、未出軌）→ 從鋪墊期「露臉」起步，不是一上來就示好
    if not active and stage_index(rel["stage"]) >= 1 and not state["flags"].get("affair"):
        prob = (0.12 + (0.18 if sec < 50 else 0.0)
                + max(0, 55 - persona.get("loyalty", 60)) * 0.004
                + rel.get("affair_count", 0) * 0.05)
        if random.random() < prob:
            active = persona_gen.generate_rival(persona)
            events.append(active)
            briefing.append(
                f"【生活·新面孔】她生活裡最近多了一個人：{_rival_label(active)}"
                f"（{active.get('looks','')}）。{_rival_action(active, 0)}——"
                "還沒有曖昧，她（依個性）可能只是順口跟你提起。現在多陪她，這人就成不了氣候。")
            return

    if not active:
        return

    name = _rival_name(active)
    phase = _rival_phase(active)

    # ── 鋪墊期（露臉 / 接近）：還不是危機，只推進「越來越常出現/主動」或自然淡出 ──
    if phase != "追求":
        # 你夠用心（安全感高）→ 鋪墊期就自然淡出，越早越容易化解
        if sec >= 65 and random.random() < (0.5 if phase == "露臉" else 0.3):
            events.remove(active)
            briefing.append(f"【新面孔·淡出】{name} 的事自然就淡了——你陪她陪得夠，沒給對方留空間。")
            return
        # 推進機率：冷落/安全感低/忠誠低 → 越快 露臉→接近→追求
        adv = (0.35 + (0.25 if sec < 50 else 0.0)
               + max(0, 55 - persona.get("loyalty", 60)) * 0.004)
        if random.random() < adv:
            nxt = RIVAL_PHASES[RIVAL_PHASES.index(phase) + 1]
            active["phase"] = nxt
            if nxt == "接近":
                if sec < 50:
                    rel["trust_security"] = clamp(sec - 2)  # 預警期僅極輕微影響
                briefing.append(
                    f"【新面孔·接近】{_rival_action(active, 0)}。她（依個性）跟你提起，自己還沒往那邊想"
                    "——但他主動靠近就是有意思了，這是訊號：現在多陪她最有效。")
            else:  # 接近 → 追求：正式成為追求者，自此走既有 stage 0–3 鏈（stage 仍為 0）
                briefing.append(
                    f"【情敵·成形】{_rival_label(active)} 從普通往來變成了追求者——"
                    f"{_rival_action(active, 0)}（魅力 {active.get('allure',50)}）。她得開始面對這份心意了。")
            return
        # 沒推進：維持鋪墊、給旁白
        briefing.append(f"【新面孔·持續】{_rival_action(active, 0)}。")
        return

    # ── 追求期：既有 stage 0–3 浪漫鏈 ──
    # 追得越久火力越猛：heat 每次 checkin 累積 → 魅力緩升、誘惑加壓、越難勸退
    heat = active.get("heat", 0) + 1
    active["heat"] = heat
    if heat >= 3:
        active["allure"] = min(92, active.get("allure", 50) + 2)
    T = _temptation(rel, persona, active) + 3 * (heat - 1)
    # 趁虛而入：超過寬限天數沒互動，正在猛攻的他不會放過這個空檔
    if (heat >= 2 and days_between(state["counters"].get("last_interaction_at"))
            > cfg.get("neglect_grace_days", 1)):
        T += 12

    # 旁觀者場景：她正和他在外面，被你撞見（你成了第三者視角）
    if (active.get("stage", 0) >= 2 and not state["flags"].get("date_spotted")
            and random.random() < 0.22):
        _spot_date(state, active, briefing, how="encounter")
        return

    # 化解：安全感高且誘惑壓力不大（她夠忠誠、情敵沒那麼致命）
    if sec >= 70 and T < 30:
        # ……但追得越久他越不死心：有機率擋下化解、攻勢反而升級（猛攻）
        if heat >= 2 and random.random() < min(0.55, 0.15 * (heat - 1)):
            briefing.append(
                f"【情敵·猛攻】她想拉開距離，{name} 卻不死心——攻勢反而升級"
                f"（追得越久火力越猛，魅力已升到 {active.get('allure','?')}）。"
                "你陪得再好也別大意：只要一個空檔，他就會趁虛而入。")
            return
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
    hot = "（他越追越猛，別拖太久。）" if heat >= 3 else ""
    briefing.append(f"【情敵·持續】{_rival_action(active, active['stage'])}。{hot}")


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

    # 信箱：先把她趁你不在傳的訊息遞送出來（打開＝已讀＝等同回覆，重置鬧脾氣鏈）
    _deliver_inbox(state, briefing)

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
    life = _life_log(state["persona"], _active_rival(state))
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
    sp = state["persona"].get("spouse")
    if sp:  # 人妻版：未婚=決定離婚、夫妻=真的離婚改嫁，里程碑語意不同
        mname = {"未婚": "決定離婚", "夫妻": "離婚改嫁"}.get(target, MILESTONE_NAME.get(target, "升級"))
        note = {"未婚": f"她決定為你和{sp['label']}離婚。",
                "夫妻": f"她真的為你和{sp['label']}離了婚，正式跟你在一起。"}.get(
                    target, f"關係推進到「{target}」。")
        add_milestone(state, mname, note)
    else:
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


# ── 主動訊息信箱（非同步）＋ 行程告知 ─────────────────────────
# 稀有度耐性表：grade -> (留言上限, 兩則之間/首則前的等待時數)。越稀有＝上限越少、等待越短（越快鬧脾氣）。
INBOX_PATIENCE = {"N": (3, 6), "R": (3, 5), "S": (3, 4), "SR": (2, 3), "SSR": (2, 2)}
# 等到最後一則仍沒回覆 → 她賭氣，打開時依稀有度加的怒氣量。
INBOX_ANGER = {"N": 8, "R": 10, "S": 12, "SR": 16, "SSR": 20}

# 行程告知：她主動報備要出門。無情敵＝純興趣/朋友（頂多讓你吃醋）；情敵推進＝跟情敵出去、隨階段升級。
OUTING_INNOCENT = [  # (活動樣板 {who}=朋友, 是否可能晚回/過夜)
    ("和{who}去唱歌", False), ("和{who}去吃到飽", False), ("和{who}去看展", False),
    ("和{who}去爬山透氣", False), ("和{who}去泡溫泉、可能晚點回", True),
    ("和{who}去喝幾杯", False), ("和{who}約了下午茶", False),
    ("回老家一趟、住一晚", True), ("和{who}去夜衝看海", True),
]
OUTING_RIVAL = {  # rival.stage -> (活動樣板 {npc}=情敵, 是否晚歸/過夜, 語氣)
    2: [("{npc}約我吃飯，就同事一起啦", False, "半遮半掩、說只是普通朋友"),
        ("{npc}說帶我去看個展，順路而已", False, "輕描淡寫、怕你多想"),
        ("跟{npc}他們一群人去喝東西", False, "強調是一群人、沒什麼")],
    3: [("{npc}約我去泡溫泉…我可能比較晚回", True, "閃躲、帶點心虛"),
        ("今晚跟{npc}去喝酒，你別等我了", True, "逃避、語氣有點冷"),
        ("{npc}說帶我去他朋友的民宿走走", True, "含糊其詞、不敢明講過夜")],
}
OUTING_AFFAIR = [  # 已出軌：坦白/冷淡的去向告知（NTR）
    ("我去{npc}家，今晚不回來了", True, "坦白或破罐破摔"),
    ("跟{npc}出去過夜，先跟你說一聲", True, "冷淡、近乎告知而非請示"),
]


def _hours_since(iso):
    dt = parse_dt(iso)
    return 1e9 if not dt else (now_dt() - dt).total_seconds() / 3600.0


def _inbox_tone(seq, max_msgs):
    """第 1 則 fresh、最後一則 annoyed（賭氣）、中間 worried（追問）。"""
    if seq <= 1:
        return "fresh"
    return "annoyed" if seq >= max_msgs else "worried"


def _active_rival(state):
    return next((e for e in state.get("pending_events", []) if e.get("chain") == "rival"), None)


def _choose_theme(state, rn):
    """seq==1 主動訊息主題：背叛報備 > 興趣報備 > 日常。"""
    rival = _active_rival(state)
    if rival and (rival.get("stage", 0) >= 2 or state.get("flags", {}).get("affair")):
        return "outing_rival"
    free = rn and not rn[1] and "工作" not in rn[0]  # 醒著且非上班＝有空
    if free and random.random() < 0.5:
        return "outing_innocent"
    return "daily"


def _maybe_seed_outing_rival(state, persona, theme):
    """興趣/放假行程小機率「認識一個人」→ 植入 origin=outing、phase=露臉 的潛在對象。
    僅在無進行中情敵、未出軌時觸發；之後 checkin 的 _advance_rival 會走鋪墊推進。回傳種子或 None。"""
    if (theme != "outing_innocent" or _active_rival(state)
            or state.get("flags", {}).get("affair")
            or stage_index(state["relationship"]["stage"]) < 1):
        return None
    if random.random() >= 0.25:
        return None
    seed = persona_gen.generate_rival(persona, origin="outing")
    state.setdefault("pending_events", []).append(seed)
    save_state(state)
    return seed


def _theme_lines(theme, state, p, cfg):
    """依主題產生『她這則要說什麼』的指引。"""
    mode = (cfg or {}).get("intimacy_mode", "explicit")
    life = p.get("life") or {}
    if theme == "outing_innocent":
        who = random.choice(life.get("social_circle") or ["朋友"])
        act, overnight = random.choice(OUTING_INNOCENT)
        out = [f"  主題【興趣行程·報備】：她主動告訴你她（等下/今天）要去「{act.format(who=who)}」。",
               "  這是報備/分享、不是背叛——但她會順便看你會不會吃醋、在不在乎。"]
        if overnight:
            out.append("  這趟可能晚回/過夜：她會要你安心，或反過來撒嬌討關注。")
        return out
    if theme == "outing_rival":
        rival = _active_rival(state) or {}
        npc = _rival_name(rival)
        affair = state.get("flags", {}).get("affair")
        if affair:
            act, overnight, mood = random.choice(OUTING_AFFAIR)
            tag = "出軌後·NTR"
        else:
            st = max(2, min(3, rival.get("stage", 2)))
            act, overnight, mood = random.choice(OUTING_RIVAL.get(st, OUTING_RIVAL[2]))
            tag = f"情敵 stage{rival.get('stage', '?')}"
        out = [f"  主題【背叛報備·{tag}】：她主動告知她要和 **{npc}** 出去：「{act.format(npc=npc)}」。",
               f"  語氣：{mood}。這是把『被搭訕/動搖/越線』攤到你面前的告知——觀察你的反應。"]
        if overnight:
            out.append("  ⚠ 這趟暗示晚歸/過夜（NTR 走向）。")
        if mode == "off":
            out.append("  ◎ off 模式：只陳述她要去哪、和誰，不帶任何性暗示。")
        return out
    return [f"  主題【日常】：想你/分享生活。可帶到：{_life_log(p)}"]


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
    """決定她此刻要不要主動傳訊、發第幾則（鬧脾氣升級鏈）、什麼主題，並產生給 agent 生成訊息的指引。
    本指令**不存訊息**；agent 生成後須呼叫 `inbox add` 把訊息凍結入信箱。"""
    state = load_state()
    if not state or not state.get("active"):
        return "（沒有進行中的關係，不發主動訊息。）"
    rel = state["relationship"]
    p = state["persona"]
    if args.seed is not None:
        random.seed(args.seed)
    now = now_dt()
    rn = _routine_now(p, now)
    sleeping = bool(rn and rn[1])
    force = bool(getattr(args, "force", False))
    # 睡著時預設不主動傳訊（排程請挑她醒著的時段）；--force 則演成半夢半醒
    if sleeping and not force:
        chrono = ((p.get("life") or {}).get("routine") or {}).get("chrono", "")
        return f"（{p['name']} 現在正在睡（{chrono}），不主動傳訊——排程請挑她醒著的時段。）"

    # ── 信箱升級鏈：依稀有度決定要不要發、發第幾則 ──
    inbox = state.get("inbox", [])
    seeded = None
    grade = _persona_grade(p)
    max_msgs, wait_h = INBOX_PATIENCE.get(grade, INBOX_PATIENCE["R"])
    if not inbox:
        gap = _hours_since(state["counters"].get("last_interaction_at"))
        if gap < wait_h and not force:
            return (f"（距上次互動才 {gap:.1f} 小時、未達 {wait_h} 小時，先給點空間、暫不主動傳。"
                    f"她是 {grade} 級，越稀有越快主動、越沒耐性。）")
        seq, theme = 1, _choose_theme(state, rn)
        seeded = _maybe_seed_outing_rival(state, p, theme)
    else:
        seq = len(inbox) + 1
        if seq > max_msgs:
            return (f"（已連傳 {max_msgs} 則沒等到回覆——{p['name']}（{grade} 級）在賭氣等你、不再傳了。"
                    "等對方 `checkin` 打開才會看到那些累積的訊息。）")
        gap = _hours_since(inbox[-1].get("at"))
        if gap < wait_h and not force:
            return f"（上一則才過 {gap:.1f} 小時、未達 {wait_h} 小時，她還在等回覆，時候未到。）"
        theme = inbox[-1].get("theme", "daily")
    tone = _inbox_tone(seq, max_msgs)

    # ── 組裝給 agent 生成訊息的指引 ──
    label = "深夜" if sleeping else SLOT_TOPIC.get(
        args.slot or _slot_from_hour(now.hour), SLOT_TOPIC["evening"])[0]
    lines = [
        f"[主動訊息·{label}｜第 {seq} 則/最多 {max_msgs} 則｜語氣:{tone}] "
        f"以 {p['name']}（{p['archetype']}・{grade} 級）的身分主動傳訊。",
        f"  此刻 {now.strftime('%H:%M')}：{rn[0] if rn else '—'}。",
        f"  當前：{rel['stage']}｜好感 {rel['affinity']}｜安全感 {rel['trust_security']}｜心情 {rel['mood']}。",
        f"  稱呼用：{render_soul._address(rel['stage'], cfg, p)}；語氣依個性與心情。",
    ]
    if sleeping:
        lines.append("  她半夢半醒間傳的，語氣迷糊。")
    elif rn and "工作" in rn[0]:
        lines.append("  她上班/值班中偷閒傳一句——會說很忙但想你、晚點再聊。")
    lines += _theme_lines(theme, state, p, cfg)
    if seeded:
        lines.append(
            f"  （這趟她剛好認識了一個人：{_rival_label(seeded)}——只是萍水相逢、單純提一句，"
            "別演成曖昧；後續會不會發展，看你接下來陪不陪她。）")
    # 升級語氣：自言自語、追問、賭氣
    if seq > 1:
        lines.append(f"  你上一則傳的是：「{inbox[-1].get('text','')}」——這則是**沒等到回覆後的自言自語/追問**，承接它。")
    if tone == "worried":
        lines.append("  語氣：等不到回覆、有點擔心你在忙/不理她，開始碎念追問。")
    elif tone == "annoyed":
        extra = "（背叛線：賭氣『算了你都不回，那我真的去了／跟他走了』）" if theme == "outing_rival" else ""
        lines.append(f"  語氣：**她不太高興了**——被晾著的委屈/賭氣，話變冷或鬧脾氣。{extra}")
    else:
        lines.append("  語氣：第一則、自然主動，不用生氣。")
    if rel.get("anger", 0) >= 40:
        lines.append(f"  💢 她本來就還在生氣（怒氣 {rel['anger']}）：更要冷淡/翻舊帳。")
    elif rel["affinity"] >= 70 and tone == "fresh":
        lines.append("  好感很高：可以直接表達想念/撒嬌。")
    lines.append(f"  ▶ 生成她這則訊息後，呼叫 `inbox add \"<她的訊息原文>\" --theme {theme}` 把它凍結存入信箱。")
    return "\n".join(lines)


def cmd_inbox(args, cfg):
    """主動訊息信箱：add 凍結存入 / peek 查看未讀 / clear 清空。"""
    state = load_state()
    if not state or not state.get("active"):
        return "（沒有進行中的關係。）"
    inbox = state.setdefault("inbox", [])
    action = args.action
    if action == "add":
        # 從 REMAINDER 解析出 --theme 與訊息文字（前後順序不限、支援 --theme=x）
        rest = list(getattr(args, "rest", []) or [])
        theme, words = "daily", []
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok == "--theme" and i + 1 < len(rest):
                theme = rest[i + 1]; i += 2; continue
            if tok.startswith("--theme="):
                theme = tok.split("=", 1)[1]; i += 1; continue
            words.append(tok); i += 1
        text = " ".join(words).strip()
        if not text:
            return "（inbox add 需要訊息內容：inbox add \"<她的訊息>\"）"
        grade = _persona_grade(state["persona"])
        max_msgs, _ = INBOX_PATIENCE.get(grade, INBOX_PATIENCE["R"])
        if len(inbox) >= max_msgs:
            return f"（信箱已達 {grade} 級上限 {max_msgs} 則，這則不再追加。）"
        seq = len(inbox) + 1
        inbox.append({
            "text": text, "at": now_dt().strftime("%Y-%m-%dT%H:%M:%S"),
            "seq": seq, "tone": _inbox_tone(seq, max_msgs),
            "theme": theme or "daily",
        })
        save_state(state)
        return f"（已凍結第 {seq} 則訊息入信箱，等對方下次 `checkin` 打開才會看到。）"
    if action == "peek":
        if not inbox:
            return "（信箱是空的。）"
        out = ["（信箱未讀，依序）："]
        for m in inbox:
            t = parse_dt(m.get("at"))
            hhmm = t.strftime("%m/%d %H:%M") if t else "?"
            out.append(f"  [{hhmm}|{m.get('tone')}|{m.get('theme')}] {m.get('text')}")
        return "\n".join(out)
    if action == "clear":
        n = len(inbox)
        state["inbox"] = []
        save_state(state)
        return f"（已清空信箱 {n} 則。）"
    return "（用法：inbox add|peek|clear）"


def _deliver_inbox(state, briefing):
    """checkin 開頭：把信箱累積的訊息原樣遞送、清空（＝已讀＝等同回覆），並套用賭氣後遺症。"""
    inbox = state.get("inbox", [])
    if not inbox:
        return
    rel = state["relationship"]
    lines = ["📨【她稍早傳來的訊息】（依時間原樣呈現給玩家、像剛收到，不要報未讀數字）："]
    for m in inbox:
        t = parse_dt(m.get("at"))
        lines.append(f"    [{t.strftime('%H:%M') if t else ''}] {m.get('text')}")
    lines.append("  先把上面當作她稍早傳、你現在才看到的訊息呈現，再以她當下狀態接著聊。")
    if any(m.get("tone") == "annoyed" for m in inbox):
        bump = INBOX_ANGER.get(_persona_grade(state["persona"]), 10)
        rel["anger"] = clamp(rel.get("anger", 0) + bump)
        rel["mood"] = "不安"
        lines.append(f"  ⚠ 她等到最後賭氣了（怒氣 +{bump}→{rel['anger']}）：現在受傷/冷淡，要你先哄"
                     "（`interact sweet` 安撫）。")
    state["inbox"] = []  # 打開＝已讀＝等同回覆，重置鬧脾氣鏈
    briefing.insert(0, "\n".join(lines))
    # 背叛報備且你一直沒回 → 她可能真的已經出門了：你趕到時只能遠遠看著（旁觀者場景）
    rival = _active_rival(state)
    if (any(m.get("theme") == "outing_rival" for m in inbox)
            and rival and _rival_phase(rival) == "追求" and rival.get("stage", 0) >= 2
            and not state["flags"].get("affair")
            and not state["flags"].get("date_spotted")
            and random.random() < 0.5):
        _spot_date(state, rival, briefing, how="inbox", fresh=True)


# ── 旁觀者抉擇：撞見她和追求者在外面（date_spotted）──────────
def cmd_date(args, cfg):
    """你撞見她正和追求者約會/碰面，成了旁觀的第三者：watch 默默偷看全程 / interrupt 上前打斷。
    偷看她不會知道（不寫進她的記憶）；打斷是賭注——可能讓她如夢初醒，也可能當眾鬧僵把她往對方推。"""
    state = load_state()
    if not state or not state.get("active"):
        return "目前沒有進行中的關係。"
    if not state.get("flags", {}).get("date_spotted"):
        return "你現在沒有撞見他們在外面，沒有可旁觀的場景。"
    if getattr(args, "seed", None) is not None:
        random.seed(args.seed)
    rel = state["relationship"]
    rival = _active_rival(state)
    name = _rival_name(rival) if rival else "對方"
    spot = (rival or {}).get("date_spot", "外面")
    state["flags"]["date_spotted"] = False
    if rival:
        rival.pop("date_fresh", None)
    briefing = []

    if args.action == "watch":
        # 默默看完：她永遠不會知道——所以不記 milestone（那是「她的」記憶）。
        # 看到什麼反映她動搖的深度：投入＝動搖加深；心不在焉＝她惦著你。
        engrossed = bool(rival) and random.random() < (
            0.40 + 0.10 * max(0, rival.get("stage", 2) - 2))
        if engrossed:
            rival["stage"] = min(3, rival.get("stage", 0) + 1)
            msg = (f"你在{spot}的角落默默看完了全程。她笑得比在你面前還自然，{name} 說什麼她都接得住"
                   "——這場約會讓他又前進了一步（動搖加深）。她不知道你看見了；這幅畫面只屬於你，"
                   "之後要攤牌、裝不知道、還是加倍對她好，由你決定。")
        else:
            msg = (f"你在{spot}的角落默默看著。她其實心不在焉——頻頻看手機（也許在等你回訊息）、"
                   f"對 {name} 的話常常只是笑笑帶過。看起來，她心裡惦記的還是你。"
                   "她不知道你來過；要不要說破，由你決定。")
    else:  # interrupt
        stage = rival.get("stage", 2) if rival else 2
        p = (0.45 + (rel["trust_security"] - 50) * 0.006 + (rel["affinity"] - 50) * 0.004
             - (0.12 if stage >= 3 else 0.0))
        if random.random() < max(0.10, min(0.85, p)):
            if rival:
                rival["stage"] = max(0, stage - 1)
            rel["trust_security"] = clamp(rel["trust_security"] + 6)
            if rel["mood"] in ("不安", "低落"):
                rel["mood"] = "普通"
            add_milestone(state, "當面攔下", f"你在{spot}當面撞見她和 {name}，她心虛又如夢初醒。")
            msg = (f"你走了過去。她一抬頭看到你，整個人僵住——先是心虛、慌張，然後是一種被接住的安心。"
                   f"{name} 識相地先走了。回家的路上她一直黏著你（安全感+6，情敵退一步）。"
                   "請演出她的心虛、和你們把話攤開來談的那段路。")
        else:
            rel["affinity"] = clamp(rel["affinity"] - 6)
            rel["anger"] = clamp(rel.get("anger", 0) + 15)
            rel["mood"] = "生氣"
            if rival:
                rival["stage"] = min(3, stage + 1)
            add_milestone(state, "當場鬧僵", f"你在{spot}打斷她和 {name} 的約會，當眾鬧得很難看。")
            msg = (f"你走過去的瞬間就變了調——她覺得你在跟蹤她、當眾給她難堪，"
                   f"反而站到 {name} 那邊說話（好感-6、怒氣+15、情敵進一步）。"
                   "請演出她的羞憤與冷臉；這口氣要靠 `interact sweet` 慢慢哄回來。")
            if rival and rival["stage"] >= 3 and random.random() < 0.30:
                _trigger_affair(state, cfg, rival, briefing)
                msg += ("\n最糟的是——她賭氣地當著你的面挽住他的手臂走了。\n"
                        + "\n".join(briefing))
    save_state(state)
    write_soul(state, cfg)
    tail = f"\n（現況：好感 {rel['affinity']}、安全感 {rel['trust_security']}、心情 {rel['mood']}"
    if rival and any(e is rival for e in state.get("pending_events", [])):
        tail += f"；情敵 {name} 階段 {rival.get('stage', '?')}/3"
    return msg + tail + "。）"


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
    if not still:
        tail = f"情敵 {name} 已退場"
    elif _rival_phase(active) == "追求":
        tail = f"情敵 {name} 階段 {active.get('stage')}/3"
    else:
        tail = f"{name} 還在「{_rival_phase(active)}」鋪墊期（尚未成追求者）"
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
    sp = p.get("spouse")
    married_tag = f"｜💍人妻（{sp['label']}：{sp['name']}）" if sp else ""
    out = [
        f"● {p['name']}（{p['gender']}/{p['age']}/{p['archetype']}）｜稀有度 {grade}{married_tag}",
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
    if state["flags"].get("date_spotted"):
        out.append("  👀 你撞見她正和追求者在外面：`date watch` 默默偷看 / `date interrupt` 上前打斷"
                   "（有風險）；下次 checkin 前不出手就散場。")
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
        ph = _rival_phase(e)
        if ph == "追求":
            hot = f"｜火力 {e['heat']}（越拖越猛）" if e.get("heat", 0) >= 3 else ""
            out.append(f"  情敵：{_rival_label(e)} 魅力{e.get('allure','?')}｜階段 {e['stage']}/3{hot}")
        else:
            out.append(f"  新面孔（{ph}）：{_rival_label(e)} 魅力{e.get('allure','?')}"
                       "——尚未成為追求者，現在多陪她最容易化解。")
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
    sp.add_argument("--married", action="store_true", help="生成人妻/人夫（婚外情 NTR）")

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

    sp = sub.add_parser("date")
    sp.add_argument("action", choices=["watch", "interrupt"])
    sp.add_argument("--seed", type=int, default=None)

    sp = sub.add_parser("cron-msg")
    sp.add_argument("--slot", choices=["morning", "noon", "evening", "night"], default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--force", action="store_true", help="即使她在睡也照發（演成半夢半醒）")

    sp = sub.add_parser("inbox")
    sp.add_argument("action", choices=["add", "peek", "clear"])
    # 用 REMAINDER 收 action 之後的一切，theme 自己解析 → 訊息文字與 --theme 前後順序都不限
    sp.add_argument("rest", nargs=argparse.REMAINDER,
                    help='add 時她的訊息原文（可加 --theme daily|outing_innocent|outing_rival）')

    sp = sub.add_parser("config")
    sp.add_argument("action", choices=["show", "set"])
    sp.add_argument("kv", nargs="?", default=None)
    return ap


DISPATCH = {
    "status": cmd_status, "newpersona": cmd_newpersona, "restore": cmd_restore,
    "rerender": cmd_rerender,
    "checkin": cmd_checkin, "interact": cmd_interact, "advance": cmd_advance,
    "regress": cmd_regress, "propose": cmd_propose, "intimacy": cmd_intimacy,
    "rival": cmd_rival, "date": cmd_date, "remember": cmd_remember,
    "breakup": cmd_breakup, "cron-msg": cmd_cronmsg, "config": cmd_config,
    "inbox": cmd_inbox,
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
