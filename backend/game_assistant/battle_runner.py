"""按「用户指定配队」的动作流跑一局：前置校验 → 点击 → 后置校验 → 失败即停。

分工：
- battle_plan 决定点什么、按什么顺序；
- battle_vision 判断现在是哪个界面 / 手牌是什么；
- device_link 把截图与点击交给 FGO-py（执行层）；
- 本模块把它们串成状态机，任何判据不成立就 ExecutionAbort，绝不"感觉差不多"继续点。

每个动作的判据 = 前后两次画面判定 + 一次区域变化量：
  期望前态不符 -> 停；点击后区域没变 -> 重试一次，仍没变就停；期望后态不符 -> 停。
证据（每步截图与数值）落到 GAME_ASSISTANT_EXECUTION_DIR/runs/<run_id>/。
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config

from . import battle_plan as plan_mod
from . import battle_vision as vision
from .device_lease import DeviceLease
from .device_link import DeviceLink, DeviceLinkError

SETTLE_SECONDS = 1.6
WAIT_POLL_SECONDS = 2.0
# 60 -> 90（2026-10-14）：加了"非战斗画面必须静止"的判据后，等待要连吃 10 帧以上演出
# 才判结束，实测单次等待已到 42.6 秒，60 秒余量太薄。
WAIT_TIMEOUT_SECONDS = 90.0
TAP_RETRY = 1
POST_POLL_TRIES = 4
POST_POLL_WAIT = 1.2
# 过场帧（换面黑帧 / 结算渐入 / 转场白屏）那一刻既不能说"点成了"也不能说"没点到"。
# 2026-10-14 实测：3T 的「攻击」点下去后连拍到一张 2.7 KB 的全黑帧（换面瞬间），
# 原来的 3 次轮询用完就被判成"期望后态 card_select，实际 other"而误停。现在过场帧
# **不占轮询预算**，最多再等这么多秒；等满还看不出来才给结论（重跑会重复点击，是危险
# 方向，所以宁可多等）。
POST_POLL_TRANSITION_SECONDS = 12.0

# 回合间等待的判据（2026-10-14 用磁盘上的历史帧定的口径）：
#   * 主战斗界面**连续确认 2 次**才算"下一回合已就绪"；
#   * 非战斗画面必须**静下来**（相邻两帧变化 ≤ WAIT_STILL_DELTA）才算一帧"打完了"的
#     证据——宝具演出的中间帧两两之间变化 0.93-1.0，真结算页几乎是静止的。
# 为什么加这条：2026-10-13 那次收尾成功时，被判成"连续 3 帧非战斗画面"的其实**全是
# 演出帧**（相邻变化 0.93 / 0.997），只是那局恰好真打完了才没出事；同样的连出 3 帧
# 出现在第 1/2 回合就会误判成"本局结束"，接着按结算页坐标去点，可能点进选牌界面。
WAIT_STILL_DELTA = 0.35
WAIT_CONFIRM_FRAMES = 2
WAIT_OVER_FRAMES = 3

# 选完助战之后游戏会**直接进本**（2026-10-14 实测：没有单独的「出击」确认步），所以
# 这里等的是"画面变成主战斗界面"。加载要几秒，给足时间；超时即 fail-stop。
SUPPORT_ENTER_SECONDS = 40.0
SUPPORT_ENTER_WAIT = 2.0
# 助战列表从「连续出击」点完到画出来要几秒（中间可能先看到加载 / 白屏）。这里只多等
# 几次、不点击——等不到才算"不是助战选择屏"。
SUPPORT_LIST_TRIES = 5
SUPPORT_LIST_WAIT = 2.0
# 「队伍确认」屏右下角的「开始任务」（登记在 templates/buttons/start_quest.*）。
# 从地图手动进本时，选完助战会**回到这一屏**，还要再点一次才真正进本并扣 AP。
START_QUEST_BUTTON = "start_quest"
# 每日任务地图上的关卡卡片（登记在 templates/buttons/daily_quest_card.*）——
# 冷启动（--enter-quest）点它开刷。
ENTER_QUEST_CARD = "daily_quest_card"
# 冠位戴冠战的关卡列表：那一关的「消耗 AP 40」框（`templates/buttons/grand_assassin_card.*`，
# 2026-10-17 从用户停在列表时的真机帧登记）。点它 → 直接进「助战选择」。
# 为什么单独一个模板：冠位战的入口不在"迦勒底之门 → 每日任务 → 关卡卡片"那条线上，
# 以前必须人手动点进去；有了它，从关卡列表也能一键开刷。
GRAND_QUEST_CARD = "grand_assassin_card"
# 冠位战关卡卡片点开后，游戏先弹「是否挑战该关卡？」（AP 消耗 40 / 当前 AP），
# 右下按钮是「任务开始」；点它之后才到「助战选择」。
GRAND_QUEST_CONFIRM = "grand_quest_confirm"
# 「上次执行」角标（`templates/buttons/last_executed.*`，2026-10-17 用户圈注）：它标在**最近刷过
# 的那一关**所在行上。拿它和关卡卡片做**同行校验** —— 两者不在同一行，说明这份 runbook 指的
# 关卡不是"你最近在刷的那关"，此时停手比点下去安全。
GRAND_LAST_EXECUTED = "last_executed"
GRAND_LAST_EXECUTED_MAX_DX = 320   # 实测同一行：角标中心 (655,179) ↔ 卡片中心 (857,255) → Δ(202,76)
GRAND_LAST_EXECUTED_MAX_DY = 110   # 行距约 200；下一行的角标 Δy≈124，必须被这条挡住
# 冷启动的导航链（用户 2026-10-14 给的实机路径：迦勒底之门 → 每日任务 → 关卡卡片）。
# 每一步都要在模板自证通过时才点；已经在每日任务屏或战斗里就自动跳过前面几跳。
ENTER_QUEST_NAV: tuple[tuple[str, str], ...] = (
    ("chaldea_gate", "主界面：迦勒底之门"),
    ("daily_quest_entry", "迦勒底之门：每日任务"),
)
CHALDEA_GATE_TITLE = "chaldea_gate_title"
DAILY_QUEST_TITLE = "daily_quest_title"
ENTER_QUEST_TRIES = 4
GATE_SCROLL_MAX = 6
GATE_SCROLL_STILL_DELTA = 0.01
GATE_SCROLL_STILL_TRIES = 2
# 冷启动弹窗：公告 ✕（可能连续两个）、连续登录奖励、倒计时登录、友情点数。
STARTUP_POPUPS: tuple[tuple[str, str], ...] = (
    ("announcement_close", "公告关闭"),
    ("login_bonus_close", "登录奖励关闭"),
    ("friend_points_close", "友情点数关闭"),
    ("master_mission_update_close", "御主任务更新关闭"),
)
STARTUP_POPUP_MAX_TAPS = 8
# 助战列表要一屏一屏往下翻找行（**列表顺序按好友最近登录排，每次都可能不一样**，
# 用户 2026-10-16 口径：只能往下滑着找，别指望"冠位从者总在第 N 屏"）。
# 真正的停止判据是"翻不动了"（到底），这个上限只是防无限翻的兜底。
# 一次只滑约两行（< 一屏），所以次数上限也要跟着放宽：一条 24 行的列表约 12 次，
# 留一倍余量（真到底由"行内容不变"判定，不靠这个数）。
SUPPORT_SCROLL_MAX = 40
# 翻一屏之后画面变化小于这个值 ⇒ 这一次没翻动。
SUPPORT_SCROLL_STILL_DELTA = 0.02
# ……而且要**连续这么多次**没翻动才算"到底"：单次滑动可能被吃掉、或正好撞上列表动画，
# 一次就认定到底会让我们提前放弃整张列表、退回普通从者（那正是 2026-10-16 要修的行为）。
SUPPORT_SCROLL_STILL_TRIES = 2
# 翻完一屏的行检测补拍次数：悬浮详情（手指停在某行上会弹「宝具·名称 等级N」）或转场帧
# 会让那一次检出为空，补拍两次再判死（2026-10-17 实测撞到过）。
SUPPORT_ROW_RETRY = 2
SUPPORT_ROW_RETRY_WAIT = 0.8
# 「行动力回复」菜单的探测：黄金果实那一行的模板（菜单开着时必然命中；实测它在
# 地图 / 战斗 / 助战屏上只有 0.19-0.28）。**AP 不够时游戏不会进本，而是弹这个菜单**——
# 检测到它就停手，别继续点（这条不花任何 AP）。
AP_MENU_BUTTON = "ap_apple_gold"
# 补给（黄金果实）——**消耗道具**，只有用户明确授权时才调用（`--use-apple N`）。
# 三道保险照抄 2026-10-14 立的口径（那时是在旧执行器里做的，2026-10-16 把它接回本执行器）：
#   ① 入口 = 地图/关卡屏左下「行动力」行里的 ＋（`ap_restore`；真机 0.979，助战屏/战斗里
#      只有 0.28-0.30 ⇒ 认得出就说明站对了屏）；
#   ② 菜单里点**黄金果实那一行**（`ap_apple_gold`）——它的搜索框**结构上不含最上面的
#      圣晶石行**，且拿它去比圣晶石行只有 0.723、白银果实 0.513（门槛 0.92）；
#   ③ 确认弹窗**两个都要认**：标题文字「消耗1个黄金果实」（`ap_apple_confirm_text`）与
#      「决定」按钮（`ap_confirm_ok`；对左边「取消」按钮区只有 0.586）。少认一个就停手。
# 每一步都先自证再点；判不出来就停手——宁可这次没补上，也绝不错耗道具。
AP_RESTORE_ENTRY = "ap_restore"
AP_APPLE_ROW = "ap_apple_gold"
AP_APPLE_CONFIRM_TEXT = "ap_apple_confirm_text"
# 补给入口的转场等待：从「连续出击」弹窗点左「关闭」回到地图时，会先出现
# 1-3 秒黑帧/加载帧；2026-10-19 实测第一张就是全黑，`ap_restore` 分数 0.000。
# 这里按“先等再判”处理，最多重试 5 次（约 7.5 秒），不把黑帧当成“没有 ＋”。
APPLE_ENTRY_TRIES = 5
APPLE_ENTRY_WAIT = 1.5
AP_APPLE_CONFIRM_OK = "ap_confirm_ok"
# 每局消耗的 AP（本关「打开宝物库之门 极级」固定 40）。
AP_PER_RUN = 40
# 行动力读数的容差：实测 ±2，所以"够不够"按 estimate + 容差 < 需要 来判（偏保守）。
AP_READ_TOLERANCE = 2
# 行动力读数读不出时重读一次（2026-10-15：收工那次正好撞上全黑转场帧，数就没了）。
AP_READ_TRIES = 4   # 2026-10-16：黑帧会被跳过（不算一次"读数失败"），所以给到 4 次
AP_READ_RETRY_WAIT = 2.0
# 低于这个亮度就认定是转场黑帧：**不当作"读数失败"**，跳过它继续等（2026-10-16：收尾点完
# 「关闭」后连拍两张 luma≈0 的黑帧，把两次尝试都浪费掉了，AP 账目又缺一条）。
AP_READ_BLANK_LUMA = 3.0
# 转场黑帧单独给额度：收工点完「关闭」后回地图要跨 4-6 秒转场（实测连拍 3 张黑帧），
# 黑帧不该吃掉"读数失败"的次数，这里按 2 秒一读给 5 次 ≈ 10 秒。
AP_READ_BLANK_TRIES = 5

# 结算页收尾（2026-10-12 起实机验证过；2026-10-16 改成"按画面自证"的状态机）：
# 结果页的页签都是"点面板任意处推进"，但**页数随副本而变**——每日任务的宝物库是
# 「战斗结束 → 推进会 → 战利品 → 弹窗」；冠位战多一页（战斗结束 → 与从者的羁绊 →
# 获得经验值 → 战利品 → 弹窗）。原来那套写死的 6 步脚本因此在冠位战上整体错位一格：
# 把「下一步」点在半路的推进会页上，等真·战利品页出来时脚本已经在点弹窗坐标了，
# 于是"点了没反应"、收尾停手，游戏停在战利品页的「下一步」上（2026-10-16 实测）。
# 现在每一步**先自证再点**：
#   * 认出右下「下一步 ▶」→ 点模板命中的中心（战利品页专用，认不出才退回推进点）；
#   * 认出「是否连续进行同一关卡？」弹窗 → 按调用方意图点「关闭」或「连续出击」；
#   * 两个都没认出来 → 退回"点面板任意处推进"。
# **默认只点「关闭」**：右侧「连续出击」会真实再耗一次 AP，只有 `--repeat` / 连刷才点。
WRAP_ADVANCE_POINT = (640, 570)          # 结果页"点面板任意处推进"的落点
WRAP_NEXT_BUTTON = "drops_next"          # 战利品页右下「下一步 ▶」（templates/buttons/）
WRAP_CLOSE_BUTTON = "repeat_close"       # 「连续出击」弹窗左「关闭」
WRAP_REPEAT_BUTTON = "repeat_again"      # 「连续出击」弹窗右「连续出击」
# 非好友助战被选中后，游戏会问「是否向提供支援的玩家发送好友申请？」；左侧「结束」
# 是零 AP 的继续按钮（2026-10-19 用户确认）。它不是「连续出击」弹窗，必须在收尾
# 状态机里单独识别，否则会被当成普通推进点盲点。
FRIEND_REQUEST_CLOSE = "friend_request_close"
# 走满这么多步还没认出「连续出击」弹窗就停手（正常一局 3-4 步；留足余量给多页结果）
WRAP_MAX_STEPS = 8
# 连着这么多次"点了没反应"就停手：宁可少点一步，也不接着盲点。
WRAP_STOP_AFTER_STILL = 2
WRAP_MIN_DELTA = 0.05
# 点击点附近（±40/±60）的变化量门槛。2026-10-12 实测：真正生效的点击 0.81-0.94
# （技能图标 0.81、宝具卡 0.92、指令卡 0.94），静止帧 0.0，动画噪声 ≤0.08。
MIN_REGION_DELTA = 0.25
# 说明：技能图标的"像不像"（battle_vision.icon_like_score）只写进日志当诊断，不当门槛。
# 2026-10-12 实测：同一个战斗界面上真图标只有 3/9 过 0.55，活动地图的场景色块反而能到
# 0.75 —— 它区分不了对错。真正的门槛是"画面判定 + 点击点附近的变化量"。


class ExecutionAbort(RuntimeError):
    """判据不成立就停：宁可停在原地，也不带着不确定继续点。"""


@dataclass
class SessionLayout:
    """本会话校准过的坐标。绑定规则要求这些值来自真机核验过的会话，
    换屏 / 重启 / 改分辨率都要重新校准（出处记在 source）。"""

    skill_x: dict[int, tuple[int, int, int]]
    skill_y: int
    np_cards: dict[int, tuple[int, int]]
    target_points: dict[int, tuple[int, int]]
    master_menu: tuple[int, int]
    master_skills: tuple[tuple[int, int], ...]
    undo: tuple[int, int]
    source: str = ""

    @classmethod
    def load(cls, path: Path | str) -> "SessionLayout":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            skill_x={int(key): tuple(value) for key, value in (payload.get("skill_x") or {}).items()},
            skill_y=int(payload["skill_y"]),
            np_cards={int(key): tuple(value) for key, value in (payload.get("np_cards") or {}).items()},
            target_points={
                int(key): tuple(value) for key, value in (payload.get("target_points") or {}).items()
            },
            master_menu=tuple(payload["master_menu"]),
            master_skills=tuple(tuple(item) for item in payload.get("master_skills") or []),
            undo=tuple(payload["undo"]),
            source=str(payload.get("source") or ""),
        )

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def skill_point(self, slot: int, index: int) -> tuple[int, int]:
        xs = self.skill_x.get(slot)
        if not xs or not 1 <= index <= len(xs):
            raise ExecutionAbort(f"布局里没有 {slot} 号位的第 {index} 格技能坐标")
        return int(xs[index - 1]), int(self.skill_y)

    def np_point(self, slot: int) -> tuple[int, int]:
        if slot not in self.np_cards:
            raise ExecutionAbort(f"布局里没有 {slot} 号位的宝具卡坐标")
        return int(self.np_cards[slot][0]), int(self.np_cards[slot][1])

    def target_point(self, slot: int) -> tuple[int, int]:
        if slot not in self.target_points:
            raise ExecutionAbort(f"布局里没有 {slot} 号位的立绘坐标（请选择对象）")
        return int(self.target_points[slot][0]), int(self.target_points[slot][1])


@dataclass
class StepRecord:
    index: int
    kind: str
    label: str
    turn: int
    scene_before: str
    round: int = 0
    scene_after: str = ""
    point: tuple[int, int] | None = None
    region_delta: float | None = None
    verdict: str = ""
    note: str = ""
    shot: str = ""
    seconds: float = 0.0


class BattleRunner:
    """一局的执行器。dry_run=True 时只读画面、不点击（开局前自检用）。"""

    def __init__(
        self,
        link: DeviceLink,
        layout: SessionLayout,
        run_id: str | None = None,
        dry_run: bool = False,
        settle: float = SETTLE_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
        wrap: bool = True,
        repeat: bool = False,
        pick_support: bool = False,
        support_row: int | None = None,
        support_key: str = "default",
        support_criteria: dict[str, Any] | None = None,
        rounds: int = 1,
        enter_quest: bool = False,
        auto_apple: int = 0,
    ) -> None:
        self.link = link
        self.layout = layout
        self.dry_run = dry_run
        self.settle = settle
        self.sleeper = sleeper
        self.log = log
        self.wrap = wrap
        # repeat=True 时收尾弹窗点右侧「连续出击」——会真实再耗一次 AP，只有用户
        # 明确要求刷本循环时才开。
        self.repeat = repeat
        # pick_support=True：点完「连续出击」之后接着把助战选上（等于把刷本循环里
        # 唯一剩下的判断步骤也交给执行器）。
        self.pick_support = pick_support
        # support_row=N：这次强制取第 N 行助战，并把它的身份块登记成指纹（首次标定用）。
        self.support_row = support_row
        self.support_key = support_key or "default"
        # support_criteria：来自 runbook 的 `support` 段（{"servant": 名, "ce_names": [...]}）。
        # 有它就按「从者 + 礼装白名单」挑行（2026-10-15 用户口径：不同副本助战不同，
        # 好友不一定常在，所以按"借哪只从者 + 带哪张礼装"挑，而不是认某个固定好友）。
        self.support_criteria = support_criteria or None
        # rounds=N（N>1）：连刷 N 局——第 1..N-1 局收尾点右「连续出击」+ 选助战直接进下一局，
        # 最后一局点左「关闭」回地图收工。
        self.rounds = max(1, int(rounds))
        # auto_apple=N：AP 不足时允许自动消耗最多 N 个黄金果实（用户 2026-10-19
        # 明确授权上限 3 个）。0 = 不自动用苹果，保持原来的手动补给行为。
        self.auto_apple = max(0, min(3, int(auto_apple)))
        self.apples_used = 0
        # 从开刷前的行动力读数开始跟踪；每打完一局扣 40。自然回复不计入（保守估计），
        # 所以只会在“按最坏情况确实不够”时补苹果，不会因为估算偏高而多耗道具。
        self.ap_estimate: int | None = None
        # enter_quest=True：先在地图上点关卡卡片把第一局开起来（已经在战斗里则跳过）。
        self.enter_quest = enter_quest
        self.round_index = 1
        self.run_id = run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
        self.run_dir = Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "runs" / self.run_id
        self.records: list[StepRecord] = []
        # 「这一回合已经点过的卡位」——它是**回合内**的约束（同一回合不能重复点同一张卡），
        # 换回合必须清空：2026-10-14 首次整局连跑（--start-at 1）时它一路累积，到第 25 个
        # 动作（第 3 回合第 2 张卡）已经用掉 5 个卡位，直接报"能用的 any 只有 0 张"。
        # 分段跑（每段一个进程）时它天然是干净的，所以这个 bug 直到整局连跑才露面。
        self.used_cards: list[int] = []
        self._turn = 0
        self.picked_support_row: int | None = None
        self._shot_seq = 0
        self._plan: plan_mod.ExecutionPlan | None = None   # 供每步增量落盘用

    def _add(self, record: StepRecord) -> StepRecord:
        """记一条步骤证据，并打上"第几局"（连刷时用来分辨回合边界）。"""
        record.round = self.round_index
        self.records.append(record)
        # 每步都落盘：这样页面的"实时步骤流"在**跑的时候**就能看到进度
        # （2026-10-14 E2 验收时发现：只在收尾写一次，跑到一半页面是空的）。
        self._write_log(self._plan)
        return record

    def _ap_menu_hint(self, image: Any) -> str:
        """画面是不是「行动力回复」菜单？是的话返回一句给人看的说明，否则空串。

        AP 不够时游戏不进本、而是弹这个菜单（2026-10-14 加的 AP 保护里的一环）。
        """
        try:
            menu = vision.match_button(image, AP_MENU_BUTTON)
        except Exception:  # 模板没登记之类：当探测不可用，不因此改变主流程
            return ""
        if menu.accepted:
            return "｜检测到「行动力回复」菜单：这一次出击的 AP 不够（游戏没进本），已停手、没有继续点。请先补 AP。"
        return ""

    def _read_ap_record(
        self,
        label: str,
        tag: str | None = None,
        tries: int = AP_READ_TRIES,
        retry_wait: float = AP_READ_RETRY_WAIT,
    ) -> vision.ApReading | None:
        """读一次行动力（只读）。读不出就**等 2 秒重读一次**再放弃——仍读不出就返回 None，
        **不因此打断整局**。

        为什么要重读：2026-10-15 收工那次读数正好撞上全黑转场帧（`run-20261015-125011`），
        数没了、AP 账目就少一条证据；换面/渐入只有一两秒，重读一次基本必中。

        `tag` 必须是 ASCII：截图文件名会用到它，而设备层写不了含中文的路径
        （2026-10-14 实测：`196_ap_收工.png` 直接报 No such file or directory）。
        """
        scene = None
        reading: vision.ApReading | None = None
        error = ""
        blank_skips = 0
        # "读数失败"的次数和"撞上转场"的次数分开算：转场黑帧不算失败（2026-10-16 修，
        # 原来黑帧也会吃掉一次重读，收工时回地图的转场就把 4 次额度用光了）。
        read_tries = max(1, int(tries))
        reads = 0
        blanks = 0
        attempts = 0
        while reads < read_tries and blanks < AP_READ_BLANK_TRIES:
            attempts += 1
            suffix = "" if attempts == 1 else f"_r{attempts}"
            try:
                scene, image, info = self._scene(f"ap_{tag or 'read'}{suffix}")
                # 全黑帧就是转场：跳过它、也**不算**一次读数失败
                if float(info.get("luma") or 0) < AP_READ_BLANK_LUMA:
                    blanks += 1
                    blank_skips += 1
                    self.log(f"    这一帧基本全黑（luma {info.get('luma')}）：是转场，{retry_wait:.0f} 秒后再看")
                    self.sleeper(retry_wait)
                    continue
                reads += 1
                reading = vision.read_ap(image)
            except Exception as exc:  # 截图/读数异常都不该把一局弄崩
                reads += 1
                error = str(exc)
                reading = None
            if reading is not None and reading.readable:
                if attempts > 1:
                    self.log(f"    第 {attempts} 次拿到可读的画面（前几次是过场帧或读数失败）")
                break
            if reads < read_tries:
                self.log(
                    f"    行动力读数读不出（{error or '这一帧没有可读的行动力条'}），"
                    f"{retry_wait:.0f} 秒后重读一次"
                )
                self.sleeper(retry_wait)
        if reading is None and not error and blank_skips:
            error = (
                f"连拍 {blank_skips} 帧都是全黑转场（luma < {AP_READ_BLANK_LUMA}）："
                "当时不在能读行动力的画面"
            )
        scene_name = scene.name if scene is not None else vision.SCENE_OTHER
        self._add(StepRecord(
            index=0, kind="ap", label=f"行动力读数（{label}）", turn=0,
            scene_before=scene_name, verdict="ok",
            note=reading.report() if reading is not None else (error or "行动力读数读不出"),
        ))
        self.log(f"    {reading.report() if reading is not None else error}")
        return reading

    def _shot(self, tag: str) -> tuple[Any, dict[str, Any]]:
        self._shot_seq += 1
        path = self.run_dir / f"{self._shot_seq:03d}_{tag}"
        info = self.link.shot(path)
        return vision.load(info["path"]), info

    def _scene(self, tag: str) -> tuple[vision.SceneReading, Any, dict[str, Any]]:
        image, info = self._shot(tag)
        scene = vision.read_scene(image)
        self.log(f"    [{tag}] {scene.report()} (luma {info.get('luma')})")
        return scene, image, info

    def run(
        self,
        plan: plan_mod.ExecutionPlan,
        start_at: int = 1,
        stop_at: int = 0,
    ) -> list[StepRecord]:
        """跑动作流。`start_at` / `stop_at` 是 1-based 动作序号，用于人工监督下的分段执行：
        跑到 `stop_at` 之前停下（把现场留给人工核对），之后可带 `start_at` 续跑。"""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        mode = "DRY-RUN" if self.dry_run else "实机执行"
        self._plan = plan
        rounds_note = f"｜连刷 {self.rounds} 局" if self.rounds > 1 else ""
        self.log(f"运行 {self.run_id}｜{plan.title or plan.quest_id}｜{mode}{rounds_note}")
        if self.auto_apple:
            self.log(f"AP 不足时自动用黄金果实：最多 {self.auto_apple} 个")
        self.log(f"证据目录：{self.run_dir}")
        if start_at > 1:
            self.log(f"从第 {start_at} 个动作续跑")
        if self.dry_run:
            return self._dry_run(plan)
        # 真跑之前先认领「模拟器 + 设备通道」资源租约：被别人占着就停手，不硬闯。
        lease = DeviceLease(job_id=self.run_id)
        if not lease.acquire():
            raise ExecutionAbort(f"模拟器 / 设备通道正被别的任务占着，先不跑：{lease.note}")
        self.log(f"    {lease.note}")
        try:
            return self._run_rounds(plan, start_at, stop_at)
        finally:
            lease.release()

    def _run_rounds(self, plan: plan_mod.ExecutionPlan, start_at: int, stop_at: int) -> list[StepRecord]:
        """真正跑动作流（含连刷与收尾）。资源租约由 `run()` 管。"""
        if self.enter_quest:
            # 冷启动：当前在地图上就先点关卡卡片把这一局开起来（已经在战斗里就跳过）。
            self._enter_quest()
        for round_index in range(1, max(1, self.rounds) + 1):
            self.round_index = round_index
            last_round = round_index >= self.rounds
            if self.rounds > 1:
                self.log(f"—— 第 {round_index}/{self.rounds} 局 ——")
            self.used_cards.clear()
            self._turn = 0
            battle_over = self._play_round(
                plan, start_at if round_index == 1 else 1, stop_at if round_index == 1 else 0
            )
            if not battle_over or not self.wrap:
                break
            last_index = self.records[-1].index if self.records else 0
            if last_round:
                # 最后一局：收尾点左侧「关闭」回地图，不额外花 AP。
                self._do_wrap(last_index)
                break
            # 还要接着刷：直接点右侧「连续出击」。AP 不足时游戏会就地弹出
            # 「行动力回复」菜单；在该菜单里用黄金果实（最多 auto_apple），
            # 然后继续助战选择。不要先关闭弹窗回地图（2026-10-19 用户口径）。
            self._do_wrap(last_index, continue_farming=True)
            self._handle_ap_restore_menu(last_index)
            self._do_support(last_index)
        # 收工时再读一次行动力：给 AP 账目留证据（只读，读不出不拦）
        self._read_ap_record("收工", "done")
        self._write_log(plan)
        self.log(f"计划跑完：{len(self.records)} 个动作，日志 {self.run_dir / 'steps.json'}")
        return self.records

    def _play_round(self, plan: plan_mod.ExecutionPlan, start_at: int, stop_at: int) -> bool:
        """跑一遍动作流。返回 True 表示这局以 battle_over 结束（收尾交给调用方）。"""
        for index, action in enumerate(plan.actions, start=1):
            if index < start_at:
                continue
            if action.turn != self._turn:
                self._turn = action.turn
                self.used_cards.clear()
            if stop_at and index >= stop_at:
                self._add(StepRecord(
                    index=index, kind=action.kind, label=action.label, turn=action.turn,
                    scene_before="", verdict="paused",
                    note=f"按 --stop-at 在第 {index} 个动作之前停下（未点击）",
                ))
                self._write_log(plan)
                self.log(f"已在第 {index} 个动作（{action.label}）之前停下，未点击")
                return False
            if action.kind == plan_mod.WAIT:
                self._do_wait(index, action)
                if self.records and self.records[-1].verdict == "battle_over":
                    return True
            else:
                self._do_action(index, action)
        return False

    def _dry_run(self, plan: plan_mod.ExecutionPlan) -> list[StepRecord]:
        """dry-run 只回答"现在能不能起步"。

        不点击就不会有真实的画面推进，所以后续步骤没有可校验的对象——它们的判据只能
        等真机执行时才成立。这里如实标注成 skipped，而不是假装校验过。
        """
        first_index = next(
            (index for index, action in enumerate(plan.actions, start=1) if action.kind != plan_mod.WAIT),
            None,
        )
        if first_index is None:
            self.log("动作流里没有可执行步骤")
            return self.records
        first = plan.actions[first_index - 1]
        scene, image, _info = self._scene("dryrun_before")
        record = StepRecord(index=first_index, kind=first.kind, label=first.label,
                            turn=first.turn, scene_before=scene.name)
        self._add(record)
        if first.expect_before != plan_mod.SCENE_ANY and scene.name != first.expect_before:
            record.verdict = "abort"
            record.note = f"期望前态 {first.expect_before}，实际 {scene.name}"
            self._abort(record, scene)
        record.point = self._resolve_point(first, scene, image)
        record.verdict = "dry-run"
        record.note = "起步自检通过（未点击）"
        for index, action in enumerate(plan.actions, start=1):
            if index == first_index:
                continue
            self._add(StepRecord(
                index=index, kind=action.kind, label=action.label, turn=action.turn,
                scene_before="", verdict="skipped",
                note="dry-run 不点击，无法校验后续步骤",
            ))
        self._write_log(plan)
        self.log(f"dry-run 结束：起步自检" + ("通过" if record.verdict == "dry-run" else "未通过"))
        return self.records

    def _do_action(self, index: int, action: plan_mod.Action) -> None:
        started = time.perf_counter()
        scene, image, _info = self._scene(f"{action.kind}{index}_before")
        record = StepRecord(
            index=index, kind=action.kind, label=action.label, turn=action.turn,
            scene_before=scene.name,
        )
        self._add(record)

        if action.expect_before != plan_mod.SCENE_ANY and scene.name != action.expect_before:
            record.verdict = "abort"
            record.note = f"期望前态 {action.expect_before}，实际 {scene.name}"
            self._abort(record, scene)

        try:
            point = self._resolve_point(action, scene, image)
        except (ValueError, ExecutionAbort) as exc:
            # 判据层面的挑不出点位（手牌里没有可用的卡、认不出纹章卡、偏好链全不满足…）
            # 一律走 fail-stop：停在这一步、写日志、留现场，而不是抛裸 traceback 让整局崩掉
            # （2026-10-14 实测过一次）。`ExecutionAbort` 也要接住：否则那些路径虽然同样会停，
            # 但 steps.json 里那一步的 note 是空的（2026-10-15 加偏好链时发现）。
            record.verdict = "abort"
            record.note = f"挑不出可执行的点位：{exc}"
            self._abort(record, scene)
        record.point = point
        if self.dry_run:
            record.verdict = "dry-run"
            record.note = "只读校验通过（未点击）"
            record.seconds = round(time.perf_counter() - started, 2)
            return

        box_half = 60 if action.kind in (plan_mod.ATTACK, plan_mod.MASTER_MENU) else 40
        box = (point[0] - box_half, point[1] - box_half, point[0] + box_half, point[1] + box_half)
        attempts = TAP_RETRY + 1
        for attempt in range(1, attempts + 1):
            self.link.tap(point[0], point[1], settle=self.settle)
            verdict, after_scene, delta, note = self._verify_after(
                f"{action.kind}{index}_a{attempt}", action, image, box
            )
            record.scene_after = after_scene.name
            record.region_delta = delta
            if verdict == "ok":
                record.verdict, record.note = "ok", note
                break
            if verdict == "retry" and attempt < attempts:
                self.log(f"    点击似乎没落到东西（区域变化 {delta}，画面仍 {after_scene.name}），重试一次")
                continue
            record.verdict = "abort"
            record.note = note
            self._abort(record, after_scene)
        record.seconds = round(time.perf_counter() - started, 2)

    def _verify_after(
        self, tag: str, action: plan_mod.Action, before_image: Any, box: tuple[int, int, int, int]
    ) -> tuple[str, vision.SceneReading, float, str]:
        """点完之后到底成没成。

        判据（顺序）：画面判定变到期望状态；或者画面本来就该不变时，点击点附近必须
        真的有变化。演出期间的中间帧（技能横幅会遮住按钮）靠轮询等过去，避免误停。
        过场帧（换面黑帧 / 结算渐入 / 转场白屏）不占轮询预算——见
        POST_POLL_TRANSITION_SECONDS 的说明。
        """
        scene = None
        delta = 0.0
        polls = 0
        transition_deadline = 0.0
        while True:
            if polls:
                self.sleeper(POST_POLL_WAIT)
            polls += 1
            scene, after_image, _ = self._scene(f"{tag}_p{polls}")
            delta = vision.region_delta(before_image, after_image, box)
            if action.expect_after == plan_mod.SCENE_ANY:
                return "ok", scene, delta, f"第 3 个卡位已满，回合自动执行（区域变化 {delta}）"
            if scene.name == action.expect_after and (
                action.expect_before != action.expect_after or delta >= MIN_REGION_DELTA
            ):
                return "ok", scene, delta, f"{action.expect_before} -> {scene.name}（区域变化 {delta}）"
            if scene.name == vision.SCENE_OTHER:
                # 过场帧。既不能判成"点成了"，也不能判成"没点到"（判成没点到会再点
                # 一次，重复点击是危险方向），所以只继续等。
                if not transition_deadline:
                    transition_deadline = time.monotonic() + POST_POLL_TRANSITION_SECONDS
                    self.log(f"    第 {polls} 次后置校验撞上过场帧（{scene.name}），继续等（不重试点击）")
                if time.monotonic() < transition_deadline:
                    continue
                break
            if polls >= POST_POLL_TRIES:
                break
        assert scene is not None
        if scene.name == action.expect_after or scene.name == action.expect_before:
            return "retry", scene, delta, f"画面仍是 {scene.name}，且点击点附近没变化（{delta}）"
        return "abort", scene, delta, f"期望后态 {action.expect_after}，实际 {scene.name}（区域变化 {delta}）"

    def _do_wait(self, index: int, action: plan_mod.Action) -> None:
        started = time.perf_counter()
        record = StepRecord(index=index, kind=action.kind, label=action.label,
                            turn=action.turn, scene_before="")
        self._add(record)
        deadline = time.time() + WAIT_TIMEOUT_SECONDS
        shot_failures = 0
        battle_frames = 0
        over_frames = 0
        previous = None
        while time.time() < deadline:
            if not self.dry_run:
                self.sleeper(WAIT_POLL_SECONDS)
            try:
                scene, image, _info = self._scene(f"wait{index}")
            except DeviceLinkError as exc:
                # 截图偶发失败（过场黑帧）不该把整局崩掉：记下来继续等，连续失败才停。
                shot_failures += 1
                self.log(f"    等待中截图失败第 {shot_failures} 次：{exc}")
                if shot_failures >= 3:
                    record.verdict = "abort"
                    record.note = f"连续 {shot_failures} 次截图失败（设备链路）：{exc}"
                    self._abort(record, None)
                continue
            shot_failures = 0
            record.scene_after = scene.name
            # 相邻两帧变化量：判断"画面是不是已经静下来了"。宝具演出的中间帧两两之间
            # 变化 0.93-1.0（2026-10-14 用磁盘上的 wait 帧实测），结算页几乎是静止的。
            still = previous is None or vision.region_delta(previous, image) <= WAIT_STILL_DELTA
            previous = image
            if scene.name == vision.SCENE_BATTLE_MAIN:
                battle_frames += 1
                over_frames = 0
                if battle_frames >= WAIT_CONFIRM_FRAMES:
                    record.verdict = "ok"
                    record.note = f"下一回合的主战斗界面已就绪（连续 {battle_frames} 次确认）"
                    break
                self.log("    等待中：看到主战斗界面，再确认一次（避开演出帧的误判）")
                continue
            battle_frames = 0
            if scene.name == vision.SCENE_OTHER and still:
                # 演出过场（换面白屏 / 结算是渐入）也会被判成 other，所以**不能看一眼就
                # 当成本局结束**（2026-10-13 实测：转场白屏 luma 232 被误判），也不能只看
                # "不在战斗内"就计数——宝具演出能连出好几帧 other，那时误判会去点结算页
                # 坐标、实机上有踩到选牌界面的风险。所以还要**画面已经静下来**才算一帧
                # 证据，连续 WAIT_OVER_FRAMES 帧才认定本局结束。
                over_frames += 1
                if over_frames >= WAIT_OVER_FRAMES:
                    record.verdict = "battle_over"
                    record.note = (
                        f"连续 {over_frames} 帧都是静止的非战斗画面（结算页 / 地图）：本局到此结束"
                    )
                    break
                continue
            over_frames = 0
        else:
            record.verdict = "abort"
            record.note = f"{WAIT_TIMEOUT_SECONDS:.0f} 秒内没等到主战斗界面（最后判定 {record.scene_after}）"
            self._abort(record, None)
        record.seconds = round(time.perf_counter() - started, 2)

    def _resolve_point(self, action: plan_mod.Action, scene: vision.SceneReading, image: Any) -> tuple[int, int]:
        if action.kind == plan_mod.SKILL:
            point = self.layout.skill_point(int(action.actor_slot or 0), int(action.skill_index or 0))
            score = vision.icon_like_score(image, point)
            self.log(f"    技能图标评分 {score}（仅诊断，不当门槛）")
            return point
        if action.kind == plan_mod.TARGET:
            return self.layout.target_point(int(action.target_slot or 0))
        if action.kind == plan_mod.MASTER_MENU:
            return self.layout.master_menu
        if action.kind == plan_mod.MASTER_SKILL:
            index = int(action.skill_index or 0)
            if not 1 <= index <= len(self.layout.master_skills):
                raise ExecutionAbort(f"布局里没有御主礼装第 {index} 格技能")
            return int(self.layout.master_skills[index - 1][0]), int(self.layout.master_skills[index - 1][1])
        if action.kind == plan_mod.ATTACK:
            if scene.attack is None or not scene.attack.usable:
                raise ExecutionAbort("找不到可用的「攻击」按钮（画面不是主战斗界面？）")
            return scene.attack.center
        if action.kind == plan_mod.NP:
            return self.layout.np_point(int(action.actor_slot or 0))
        if action.kind == plan_mod.CARD:
            if not scene.hand.verified:
                raise ExecutionAbort(f"要出卡但没认出选牌界面：{scene.hand.report()}")
            if action.choices:
                return self._resolve_card_choice_chain(action, scene, image)
            if action.position == plan_mod.POSITION_COMMAND_CODE:
                # 「必须是刻了某个指令纹章的那张卡」——这一步不靠位置规则、不靠人指，
                # 靠 battle_vision 按锚点+模板判；判不出来就停在这里等人工，绝不猜。
                return self._resolve_command_code_card(action, scene, image)
            picks = vision.resolve_cards(
                scene.hand, str(action.card_color), count=1,
                position=action.position, exclude=self.used_cards,
            )
            card = scene.hand.card_at(picks[0])
            if card is None:
                raise ExecutionAbort(f"卡片 {picks[0]} 读不出坐标")
            self.used_cards.append(card.index)
            self.log(f"    选卡：{action.card_color} -> 第 {card.index} 张（x={card.center_x}）｜{scene.hand.report()}")
            return int(card.center_x), vision.HAND_CARD_Y

    def _resolve_card_choice_chain(
        self, action: plan_mod.Action, scene: vision.SceneReading, image: Any
    ) -> tuple[int, int]:
        """选卡偏好链：按顺序试，**第一条能在当前手牌挑到卡的生效**；全挑不到才停手。

        这是给"必须靠指令卡、但手牌随机"的关卡用的（2026-10-15 冠位战实测需求）：
        例如「优先打手红卡 → 没有就打手任意卡 → 再没有就任意卡」，规则写进 spec 之后，
        执行器不会因为第一条不成立就停在原地。挑不到任何一条才 fail-stop（判据不成立不猜）。
        """
        reasons: list[str] = []
        owner_library = vision.load_support_library("card") if any(
            choice.get("owner") for choice in action.choices
        ) else {}
        for index, choice in enumerate(action.choices, start=1):
            label = str(choice.get("label") or f"第 {index} 条")
            try:
                if choice.get("engraved_code"):
                    probe = replace(
                        action,
                        card_color=str(choice.get("card") or "any"),
                        position=plan_mod.POSITION_COMMAND_CODE,
                        command_code=str(choice["engraved_code"]),
                        choices=(),
                    )
                    return self._resolve_command_code_card(probe, scene, image)
                allowed = None
                if choice.get("owner"):
                    wanted_owner = str(choice["owner"])
                    reference = owner_library.get(wanted_owner)
                    if reference is None:
                        raise ExecutionAbort(
                            f"卡主「{wanted_owner}」的卡面指纹没登记过（库里：{list(owner_library) or '空'}）："
                            "先在选牌屏登记一次它的卡面，或者把这一条改成不带 owner"
                        )
                    allowed = []
                    detail = []
                    for card in scene.hand.cards:
                        name, score = vision.match_card_owner(image, card.center_x, owner_library)
                        detail.append(f"第{card.index}张={name or '认不出'}({score:.3f})")
                        if name == wanted_owner:
                            allowed.append(card.index)
                    self.log(f"    卡主识别（要 {wanted_owner}）：" + "；".join(detail))
                    if not allowed:
                        raise ExecutionAbort(
                            f"这一手没有「{wanted_owner}」的卡（" + "；".join(detail) + "）"
                        )
                picks = vision.resolve_cards(
                    scene.hand, str(choice.get("card") or "any"), count=1,
                    position=str(choice.get("position") or "any"), exclude=self.used_cards,
                    allowed=allowed,
                )
                card = scene.hand.card_at(picks[0])
                if card is None:
                    raise ExecutionAbort(f"卡片 {picks[0]} 读不出坐标")
            except (ExecutionAbort, ValueError) as exc:
                reasons.append(f"第 {index} 条（{label}）：{exc}")
                continue
            self.used_cards.append(card.index)
            self.log(f"    偏好链命中第 {index} 条「{label}」-> 第 {card.index} 张（x={card.center_x}）")
            return int(card.center_x), vision.HAND_CARD_Y
        raise ExecutionAbort("偏好链每一条都挑不到卡（手牌不满足）：" + "；".join(reasons))

    def _resolve_command_code_card(
        self, action: plan_mod.Action, scene: vision.SceneReading, image: Any
    ) -> tuple[int, int]:
        name = str(action.command_code or "")
        try:
            match = vision.find_command_code_card(image, name)
        except (FileNotFoundError, KeyError) as error:
            raise ExecutionAbort(f"纹章模板不可用：{error}") from error
        self.log(f"    纹章识别：{match.report()}")
        for note in match.notes:
            self.log(f"      · {note}")
        if not match.accepted or match.index is None:
            raise ExecutionAbort(
                f"认不出哪张卡刻着「{name}」：{match.report()}"
                "（判据不足时停下来等人工指卡，不猜卡位）"
            )
        if match.index in self.used_cards:
            raise ExecutionAbort(f"识别出的是第 {match.index} 张卡，但这一回合已经用掉了")
        card = scene.hand.card_at(match.index)
        if card is None:
            raise ExecutionAbort(f"第 {match.index} 张卡读不出坐标")
        if action.card_color not in ("any", "") and card.color != action.card_color:
            raise ExecutionAbort(
                f"识别出的第 {match.index} 张是「{card.label}」，但 spec 要求的是 "
                f"{vision.CARD_COLORS.get(str(action.card_color), action.card_color)}"
            )
        self.used_cards.append(card.index)
        self.log(
            f"    选卡：刻「{name}」-> 第 {card.index} 张（{card.label}，x={card.center_x}）"
            f"｜{scene.hand.report()}"
        )
        return int(card.center_x), vision.HAND_CARD_Y
        if action.kind == plan_mod.UNDO:
            return self.layout.undo
        raise ExecutionAbort(f"不知道该怎么执行动作类型：{action.kind}")

    def _abort(self, record: StepRecord, scene: vision.SceneReading | None) -> None:
        detail = scene.report() if scene else ""
        record.note = f"{record.note}｜{detail}"
        self._write_log(None)
        raise ExecutionAbort(f"第 {record.index} 步（{record.label}）停下：{record.note}")

    @staticmethod
    def _support_rows_signature(image: Any, rows: list[vision.SupportRow]) -> tuple:
        """行内容的指纹（面板位置 + 身份块均值）：用来判断"这一屏到底有没有翻动"。

        为什么不用整帧像素差（2026-10-17 实测）：悬停到某一行时会弹出"从者详情卡"，那张卡
        一直在轻微动画 ⇒ 整帧差永远大于阈值，于是"翻不动"永远判不出来，白白空滑 24 次。
        """
        signature = []
        for row in rows:
            left, top, right, bottom = row.identity
            patch = image[top : bottom + 1, left : right + 1]
            mean = round(float(patch.mean()), 1) if patch.size else 0.0
            signature.append((row.panel, mean))
        return tuple(signature)

    def _swipe_support_list(self, rows: list[vision.SupportRow], direction: int) -> None:
        """按**已检出行的几何**在助战列表里滑一屏（不手量坐标）。

        `direction=+1` 往下看后面的行（手指从下往上划）、`-1` 往回翻。
        **两端都落在行外**（起点在最后一行下面、终点在第一行上面）：2026-10-17 实测，
        手指停在某一行上时 FGO 会弹出「宝具 · 名称 等级N」的悬浮详情（模拟器是鼠标指针
        语义），那块浮层会盖住列表顶部、让下一次行检测失效。落在行与行之间的空白/标题带
        就不会触发。

        **一次只滑约两行（< 一屏）**：2026-10-17 用户指出"中间明明有光之高扬斯卡娅"，
        说明原来"一次滑一屏（≈3 行）"在带惯性时会多滑一点、把中间的行整段跳过。现在让
        相邻两次截图**重叠约一行**，宁可多翻几次也不漏行。
        """
        first_row, last_row = rows[0], rows[-1]
        x = (first_row.center[0] + last_row.center[0]) // 2
        # 终点取第 1、2 行之间的**空隙中心**（不在任何一行上），起点取最后一行下方。
        gap_top = first_row.panel[3] + 2
        gap_bottom = rows[1].panel[1] - 2 if len(rows) > 1 else gap_top + 40
        upper = max(96, (gap_top + gap_bottom) // 2)
        lower = min(704, last_row.panel[3] + 40)
        if lower - upper < 160:
            upper = max(96, lower - 200)
        if direction > 0:
            self.link.swipe(x, lower, x, upper, settle=self.settle)
        else:
            self.link.swipe(x, upper, x, lower, settle=self.settle)

    def _scroll_support_to_edge(
        self, rows: list[vision.SupportRow], direction: int, tag: str, start_image: Any = None
    ) -> tuple[Any, list[vision.SupportRow], bool]:
        """一直滑到翻不动为止（`direction=+1` 到底 / `-1` 到顶），返回最后一帧与行列表。

        为什么需要"先回顶"（2026-10-17）：上一局可能中途停手，把列表留在中间位置；从中间
        开始扫会漏掉**上面**的冠位从者，于是会错误地"退普通行"。先滑到顶再往下扫，结果才
        与"从第一屏开始"一致。翻不动的判据同样是**连续两次**（单次滑动可能被吃掉）。
        """
        image: Any = start_image
        still = 0
        moved_any = False
        signature = self._support_rows_signature(image, rows) if image is not None else None
        for step in range(1, SUPPORT_SCROLL_MAX + 1):
            self._swipe_support_list(rows, direction=direction)
            scene, image, _info = self._scene(f"{tag}{step}")
            found = vision.find_support_rows(image)
            # 转场 / 悬浮详情会让某一次行检测失效：再补拍两次，别一次判死。
            for extra in range(1, SUPPORT_ROW_RETRY + 1):
                if found:
                    break
                self.sleeper(SUPPORT_ROW_RETRY_WAIT)
                scene, image, _info = self._scene(f"{tag}{step}_r{extra}")
                found = vision.find_support_rows(image)
            if found:
                rows = found
            new_signature = self._support_rows_signature(image, rows)
            if signature is not None and new_signature == signature:
                still += 1
                if still >= SUPPORT_SCROLL_STILL_TRIES:
                    self.log(f"    连着翻不动 ⇒ 已经{'到底' if direction > 0 else '到顶'}了")
                    break
            else:
                still = 0
                moved_any = True
            signature = new_signature
        return image, rows, moved_any

    def _dismiss_friend_request(
        self,
        image: Any,
        *,
        index: int,
        scene_before: str,
        label: str,
        tag: str,
    ) -> bool:
        """非好友助战的「是否发送好友申请？」弹窗：点左侧「结束」继续。

        只认登记过的按钮模板；没登记、分数不够或没有落点都不点，保持 fail-stop。
        """
        try:
            match = vision.match_button(image, FRIEND_REQUEST_CLOSE)
        except Exception as exc:  # 模板缺失/损坏：当作没有这个弹窗，不改变主流程
            self.log(f"    {tag}：好友申请弹窗探测不可用（{exc}）")
            return False
        if not (match.accepted and match.center):
            return False
        self.log(f"    {tag}：{match.report()}（非好友助战）⇒ 点「结束」")
        self.link.tap(match.center[0], match.center[1], settle=self.settle)
        self._add(StepRecord(
            index=index,
            kind="friend_request_close",
            label=label,
            turn=self._turn,
            scene_before=scene_before,
            point=match.center,
            verdict="ok",
            note=(
                f"检测到非好友助战的好友申请弹窗，点左侧「结束」@{match.center}"
                f"（模板分数 {match.score}，未申请好友、未消耗 AP）"
            ),
        ))
        return True

    def _do_support(self, index: int) -> None:
        """在「助战选择」屏上按登记过的身份块指纹挑一行并点它。

        规则（用户 2026-10-14 口径 + 本机实测）：只看画面**左边的身份块**（名字带 +
        「从者 / 宝具」面板整块）。实测同一行 NCC 1.000、不同职阶变体 0.494 / 0.272，
        所以门槛取 0.85 且要求与次高差 ≥0.05。没登记过指纹、或没有一行达标，都 fail-stop
        并把现场截图留给人工——**绝不"取最上面那行"顶上去**。
        """
        record = StepRecord(index=index, kind="support", label="选助战", turn=0, scene_before="")
        self._add(record)
        scene = image = None
        rows: list[vision.SupportRow] = []
        confirm_tapped = False
        for attempt in range(1, SUPPORT_LIST_TRIES + 1):
            tag = "support_before" if attempt == 1 else f"support_before_r{attempt}"
            scene, image, _info = self._scene(tag)
            if self._dismiss_friend_request(
                image, index=index, scene_before=scene.name,
                label="关闭好友申请弹窗", tag="进入助战屏时",
            ):
                self.sleeper(SUPPORT_LIST_WAIT)
                continue
            if not confirm_tapped:
                confirm = vision.match_button(image, GRAND_QUEST_CONFIRM)
                if confirm.accepted and confirm.center:
                    self.log(f"    冠位战挑战确认：{confirm.report()} ⇒ 点「任务开始」")
                    self.link.tap(confirm.center[0], confirm.center[1], settle=self.settle)
                    self._add(StepRecord(
                        index=index, kind="enter_quest_confirm", label="确认启动冠位战", turn=0,
                        scene_before=scene.name, point=confirm.center, verdict="ok",
                        note=(
                            f"冠位战挑战确认弹窗：点「任务开始」@{confirm.center}"
                            f"（模板分数 {confirm.score}），交给「选助战」"
                        ),
                    ))
                    confirm_tapped = True
                    self.sleeper(SUPPORT_LIST_WAIT)
                    continue
            rows = vision.find_support_rows(image)
            if rows:
                break
            if attempt < SUPPORT_LIST_TRIES:
                self.log(f"    还没看到助战列表（判定 {scene.name}），{SUPPORT_LIST_WAIT:.0f} 秒后再看一次")
                self.sleeper(SUPPORT_LIST_WAIT)
        assert scene is not None
        record.scene_before = scene.name
        if not rows:
            record.verdict = "abort"
            record.note = f"当前画面不是「助战选择」屏（判定 {scene.name}）" + self._ap_menu_hint(image)
            self._abort(record, scene)
        self.log("    助战行：" + "；".join(row.report() for row in rows))
        pick_reason = ""   # 选行理由（只有"整张列表没有冠位从者、退回普通行"这一种）
        if self.support_row:
            if not 1 <= int(self.support_row) <= len(rows):
                record.verdict = "abort"
                record.note = f"--support-row {self.support_row} 超范围（这一帧只有 {len(rows)} 行）"
                self._abort(record, scene)
            pick = rows[int(self.support_row) - 1]
            meta_path = vision.save_support_reference(
                self.support_key, image, pick,
                note=f"由 --support-row {pick.index} 登记（run {self.run_id}）",
            )
            self.log(f"    按 --support-row 取第 {pick.index} 行；身份块指纹已登记：{meta_path}")
        else:
            criteria = self.support_criteria or {}
            prefer_grand = bool(criteria.get("prefer_grand"))
            servant_reference = None
            ce_references: dict[str, Any] = {}
            if criteria:
                servant_library = vision.load_support_library("servant")
                ce_library = vision.load_support_library("ce")
                wanted_servant = str(criteria.get("servant") or "")
                wanted_ce = [str(name) for name in criteria.get("ce_names") or []]
                servant_reference = servant_library.get(wanted_servant)
                # 同一只从者的**另一版布局**指纹（窄块 / 宽块的字距字号不同，一个模板在另一
                # 版上只有 0.15）。命名约定：`<从者名>_<变体说明>`，如 `光之高扬斯卡娅_冠位宽块`。
                servant_variants = {
                    name: reference
                    for name, reference in servant_library.items()
                    if name != wanted_servant and name.startswith(f"{wanted_servant}_")
                }
                ce_references = {name: ce_library[name] for name in wanted_ce if name in ce_library}
                missing_ce = [name for name in wanted_ce if name not in ce_library]
                if servant_reference is None:
                    record.verdict = "abort"
                    record.note = (
                        f"助战规则要的从者指纹不在库里：从者「{wanted_servant}」未登记"
                        + (f"（另外礼装 {'/'.join(missing_ce)} 也没登记）" if missing_ce else "")
                        + "；先在助战屏登记它（或在 spec 里改用 --support-row），不猜行"
                    )
                    self._abort(record, scene)
                if wanted_ce and not ce_references:
                    record.verdict = "abort"
                    record.note = (
                        f"礼装白名单里的 {'/'.join(missing_ce)} 都没登记过；"
                        "要么先登记礼装指纹，要么把白名单留空（= 只按从者挑行），不猜行"
                    )
                    self._abort(record, scene)
                if ce_references:
                    self.log(
                        f"    按「从者 + 礼装」挑行：从者 {wanted_servant}、"
                        f"礼装白名单 {list(ce_references)}"
                    )
                else:
                    self.log(
                        f"    只按从者挑行：{wanted_servant}（没指定礼装白名单——"
                        "冠位战里助战可以戴 3 件礼装、礼装区几何不一样，按礼装挑不可靠）"
                    )
                if servant_variants:
                    self.log(f"    同一只从者另有 {len(servant_variants)} 份布局变体指纹（每行取最高分）：{list(servant_variants)}")
                if criteria.get("prefer_grand"):
                    self.log(
                        "    优先挑「冠位从者」：**整张列表**里找 —— 这一屏没有就往下翻，"
                        "一路翻到底都没有冠位从者，才退回普通行"
                    )
            else:
                try:
                    reference, meta = vision.load_support_reference(self.support_key)
                except FileNotFoundError as exc:
                    record.verdict = "abort"
                    record.note = (
                        f"还没登记过助战行指纹（{exc}）：先跑一次 "
                        "--pick-support-only --support-row N 让它认一次，不要猜行"
                    )
                    self._abort(record, scene)
                self.log(f"    指纹登记于 {meta.get('captured_at')}（当时是第 {meta.get('row_index')} 行）")

            def evaluate(row_list: list[vision.SupportRow]) -> vision.SupportMatch:
                """用当前这一帧 + 当前行列表打分（闭包读的是最新的 image/rows）。"""
                if servant_reference is not None:
                    return vision.match_support_criteria(
                        image, servant_reference, ce_references, rows=row_list,
                        prefer_grand=prefer_grand,
                        extra_servant_references=servant_variants,
                    )
                return vision.match_support_row(image, reference, rows=row_list)

            match = evaluate(rows)
            self.log(f"    {match.report()}")
            # 当前可见范围里没有 ⇒ 往下翻页找（翻页手势的起止点按已检出的行的几何给，
            # 不是手量固定坐标；每翻一次都重新自证）。
            # 先把列表滑回**最上面**再开始扫：上一局可能停在中间位置，从中间开始会漏掉
            # 上面的冠位从者（2026-10-17 补）。已经在顶上时只多花两次探测。
            self.log("    先把助战列表滑回最上面（保证是从第一屏开始扫）")
            image, rows, _moved = self._scroll_support_to_edge(
                rows, direction=-1, tag="support_to_top", start_image=image
            )
            if not rows:
                record.verdict = "abort"
                record.note = "滑回顶部之后认不出助战行了" + self._ap_menu_hint(image)
                self._abort(record, scene)
            match = evaluate(rows)
            self.log(f"    回到顶部后：{match.report()}")
            # `prefer_grand` 时"没有"= **这一屏没有冠位从者**：哪怕这一屏有普通杀狐也要接着
            # 往下翻（用户 2026-10-16 澄清："首屏没有的话就往下翻，一直到底部都没有的话就
            # 选个普通杀狐"）。到底的判据是"翻完画面几乎没变"。
            scrolls = 0
            still = 0
            bottom_reached = False
            # 普通行的候选要**跨屏记住**：它多半出现在第一屏，而翻到底时最后那一屏往往
            # 一只杀狐都没有（2026-10-17 实测：只认"当前这一屏的 match.plain"会导致
            # "明明首屏有一只普通杀狐，却因为最后几屏没有而报找不到"）。
            plain_seen = match.plain
            while not match.accepted and scrolls < SUPPORT_SCROLL_MAX:
                self.log(f"    往下翻一屏找（第 {scrolls + 1}/{SUPPORT_SCROLL_MAX} 次）")
                previous_rows = rows
                previous_signature = self._support_rows_signature(image, previous_rows)
                self._swipe_support_list(rows, direction=1)
                scene, image, _info = self._scene(f"support_scroll{scrolls + 1}")
                scrolls += 1
                rows = vision.find_support_rows(image)
                if not rows:
                    record.verdict = "abort"
                    record.note = f"翻页之后认不出助战行了（判定 {scene.name}）" + self._ap_menu_hint(image)
                    self._abort(record, scene)
                match = evaluate(rows)
                self.log(f"    翻页后：{match.report()}")
                if plain_seen is None and match.plain is not None:
                    plain_seen = match.plain
                # 用**行内容指纹**判"有没有翻动"（整帧像素差会被悬浮动画骗过去：2026-10-17
                # 实测列表到底之后还空滑了 7 次才判出来）。
                if self._support_rows_signature(image, rows) == previous_signature:
                    still += 1
                    self.log(f"    这一次没翻动（第 {still}/{SUPPORT_SCROLL_STILL_TRIES} 次）")
                    if still >= SUPPORT_SCROLL_STILL_TRIES:
                        self.log("    连着翻不动 ⇒ 已经到底了")
                        bottom_reached = True
                        break
                else:
                    still = 0
            for note in match.notes:
                self.log(f"      · {note}")
            if not match.accepted and prefer_grand and plain_seen is not None:
                # 整张列表都没有冠位从者 ⇒ 按用户口径退回普通行：**翻回最上面**重新自证再点
                # （不拿翻页前的旧几何去点，也不点看不见的行）。
                why = "整张列表" if bottom_reached else f"翻满 {scrolls} 屏（还没翻到底）"
                self.log(
                    f"    {why}没见到冠位从者：翻回最上面，退回普通行"
                    f"（首屏候选：第 {plain_seen[0]} 行 {plain_seen[1]:.3f}）"
                )
                image, rows, _moved = self._scroll_support_to_edge(
                    rows, direction=-1, tag="support_scrollback", start_image=image
                )
                if rows:
                    match = vision.match_support_criteria(
                        image, servant_reference, ce_references, rows=rows, prefer_grand=False,
                        extra_servant_references=servant_variants,
                    )
                    self.log(f"    退回普通规则：{match.report()}")
                    if match.accepted:
                        pick_reason = (
                            "（整张列表没有冠位从者，按口径退回普通行）" if bottom_reached
                            else f"（翻满 {scrolls} 屏还没到底也没见到冠位从者，先按口径退回普通行）"
                        )
            if not match.accepted or match.index is None:
                record.verdict = "abort"
                record.note = (
                    f"认不出要选哪一行助战：{match.report()}"
                    f"（已往下翻 {scrolls} 屏也没找到；停下来等人工指行，"
                    "或者在游戏里点「列表更新」刷新列表后重试，不猜）"
                )
                self._abort(record, scene)
            pick = rows[match.index - 1]
        record.point = pick.center
        self.picked_support_row = pick.index
        self.link.tap(pick.center[0], pick.center[1], settle=self.settle)
        pick_note = f"点了第 {pick.index} 行助战 @{pick.center}{pick_reason}"
        # 选完这条助战分两种收尾（2026-10-14 实测）：
        #   * 从「连续出击」过来 ⇒ 直接进本；
        #   * 从地图手动进本过来 ⇒ 先回到「队伍确认」屏，要再点一次「开始任务」。
        # 两条都支持：每轮先看是不是主战斗界面，不然就找「开始任务」按钮（模板匹配，
        # 落点来自匹配位置而不是手量坐标），点过一次就不再点。
        deadline = time.monotonic() + SUPPORT_ENTER_SECONDS
        tapped_start = False
        warned_template = False
        friend_request_clicks = 0
        while True:
            after, after_image, _info = self._scene("support_after")
            if self._dismiss_friend_request(
                after_image, index=index, scene_before=after.name,
                label="关闭好友申请弹窗", tag="选完助战后",
            ):
                friend_request_clicks += 1
                if friend_request_clicks > 2:
                    record.verdict = "abort"
                    record.scene_after = after.name
                    record.note = "连续 3 次关闭好友申请弹窗但画面没有继续推进"
                    self._abort(record, after)
                continue
            if after.name == vision.SCENE_BATTLE_MAIN:
                record.verdict = "ok"
                record.scene_after = after.name
                record.note = (
                    f"{pick_note}，已直接进本（{after.name}）"
                    if not tapped_start
                    else f"{pick_note}，落到「队伍确认」后补点「开始任务」进本（{after.name}）"
                )
                return
            if not tapped_start:
                button = vision.match_button(after_image, START_QUEST_BUTTON)
                if button.accepted and button.center:
                    # 注意：控制台是 GBK，日志里不要用 ⇒ 这类编不出的符号（会直接把整局
                    # 打成 UnicodeEncodeError，2026-10-14 真栽过一次）。
                    self.log(f"    落到「队伍确认」屏：{button.report()}，点它进本")
                    self.link.tap(button.center[0], button.center[1], settle=self.settle)
                    tapped_start = True
                    continue
                if button.notes and not warned_template:
                    self.log(f"    （没登记「开始任务」按钮模板：{button.notes[0]}）")
                    warned_template = True
            if time.monotonic() >= deadline:
                record.verdict = "abort"
                record.scene_after = after.name
                record.note = (
                    f"选了第 {pick.index} 行助战但 {SUPPORT_ENTER_SECONDS:.0f} 秒内没进本"
                    f"（判定 {after.name}，开始任务已点={tapped_start}）"
                )
                self._abort(record, after)
            self.sleeper(SUPPORT_ENTER_WAIT)

    def _enter_quest(self) -> None:
        """冷启动：从当前画面一路把这一局开起来。

        路线（用户 2026-10-14 给的实机路径，每一跳都要模板自证才点）：
          主界面 →「迦勒底之门」→「每日任务」→ 关卡卡片 → （游戏落到「助战选择」）
        点完卡片交给 `_do_support`（选助战 + 必要时补点「开始任务」）。已经在战斗里、
        或者已经在每日任务屏（卡片认得出）时，前面几跳自动跳过。
        """
        scene, image, _info = self._clear_startup_popups()
        if scene.name == vision.SCENE_BATTLE_MAIN:
            self.log("    已经在战斗里了，跳过「点关卡卡片」这一步")
            return
        if vision.find_support_rows(image):
            # 已经在「助战选择」屏上（2026-10-16 用户口径：**可以接受从助战开始刷**）：
            # 有些入口不在"每日任务 → 关卡卡片"那条导航线上（例如冠位战），所以这里不导航、
            # 直接选助战 →（必要时补点「开始任务」）→ 进本，然后照常跑动作流。
            # 注意：这一屏读不到行动力（条在地图屏上），所以这里**不**做 AP 前置检查。
            self.log("    已经在「助战选择」屏上：跳过地图导航，直接选助战进本（这一屏读不到行动力，自己确认 AP）")
            self._do_support(0)
            return
        confirm = vision.match_button(image, GRAND_QUEST_CONFIRM)
        if confirm.accepted and confirm.center:
            self.log("    已经在冠位战挑战确认弹窗上：点「任务开始」后选助战")
            self._do_support(0)
            return
        # 冠位戴冠战的关卡列表（2026-10-17 加）：点这一关的卡片 → 助战选择。
        # 这一屏**有行动力条**，所以先过 AP 闸门（不够就一下都不点）。
        grand_card = vision.match_button(image, GRAND_QUEST_CARD)
        if grand_card.accepted and grand_card.center:
            self.log(f"    冠位战关卡卡片：{grand_card.report()}")
            badge = vision.match_button(image, GRAND_LAST_EXECUTED)
            if badge.accepted and badge.center:
                dx = abs(badge.center[0] - grand_card.center[0])
                dy = abs(badge.center[1] - grand_card.center[1])
                if dx > GRAND_LAST_EXECUTED_MAX_DX or dy > GRAND_LAST_EXECUTED_MAX_DY:
                    raise ExecutionAbort(
                        f"「上次执行」角标不在同一张关卡卡片上（Δ=({dx},{dy})，容差 "
                        f"{GRAND_LAST_EXECUTED_MAX_DX}/{GRAND_LAST_EXECUTED_MAX_DY}）："
                        f"{badge.report()}｜{grand_card.report()}。"
                        "这说明你最近在刷的不是这份 runbook 指的那一关——先确认，别点错关卡。"
                    )
                self.log(f"    「上次执行」角标在同一行 ✓（Δ=({dx},{dy})）：确认这是你最近在刷的那关")
            else:
                self.log(f"    没看到「上次执行」角标（{badge.report()}）：按卡片模板继续")
            self._check_ap_before_start()
            self.link.tap(grand_card.center[0], grand_card.center[1], settle=self.settle)
            self._add(StepRecord(
                index=0, kind="enter_quest", label="点冠位战关卡卡片", turn=0,
                scene_before=scene.name, point=grand_card.center, verdict="ok",
                note=f"点冠位战关卡卡片 @{grand_card.center}（模板分数 {grand_card.score}），交给「选助战」",
            ))
            self._do_support(0)
            return
        # 开刷前先读行动力：不够就别开（这一步不花任何 AP）。读数读不出时不拦。
        self._check_ap_before_start()
        card, scene_name = self._nav_to_daily_screen()
        if card is None or card.center is None:
            raise ExecutionAbort(
                "冷启动导航失败：既不在战斗里，也没能一路走到「每日任务」屏（每跳都要自证，"
                "认不出来就停下等人工）"
            )
        self.log(f"    关卡卡片：{card.report()}")
        self.link.tap(card.center[0], card.center[1], settle=self.settle)
        self._add(StepRecord(
            index=0, kind="enter_quest", label="点关卡卡片", turn=0, scene_before=scene_name,
            point=card.center, verdict="ok",
            note=f"点关卡卡片 @{card.center}（模板分数 {card.score}），进本后交给「选助战」",
        ))
        self._do_support(0)

    def _clear_startup_popups(self) -> tuple[Any, Any, dict[str, Any]]:
        """清掉冷启动弹窗；认不出任何已知关闭按钮就返回当前画面。"""
        scene = image = None
        info: dict[str, Any] = {}
        for attempt in range(1, STARTUP_POPUP_MAX_TAPS + 1):
            tag = "startup_clear" if attempt == 1 else f"startup_clear_r{attempt}"
            scene, image, info = self._scene(tag)
            hit_name = hit_label = ""
            hit = None
            for name, label in STARTUP_POPUPS:
                candidate = vision.match_button(image, name)
                if candidate.accepted and candidate.center:
                    hit_name, hit_label, hit = name, label, candidate
                    break
            if hit is None or hit.center is None:
                return scene, image, info
            self.log(f"    启动弹窗：{label} {hit.report()} ⇒ 点关闭")
            self.link.tap(hit.center[0], hit.center[1], settle=self.settle)
            self._add(StepRecord(
                index=0, kind="startup_clear", label=hit_label, turn=0,
                scene_before=scene.name, point=hit.center, verdict="ok",
                note=f"冷启动清理：点「{hit_label}」@{hit.center}（模板 {hit.score}）",
            ))
            self.sleeper(SUPPORT_LIST_WAIT)
        raise ExecutionAbort(
            f"连续清理 {STARTUP_POPUP_MAX_TAPS} 个启动弹窗后仍有已知弹窗，停止等待人工确认"
        )

    def _check_ap_before_start(self) -> None:
        """开刷前的行动力闸门：只保证**下一局**的 40 AP，不再一次性预占整批。

        2026-10-19 用户口径：规划 4 局但 AP 不足时，应在上限内自动用金苹果，
        而不是要求开局就有 4×40=160 AP。每局开始前用 `_ensure_ap_for_next_round`
        再检查；自然回复不计入估算（保守），苹果用完仍不足就停手。
        """
        reading = self._read_ap_record("开刷前", "pre")
        if reading is not None and reading.estimate is not None:
            self.ap_estimate = int(reading.estimate)
        self._ensure_ap_for_next_round()

    def _needs_apple_for_next_round(self) -> bool:
        return self.ap_estimate is not None and self.ap_estimate + AP_READ_TOLERANCE < AP_PER_RUN

    def _ensure_ap_for_next_round(self) -> None:
        """下一局需要 40 AP；不足时按授权上限自动补金苹果，否则停手。

        这个方法只应在**地图 / 关卡列表**这类有「行动力 ＋」的屏幕调用，因为
        `use_apple()` 需要从行动力行进入补给菜单。连刷中途若判断不足，调用方会先
        点「关闭」回地图，再调用这里。
        """
        if not self._needs_apple_for_next_round():
            return
        if self.apples_used >= self.auto_apple:
            raise ExecutionAbort(
                f"行动力不够：当前约 {self.ap_estimate} AP，而下一局需要 {AP_PER_RUN} AP。"
                f"本次自动补苹果上限 {self.auto_apple} 个，已用 {self.apples_used} 个；"
                "先手动补体力、减少局数，或重新规划后再开刷。"
            )
        if self.log:
            self.log(
                f"    行动力不足（约 {self.ap_estimate} AP，下一局需 {AP_PER_RUN}）："
                f"自动使用黄金果实（第 {self.apples_used + 1}/{self.auto_apple} 个）"
            )
        used = self.use_apple(1)
        if used < 1:
            raise ExecutionAbort(
                "行动力不够，尝试自动使用黄金果实失败（判据不成立）：已停手，"
                "没有继续点关卡或连续出击。"
            )
        self.apples_used += used
        reading = self._read_ap_record("自动补苹果后", "auto_apple_after")
        if reading is not None and reading.estimate is not None:
            self.ap_estimate = int(reading.estimate)
        if self._needs_apple_for_next_round():
            raise ExecutionAbort(
                f"使用 {used} 个黄金果实后行动力仍不足（约 {self.ap_estimate} AP，"
                f"下一局需 {AP_PER_RUN} AP）；停手等人工核对。"
            )

    def _nav_to_daily_screen(
        self, *, stop_at_daily_page: bool = False
    ) -> tuple[vision.ButtonMatch | None, str]:
        """按导航链走到「每日任务」屏。返回（关卡卡片的匹配结果, 最后一帧的画面判定）。"""
        last_scene = ""
        gate_scrolled = False
        for name, label in ENTER_QUEST_NAV:
            for attempt in range(1, ENTER_QUEST_TRIES + 1):
                tag = f"enter_quest_{name}" if attempt == 1 else f"enter_quest_{name}_r{attempt}"
                scene, image, _info = self._scene(tag)
                last_scene = scene.name
                card = vision.match_button(image, ENTER_QUEST_CARD)
                if card.accepted and card.center:
                    self.log(f"    已经在「每日任务」屏（卡片 {card.score:.3f}），跳过「{label}」")
                    return card, scene.name
                if stop_at_daily_page:
                    page_title = vision.match_button(image, DAILY_QUEST_TITLE)
                    if page_title.accepted and page_title.center:
                        self.log(
                            f"    已经到达「每日任务」页（标题 {page_title.score:.3f}）"
                        )
                        return page_title, scene.name
                if name == "chaldea_gate":
                    gate_title = vision.match_button(image, CHALDEA_GATE_TITLE)
                    if gate_title.accepted:
                        self.log(
                            f"    已经在「迦勒底之门」列表（标题 {gate_title.score:.3f}），"
                            "跳过主界面入口，直接找每日任务"
                        )
                        last_scene = scene.name
                        break
                nav = vision.match_button(image, name)
                if (
                    not nav.accepted
                    and name == "daily_quest_entry"
                    and not gate_scrolled
                ):
                    gate_scrolled = True
                    nav, scene, image = self._scroll_gate_to_daily(image)
                if nav.accepted and nav.center:
                    self.log(f"    {label}：模板 {nav.score:.3f} ⇒ 点 {nav.center}")
                    self.link.tap(nav.center[0], nav.center[1], settle=self.settle)
                    self._add(StepRecord(
                        index=0, kind="enter_quest_nav", label=label, turn=0,
                        scene_before=scene.name, point=nav.center, verdict="ok",
                        note=f"冷启动导航：点「{label}」@{nav.center}（模板 {nav.score}）",
                    ))
                    break
                if attempt < ENTER_QUEST_TRIES:
                    self.log(f"    还没看到「{label}」（判定 {scene.name}），{SUPPORT_LIST_WAIT:.0f} 秒后再看")
                    self.sleeper(SUPPORT_LIST_WAIT)
            else:
                self.log(
                    f"    跳不过「{label}」：这一屏既没有每日任务卡片、也认不出该入口"
                    + self._ap_menu_hint(image)
                )
                return None, last_scene
        # 导航链走完（最后一跳是「每日任务」入口）⇒ 再确认卡片
        for attempt in range(1, ENTER_QUEST_TRIES + 1):
            scene, image, _info = self._scene(f"enter_quest_card_probe{attempt}")
            last_scene = scene.name
            card = vision.match_button(image, ENTER_QUEST_CARD)
            if card.accepted and card.center:
                return card, scene.name
            if stop_at_daily_page:
                page_title = vision.match_button(image, DAILY_QUEST_TITLE)
                if page_title.accepted and page_title.center:
                    self.log(
                        f"    已经到达「每日任务」页（标题 {page_title.score:.3f}）"
                    )
                    return page_title, scene.name
            if attempt < ENTER_QUEST_TRIES:
                self.sleeper(SUPPORT_LIST_WAIT)
        self.log("    走到最后也没看到关卡卡片")
        return None, last_scene

    def _scroll_gate_to_daily(
        self, image: Any
    ) -> tuple[vision.ButtonMatch, vision.SceneReading | None, Any]:
        """在「迦勒底之门」列表里向下找每日任务入口；只滑不点入口。"""
        scene = None
        last_image = image
        still = 0
        height, width = image.shape[:2]
        # 起点必须落在列表卡片中段；贴着右侧滚动条滑动在实机不会带动内容。
        x = int(width * 0.62)
        lower = int(height * 0.84)
        upper = int(height * 0.28)
        for attempt in range(1, GATE_SCROLL_MAX + 1):
            self.link.swipe(x, lower, x, upper, settle=self.settle)
            scene, image, _info = self._scene(f"enter_quest_gate_scroll{attempt}")
            hit = vision.match_button(image, "daily_quest_entry")
            if hit.accepted and hit.center:
                self._add(StepRecord(
                    index=0, kind="enter_quest_scroll", label="迦勒底之门列表下滑",
                    turn=0, scene_before=scene.name, point=None, verdict="ok",
                    note=f"下滑 {attempt} 次后找到每日任务入口：{hit.report()}",
                ))
                return hit, scene, image
            delta = vision.region_delta(last_image, image)
            still = still + 1 if delta < GATE_SCROLL_STILL_DELTA else 0
            self._add(StepRecord(
                index=0, kind="enter_quest_scroll", label="迦勒底之门列表下滑",
                turn=0, scene_before=scene.name, point=None, verdict="ok",
                note=f"第 {attempt} 次下滑后仍未看到每日任务入口（画面变化 {delta}）",
            ))
            if still >= GATE_SCROLL_STILL_TRIES:
                break
            last_image = image
        return vision.ButtonMatch(name="daily_quest_entry"), scene, image

    def _wait_for_battle(self, tag: str, what: str, timeout: float = SUPPORT_ENTER_SECONDS) -> None:
        """点完"进本"那一下之后，等画面变成主战斗界面；等不到就 fail-stop。"""
        deadline = time.monotonic() + timeout
        while True:
            scene, _image, _info = self._scene(tag)
            if scene.name == vision.SCENE_BATTLE_MAIN:
                return
            if time.monotonic() >= deadline:
                raise ExecutionAbort(f"{what} 之后 {timeout:.0f} 秒内没进本（当前判定 {scene.name}）")
            self.sleeper(SUPPORT_ENTER_WAIT)

    def _do_start_quest(self) -> None:
        """在「队伍确认」屏点「开始任务」进本（**这一步会真正扣 AP**）。

        自证：模板匹配到登记过的「开始任务」按钮且分数达标，落点取匹配位置（不是手量
        坐标）。匹配不到就停手——绝不盲点右下角。
        """
        scene, image, _info = self._scene("start_quest_before")
        button = vision.match_button(image, START_QUEST_BUTTON)
        self.log(f"    {scene.name}｜{button.report()}")
        for note in button.notes:
            self.log(f"      · {note}")
        if not button.accepted or button.center is None:
            raise ExecutionAbort(f"这一屏没认出自证的「开始任务」按钮：{button.report()}")
        self.link.tap(button.center[0], button.center[1], settle=self.settle)
        self._add(StepRecord(
            index=0, kind="start_quest", label="开始任务", turn=0, scene_before=scene.name,
            point=button.center, verdict="ok",
            note=f"点「开始任务」@{button.center}（按钮模板分数 {button.score}）",
        ))
        self._wait_for_battle("start_quest_after", "点「开始任务」")
        self.records[-1].scene_after = vision.SCENE_BATTLE_MAIN
        self.log("    已进本（主战斗界面就绪）")

    def use_apple(self, count: int = 1, *, from_menu: bool = False) -> int:
        """用 `count` 个黄金果实补行动力（**消耗道具**：只有用户明确授权时才调用）。

        每一步**先自证再点**（三道保险见 `AP_RESTORE_ENTRY` 那段注释），判不出来就停手、
        把手里的画面与理由留在日志和证据里。返回**实际用掉**的个数。

        `from_menu=True`：当前画面已经是「行动力回复」菜单（例如点「连续出击」后
        AP 不足，游戏直接弹出的那一屏）；此时跳过地图上的「行动力 ＋」入口，直接
        认黄金果实行。
        """
        used = 0
        for order in range(1, max(1, int(count)) + 1):
            if not from_menu:
                entry = vision.ButtonMatch(name=AP_RESTORE_ENTRY)
                for attempt in range(1, APPLE_ENTRY_TRIES + 1):
                    tag = f"apple{order}_entry" if attempt == 1 else f"apple{order}_entry_r{attempt}"
                    entry_frame, _ = self._shot(tag)
                    entry = vision.match_button(entry_frame, AP_RESTORE_ENTRY)
                    if entry.accepted and entry.center:
                        break
                    if attempt < APPLE_ENTRY_TRIES:
                        self.log(
                            f"  补给 {order}：{entry.report()}——画面可能还在转场，"
                            f"{APPLE_ENTRY_WAIT:.1f} 秒后重试（{attempt}/{APPLE_ENTRY_TRIES}）"
                        )
                        self.sleeper(APPLE_ENTRY_WAIT)
                if not entry.accepted or not entry.center:
                    self.log(f"  补给 {order}：{entry.report()}——认不出「行动力」行里的 ＋，停手（不点）")
                    break
                self.log(f"  补给 {order}：{entry.report()}")
                self.link.tap(entry.center[0], entry.center[1], settle=self.settle)
            menu_frame, _ = self._shot(f"apple{order}_menu")
            row = vision.match_button(menu_frame, AP_APPLE_ROW)
            if not row.accepted or not row.center:
                self.log(f"  补给 {order}：{row.report()}——没认出自证的「黄金果实」行，停手"
                         "（菜单最上面是圣晶石，绝不猜着点）")
                break
            self.log(f"  补给 {order}：{row.report()}")
            self.link.tap(row.center[0], row.center[1], settle=self.settle)
            confirm_frame, _ = self._shot(f"apple{order}_confirm")
            title = vision.match_button(confirm_frame, AP_APPLE_CONFIRM_TEXT)
            ok = vision.match_button(confirm_frame, AP_APPLE_CONFIRM_OK)
            self.log(f"  补给 {order}：确认弹窗 标题 {title.score:.3f}｜「决定」 {ok.score:.3f}")
            if not (title.accepted and ok.accepted and ok.center):
                self.log("  补给：确认弹窗没同时认出「消耗1个黄金果实」与「决定」，停手（不猜着点）")
                break
            self.link.tap(ok.center[0], ok.center[1], settle=self.settle)
            used += 1
            after_frame, _ = self._shot(f"apple{order}_after")
            delta = vision.region_delta(menu_frame, after_frame)
            self.log(f"  补给 {order}：已点「决定」@{ok.center}（变化 {delta}）")
            entry_note = (
                "补给菜单已打开 → "
                if from_menu
                else f"三道自证：＋ {entry.score:.3f}@{entry.center} → "
            )
            self._add(StepRecord(
                index=0, kind="apple", label=f"黄金果实补给（第 {order} 个）", turn=0,
                scene_before="", point=ok.center, region_delta=delta, verdict="ok",
                note=f"{entry_note}黄金果实行 {row.score:.3f}"
                     f"@{row.center} → 标题 {title.score:.3f} + 「决定」 {ok.score:.3f}@{ok.center}",
            ))
        if used and not from_menu:
            self._read_ap_record("补给后", "after_apple")
        return used

    def _handle_ap_restore_menu(self, index: int) -> bool:
        """点「连续出击」后若 AP 不足，游戏会直接弹「行动力回复」菜单。

        2026-10-19 用户口径：不要先关闭弹窗回地图；就在这个菜单里用黄金果实。
        返回 True 表示确实处理了这个菜单。没开自动苹果时停手，不点圣晶石。
        """
        image, _ = self._shot("ap_restore_menu_check")
        row = vision.match_button(image, AP_APPLE_ROW)
        if not (row.accepted and row.center):
            return False
        self.log(f"    连续出击后弹出「行动力回复」菜单：{row.report()}")
        if self.apples_used >= self.auto_apple:
            raise ExecutionAbort(
                f"AP 不足，游戏已弹出「行动力回复」菜单；本次自动补苹果上限 "
                f"{self.auto_apple} 个，已用 {self.apples_used} 个。"
                "停手，等人工补体力或减少局数。"
            )
        used = self.use_apple(1, from_menu=True)
        if used < 1:
            raise ExecutionAbort(
                "AP 不足，尝试在「行动力回复」菜单使用黄金果实失败（判据不成立）；"
                "停手等人工核对，没有点圣晶石。"
            )
        self.apples_used += used
        self.log(
            f"    已在「行动力回复」菜单使用 {used} 个黄金果实"
            f"（本次累计 {self.apples_used}/{self.auto_apple}）"
        )
        # 有些布局在用完苹果后会回到「是否连续进行同一关卡？」弹窗，而不是
        # 直接进助战屏；此时补点一次右「连续出击」。认不出就交给后面的
        # `_do_support` 继续自证，不盲点。
        after, _ = self._shot("ap_restore_after_apple")
        again = vision.match_button(after, WRAP_REPEAT_BUTTON)
        if again.accepted and again.center:
            self.log(f"    补给后仍停在连续出击弹窗：{again.report()} ⇒ 再点一次")
            self.link.tap(again.center[0], again.center[1], settle=self.settle)
            self.sleeper(SUPPORT_LIST_WAIT)
        return True

    def _do_wrap(self, index: int, continue_farming: bool = False) -> None:
        """打完之后把结算页收尾回活动地图（或接着刷下一局）。

        每一步**先自证再点**：认得出去右下「下一步」按钮就点它命中的中心，认得出
        「连续出击」弹窗就按本局意图点「关闭」或「连续出击」，都认不出才退回"点面板
        任意处推进"。每次点完都看"有没有反应"：连着两次没反应就停手，把现场留给人工
        ——宁可少点一步，也绝不接着盲点。唯一的 AP 陷阱是弹窗右侧「连续出击」：默认
        点左侧「关闭」（不耗 AP），只有 `--repeat` 或连刷（continue_farming / rounds>1）
        才点右侧。
        """
        # 只看**调用方这次的意图**：连刷的中间局（continue_farming）或老的 --repeat。
        # 注意别把 pick_support 算进来：连刷时它会被自动打开，但**最后一局**必须点左
        # 「关闭」——2026-10-14 真机就是这样多花了一次 40 AP 开了下一局。
        repeat_like = continue_farming or self.repeat
        still = 0
        point: tuple[int, int] = WRAP_ADVANCE_POINT
        for order in range(1, WRAP_MAX_STEPS + 1):
            before, _ = self._shot(f"wrap{order}_before")
            if self._dismiss_friend_request(
                before, index=index, scene_before="",
                label="关闭好友申请弹窗", tag=f"收尾 {order}",
            ):
                still = 0
                continue
            close = vision.match_button(before, WRAP_CLOSE_BUTTON)
            again = vision.match_button(before, WRAP_REPEAT_BUTTON)
            if close.accepted or again.accepted:
                # 「是否连续进行同一关卡？」弹窗。要点的那个按钮必须自己命中——识别不出
                # 就不点（宁可停手；点错右侧就是白扣 40 AP）。
                target = again if repeat_like else close
                if not target.accepted:
                    self.log(f"  收尾 {order}：认出「连续出击」弹窗，但要点的按钮没命中：{target.report()}")
                    self.log("  收尾：判不出来，停手（不盲点，剩下交给人工核对）")
                    return
                suffix = "repeat" if repeat_like else "close"
                label, point, kind = f"wrap{order}_{suffix}", target.center, "dialog"
                hit = f"认出「连续出击」弹窗，点的是 {target.report()}"
            else:
                next_button = vision.match_button(before, WRAP_NEXT_BUTTON)
                if next_button.accepted:
                    label, point, kind = f"wrap{order}_next", next_button.center, "advance"
                    hit = f"认出「下一步」（{next_button.report()}）"
                else:
                    label, point, kind = f"wrap{order}_advance", WRAP_ADVANCE_POINT, "advance"
                    hit = "这一步既没有「下一步」也没有「连续出击」弹窗：按“点面板任意处推进”处理"
            try:
                self.link.tap(point[0], point[1], settle=self.settle)
            except Exception as exc:  # 设备链路问题不该掩盖收尾本身
                self.log(f"  收尾 {order}/{WRAP_MAX_STEPS} {label} 点击失败：{exc}")
                return
            after, _ = self._shot(f"{label}_after")
            delta = vision.region_delta(before, after)
            self.log(f"  收尾 {order}/{WRAP_MAX_STEPS} {label} @{point} 变化 {delta}｜{hit}")
            if kind == "dialog":
                break
            if delta < WRAP_MIN_DELTA:
                still += 1
                self.log(f"  收尾：这一步几乎没有变化（第 {still} 次）")
                if still >= WRAP_STOP_AFTER_STILL:
                    self.log("  收尾：连着几步都没反应，停手（剩下交给人工核对）")
                    return
            else:
                still = 0
        else:
            self.log(f"  收尾：走了 {WRAP_MAX_STEPS} 步都没认出「连续出击」弹窗，停手（剩下交给人工核对）")
            return
        # 证据里写清**这一步到底点了哪边**：连刷的最后一局 `pick_support` 仍然是打开
        # 状态，但那是给"还要接着刷的中间局"用的，最后一局点的是左「关闭」（2026-10-16
        # 修：原来的写法会让最后一局的证据写着"点了连续出击"，与事实不符）。
        if repeat_like:
            note = "结果页已收尾，点了右侧「连续出击」（会再耗一次 AP）"
            note += "；接着由执行器选助战" if self.pick_support else "，下一轮回到「助战选择」"
        else:
            note = "结果页已收尾（连续出击弹窗点的是左侧「关闭」，未消耗 AP）"
        if repeat_like:
            # 记下点完之后游戏落在哪：这是"确实又开了新一局"的证据（2026-10-14 实测落在
            # 「助战选择」，说明连续出击会重新走一遍进本流程）。
            self._scene("repeat_after_click")
        self._add(StepRecord(
            index=index, kind="wrap", label="结算页收尾", turn=self.records[-1].turn if self.records else 0,
            scene_before="", verdict="ok", note=note,
        ))

    def _write_log(self, plan: plan_mod.ExecutionPlan | None) -> None:
        payload = {
            "run_id": self.run_id,
            "support": {
                "key": self.support_key,
                "forced_row": self.support_row,
                "picked_row": self.picked_support_row,
            },
            "auto_apple": self.auto_apple,
            "apples_used": self.apples_used,
            "dry_run": self.dry_run,
            "quest_id": plan.quest_id if plan else None,
            "layout_source": self.layout.source,
            "steps": [asdict(record) for record in self.records],
        }
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            (self.run_dir / "steps.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass


def preflight(link: DeviceLink, plan: plan_mod.ExecutionPlan, layout: SessionLayout,
              runner: BattleRunner | None = None, start_at: int = 1,
              tries: int = 3, retry_wait: float = 2.0) -> dict[str, Any]:
    """零点击自检：现在能不能起步？不能就直说原因（不改游戏状态）。"""
    # 每次自检用自己的目录名（原来固定叫 "preflight"，多跑几次会互相覆盖证据截图——
    # 2026-10-14 就因此把一张助战屏的模板源覆盖成了战斗帧）。
    runner = runner or BattleRunner(
        link, layout, run_id=datetime.now().strftime("preflight-%Y%m%d-%H%M%S"), dry_run=True
    )
    # 续跑（start_at > 1）时自检的对象是**要接着跑的那个动作**，不是整个计划的第 1 个动作
    first = plan.actions[start_at - 1] if 0 < start_at <= len(plan.actions) else None
    scene = image = None
    info = {}
    # 换面 / 结算渐入的过场帧会被判成 other（2026-10-13 实测：preflight 恰好落在换面
    # 瞬间，亮度 159、按钮还没绘出，于是误判"不能起步"）。所以这里**短暂重试**：
    # 只有连续几次都拿不到期望画面，才认定真的不能起步。
    for attempt in range(1, max(1, tries) + 1):
        scene, image, info = runner._scene("preflight" if attempt == 1 else f"preflight_r{attempt}")
        expected = first.expect_before if first is not None else plan_mod.SCENE_ANY
        if expected == plan_mod.SCENE_ANY or scene.name == expected or scene.name != vision.SCENE_OTHER:
            break
        if attempt < tries:
            runner.log(f"    当前是过场帧（other），{retry_wait:.0f} 秒后再看一次")
            time.sleep(retry_wait)
    report: dict[str, Any] = {
        "scene": scene.name,
        "scene_report": scene.report(),
        "display": link.display,
        "ready": False,
        "shot": info.get("path"),
    }
    if first is None:
        report["note"] = "动作流是空的"
        return report
    report["first_action"] = f"{first.label}（期望前态 {first.expect_before}）"
    report["ready"] = first.expect_before == plan_mod.SCENE_ANY or scene.name == first.expect_before
    if not report["ready"]:
        report["note"] = f"当前画面是 {scene.name}，不是 {first.expect_before}，不能起步"
        return report
    if first.kind == plan_mod.SKILL:
        point = layout.skill_point(int(first.actor_slot or 0), int(first.skill_index or 0))
        score = vision.icon_like_score(image, point)
        report["first_point"] = point
        report["first_point_icon_score"] = score
    return report


def parse_ce_specs(specs: list[str] | tuple[str, ...], default_row: int) -> list[tuple[str, int]]:
    """把 CLI / 接口里的礼装登记项解析成 `(名字, 取哪一行的礼装条)`。

    写法：`名字`（就用 `default_row` 那一行）或 `名字:行号`（取另一行的礼装条，
    用于"想登记的礼装不在被指的那一行"的情形）。名字里带冒号就按整串当名字。
    """
    wanted: list[tuple[str, int]] = []
    for raw in specs:
        text = str(raw or "").strip()
        if not text:
            continue
        name, _, tail = text.rpartition(":")
        if name.strip() and tail.strip().isdigit():
            wanted.append((name.strip(), int(tail)))
        else:
            wanted.append((text, int(default_row)))
    return wanted


def register_support(
    link: DeviceLink,
    *,
    row: int,
    servant_name: str = "",
    ce_specs: list[str] | tuple[str, ...] = (),
    run_id: str | None = None,
    tries: int = SUPPORT_LIST_TRIES,
    wait: float = SUPPORT_LIST_WAIT,
    sleeper: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """零点击登记助战指纹：当前画面**必须**是「助战选择」屏。

    把第 `row` 行的**从者指纹**（「宝具 名称 等级N」那一行）存成 `servant_name`，
    把左块下半的**礼装条**存成 `ce_specs` 里的名字（`名字[:行号]`）。
    **只截图 + 存图，一下都不点** ⇒ 不花 AP、也不改游戏状态（所以可以随时做）。
    屏不对 / 行号越界 / 没给名字，一律 fail-stop 说清原因，绝不猜也别拿别的行顶上。
    """
    wanted = parse_ce_specs(ce_specs, row)
    servant_name = str(servant_name or "").strip()
    if not servant_name and not wanted:
        raise ExecutionAbort("登记要给至少一个名字：从者名 和/或 礼装名（`名字[:行号]`）。")
    run_root = Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "runs" / (
        run_id or datetime.now().strftime("register-%Y%m%d-%H%M%S")
    )
    run_root.mkdir(parents=True, exist_ok=True)
    scene = image = None
    info: dict[str, Any] = {}
    rows: list[vision.SupportRow] = []
    for attempt in range(1, max(1, int(tries)) + 1):
        tag = "register_support" if attempt == 1 else f"register_support_r{attempt}"
        info = link.shot(run_root / f"{attempt:03d}_{tag}")
        image = vision.load(info["path"])
        scene = vision.read_scene(image)
        log(f"    [{tag}] {scene.report()}")
        rows = vision.find_support_rows(image)
        if rows:
            break
        if attempt < tries:
            log(f"    还没看到助战列表（判定 {scene.name}），{wait:.0f} 秒后再看一次")
            sleeper(wait)
    assert scene is not None and image is not None
    if not rows:
        raise ExecutionAbort(
            f"当前画面不是「助战选择」屏（判定 {scene.name}）：登记要先停在助战屏上。一下都没点。"
        )
    log("    助战行：" + "；".join(item.report() for item in rows))
    out_of_range = [
        what for what, source_row in
        ([("从者", int(row))] if servant_name else [])
        + [(f"礼装「{name}」", source_row) for name, source_row in wanted]
        if not 1 <= source_row <= len(rows)
    ]
    if out_of_range:
        raise ExecutionAbort(
            f"这一帧只看到 {len(rows)} 行助战，但 {('/'.join(out_of_range))} 指的行号不在里面："
            "先在游戏里把它滚到可见范围再登记（一个指纹都没写）。"
        )

    def scores(kind: str, name: str, pick: Callable[[vision.SupportRow], tuple[int, int, int, int]],
               shift: int) -> dict[str, float]:
        """读回刚存进库的指纹，对每一行打分 —— 用来当场自证"判别力够不够"。"""
        reference = vision.load_support_library(kind).get(name)
        if reference is None:
            return {}
        return {
            str(item.index): round(vision.best_shifted_ncc(image, pick(item), reference, shift), 3)
            for item in rows
        }

    report: dict[str, Any] = {
        "ok": True,
        "row": int(row),
        "rows_seen": len(rows),
        "scene": scene.name,
        "shot": info.get("path"),
        "saved": [],
        "discrimination": {},
    }
    note = f"登记自第 {int(row)} 行（run {run_root.name}）"
    if servant_name:
        meta = vision.save_support_library_entry("servant", servant_name, image, rows[row - 1].identity, note=note)
        report["saved"].append({"kind": "servant", "name": servant_name, "meta": meta.name, "source_row": int(row)})
        report["discrimination"][f"从者 {servant_name}"] = scores(
            "servant", servant_name, lambda item: item.identity, vision.SUPPORT_SHIFT
        )
    for name, source_row in wanted:
        meta = vision.save_support_library_entry(
            "ce", name, image, rows[source_row - 1].ce, note=f"登记自第 {source_row} 行（run {run_root.name}）"
        )
        report["saved"].append({"kind": "ce", "name": name, "meta": meta.name, "source_row": int(source_row)})
        report["discrimination"][f"礼装 {name}"] = scores(
            "ce", name, lambda item: item.ce, vision.SUPPORT_CE_SHIFT
        )
    return report


def normalize_run_args(args: Any) -> int:
    """把 `--repeat` / `--rounds` / `--pick-support` 三个开关归一；非法组合返回非 0。

    2026-10-15 统一口径：**`--repeat` 就是 `--rounds 2` 的旧写法**。此前 `--repeat` 的意思是
    "打完这局点右「连续出击」再选个助战就停"——那会在没打下一局的情况下先扣掉 40 AP，语义既
    难解释又和 `--rounds` 打架，所以取消这种模式；两个开关表达同一件事，只是 `--rounds N`
    能表达 N 局。
    """
    if args.rounds < 1:
        print("--rounds 必须 ≥ 1。")
        return 2
    if args.repeat:
        if args.rounds > 1:
            print("--repeat 与 --rounds 互斥：--repeat 就是 --rounds 2 的旧写法。")
            return 2
        print("--repeat 等价于 --rounds 2（连刷 2 局，每局都真实扣 AP）。")
        args.rounds = 2
        args.repeat = False
    if args.pick_support and args.rounds < 2:
        print("--pick-support 只在连刷（--rounds ≥ 2）时有意义：单局不需要选第二次助战。")
        return 2
    if args.rounds > 1 and not args.pick_support:
        print(f"连刷 {args.rounds} 局需要选助战 ⇒ 自动打开 --pick-support。")
        args.pick_support = True
    return 0


def _register_support_cli(args: Any) -> int:
    """CLI 的登记模式：零点击（不花 AP），只截图 + 把指纹写进库。

    报告以 `REGISTER_REPORT {json}` 一行打出来 —— 后端按这个标记取结构化结果给界面。
    """
    run_id = args.run_id or datetime.now().strftime("register-%Y%m%d-%H%M%S")
    lease = DeviceLease(job_id=run_id)
    if not lease.acquire():
        print(f"模拟器 / 设备通道正被别的任务占着，先不登记：{lease.note}")
        return 4
    try:
        link = DeviceLink()
        with link:
            print(f"设备：{link.display}")
            print("登记模式：只截图 + 存指纹，一下都不点（不花 AP、不改游戏状态）。")
            try:
                report = register_support(
                    link,
                    row=int(args.support_row or 1),
                    servant_name=args.servant,
                    ce_specs=list(args.ce),
                    run_id=run_id,
                )
            except ExecutionAbort as exc:
                print(f"已按判据停下：{exc}")
                return 4
    finally:
        lease.release()
    for item in report["saved"]:
        print(f"  已登记「{item['name']}」（{item['kind']}，取自第 {item['source_row']} 行）：{item['meta']}")
    for label, detail in report["discrimination"].items():
        print(f"  {label} 判别力：" + "、".join(f"第{key}行 {value:.3f}" for key, value in detail.items()))
    print(f"REGISTER_REPORT {json.dumps(report, ensure_ascii=False)}")
    print(f"登记完成（run {run_id}）：一下都没点。")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI：默认只做零点击自检；真的要打必须显式给 --execute。"""
    import argparse

    # 控制台是 GBK：日志里万一混进编不出的符号（⇒ 之类），默认会抛 UnicodeEncodeError
    # 把整局打断、还把设备留在半路（2026-10-14 实测）。这里降级成替换字符，永不因打印崩。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="按指定配队跑一局（执行层 = FGO-py）")
    parser.add_argument(
        "spec",
        nargs="?",
        default="",
        help="轮转 spec JSON（只有 --register-support 模式可以不填）",
    )
    parser.add_argument(
        "layout",
        nargs="?",
        default="",
        help="本会话坐标 JSON（只有 --register-support 模式可以不填）",
    )
    parser.add_argument(
        "--register-support",
        action="store_true",
        help="零点击登记：当前画面必须是「助战选择」屏，把第 N 行的从者/礼装指纹存进指纹库"
             "（配合 --servant / --ce；**一下都不点**、不花 AP，所以默认就可以跑）",
    )
    parser.add_argument(
        "--servant",
        default="",
        help="配合 --register-support：把所选那一行的从者指纹存成这个名字",
    )
    parser.add_argument(
        "--ce",
        action="append",
        default=[],
        help="配合 --register-support：把礼装条存成这个名字（可重复）；`名字:行号` 表示取另一行的礼装",
    )
    parser.add_argument("--execute", action="store_true", help="真的点击（默认只自检）")
    parser.add_argument("--stop-at", type=int, default=0, help="执行到第 N 个动作之前停下（1-based）")
    parser.add_argument("--start-at", type=int, default=1, help="从第 N 个动作开始（1-based，暂停后续跑用）")
    parser.add_argument("--no-wrap", action="store_true", help="打完后不自动收尾结算页（默认收尾）")
    parser.add_argument(
        "--wrap-only",
        action="store_true",
        help="只做结算页收尾：当前画面必须是结果页或「连续出击」弹窗；默认点左「关闭」"
             "（**不消耗 AP**）。收尾中途停手后，用它把留在结果页的设备送回地图",
    )
    parser.add_argument(
        "--use-apple",
        type=int,
        default=0,
        help="先用 N 个黄金果实补行动力（**消耗道具**，只有用户明确授权时才用）：当前画面必须"
             "是能看到「行动力」行 ＋ 的地图/关卡屏；只做这一步就退出（之后另跑一次刷本）",
    )
    parser.add_argument(
        "--auto-apple",
        type=int,
        default=0,
        help="AP 不足时自动使用黄金果实，**最多 N 个**（0-3；消耗道具）。与 --use-apple 不同，"
             "它会在连刷过程中按需补给并继续，不会补完就退出",
    )
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="旧写法，等价于 --rounds 2（连刷 2 局，**每局都真实扣 AP**）；单局默认点左「关闭」不耗 AP",
    )
    parser.add_argument(
        "--support-row",
        type=int,
        default=0,
        help="首次登记：这次强制取第 N 行助战，并把它的身份块指纹存下来（以后自动认这一行）",
    )
    parser.add_argument(
        "--pick-support",
        action="store_true",
        help="连刷时自动选助战（--rounds ≥ 2 会自动打开；单局给这个开关是错的）",
    )
    parser.add_argument(
        "--pick-support-only",
        action="store_true",
        help="只做「选助战」这一步（当前画面必须就是助战选择屏），用于首次登记与验收",
    )
    parser.add_argument(
        "--start-quest-only",
        action="store_true",
        help="只做「开始任务」这一步（当前画面必须是队伍确认屏；**会真正扣 AP**）",
    )
    parser.add_argument(
        "--enter-quest",
        action="store_true",
        help="冷启动：先在每日任务地图上点关卡卡片把这一局开起来（已在战斗里则跳过），再跑动作流",
    )
    parser.add_argument(
        "--nav-only",
        action="store_true",
        help="只清启动弹窗并导航到「每日任务」关卡卡片，**不点关卡、不花 AP**；用于 C15 冷启动验收",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="连刷 N 局（默认 1）。第 1..N-1 局收尾点右「连续出击」+ 选助战直接进下一局，"
             "最后一局点左「关闭」回地图；**每局都真实扣 AP**（与 --repeat 互斥）",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="指定本次运行的证据目录名（默认按时间戳生成）；后端接口按它定位 runs/<run_id>/",
    )
    args = parser.parse_args(argv)

    if args.register_support:
        return _register_support_cli(args)

    if not args.spec or not args.layout:
        print("正常跑一局要给 spec 和 layout 两个参数（只有 --register-support 模式可以不填）。")
        return 2

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    plan = plan_mod.compile_plan(spec)
    layout = SessionLayout.load(args.layout)
    print(plan.summary())
    invalid = normalize_run_args(args)
    if invalid:
        return invalid
    if args.rounds > 1:
        print(f"注意：这次连刷 {args.rounds} 局，每局都真实扣 AP。")
    if args.auto_apple < 0 or args.auto_apple > 3:
        print("--auto-apple 只允许 0-3 个（用户授权上限 3 个）。")
        return 2

    link = DeviceLink()
    with link:
        print(f"设备：{link.display}")
        runner = BattleRunner(
            link, layout, wrap=not args.no_wrap, repeat=args.repeat,
            pick_support=args.pick_support, support_row=args.support_row or None,
            support_key=plan.quest_id, rounds=args.rounds, enter_quest=args.enter_quest,
            run_id=args.run_id or None,
            support_criteria=spec.get("support") or None,
            auto_apple=args.auto_apple,
        )
        if args.nav_only:
            try:
                scene, _image, _info = runner._clear_startup_popups()
                if scene.name == vision.SCENE_BATTLE_MAIN:
                    print("当前已经在战斗内：跳过导航验收。")
                    return 0
                card, scene_name = runner._nav_to_daily_screen(stop_at_daily_page=True)
                if card is None or card.center is None:
                    print(f"导航未到达「每日任务」关卡卡片（最后判定 {scene_name}）：未点关卡、未花 AP。")
                    return 4
                if card.name == DAILY_QUEST_TITLE:
                    print(
                        f"导航验收通过：已到「每日任务」页面（标题 {card.center}，模板 {card.score}）；"
                        "未点关卡、未花 AP。"
                    )
                else:
                    print(
                        f"导航验收通过：已到每日任务关卡卡片 {card.center}"
                        f"（模板 {card.score}）；未点关卡、未花 AP。"
                    )
                return 0
            except ExecutionAbort as exc:
                print(f"已按判据停下：{exc}")
                return 4
        if args.pick_support_only:
            # 只做「选助战」：当前画面必须就是助战选择屏（不自检战斗界面）。
            print("只做「选助战」：当前画面必须就是助战选择屏。")
            try:
                runner._do_support(0)
            except ExecutionAbort as exc:
                print(f"已按判据停下：{exc}")
                return 4
            print(f"已选第 {runner.picked_support_row} 行助战并进本。")
            return 0
        if args.wrap_only:
            # 只做收尾：设备停在结果页 / 「连续出击」弹窗时把它送回地图。默认点左
            # 「关闭」，**不花 AP**。判不出来就停手（`_do_wrap` 自己会停，不在这里抛）。
            print("只做结算页收尾：点左「关闭」回地图（不消耗 AP）。")
            runner._do_wrap(0, continue_farming=False)
            if any(record.kind == "wrap" for record in runner.records):
                print("收尾完成。")
                return 0
            print("收尾没走完（判据不成立或点了没反应）：现场留给人工核对。")
            return 4
        if args.use_apple:
            # 只做补给：**消耗道具**，所以必须显式给 `--use-apple N`；补完就退出（刷本另跑一次）。
            print(f"补给：准备使用 {args.use_apple} 个黄金果实（**会消耗道具**）。")
            used = runner.use_apple(args.use_apple)
            if used < args.use_apple:
                print(f"只补上 {used} 个就停手了（判据不成立）：现场留给人工核对。")
                return 4
            print(f"补给完成：用掉 {used} 个黄金果实。")
            return 0
        if args.start_quest_only:
            print("只做「开始任务」：当前画面必须是队伍确认屏（这一步会真正扣 AP）。")
            try:
                runner._do_start_quest()
            except ExecutionAbort as exc:
                print(f"已按判据停下：{exc}")
                return 4
            return 0
        if args.enter_quest:
            # 冷启动时当前画面是地图，不能按"第 1 个动作的期望前态"自检；改成零点击检查
            # 「关卡卡片」模板在不在（已经在战斗里也算通过，进本那步会跳过）。
            scene, image, info = runner._scene("preflight_enter_quest")
            card = vision.match_button(image, ENTER_QUEST_CARD)
            grand_card = vision.match_button(image, GRAND_QUEST_CARD)
            grand_confirm = vision.match_button(image, GRAND_QUEST_CONFIRM)
            badge = vision.match_button(image, GRAND_LAST_EXECUTED)
            already_in_battle = scene.name == vision.SCENE_BATTLE_MAIN
            nav_ready = None
            for name, label in ENTER_QUEST_NAV:
                hit = vision.match_button(image, name)
                if hit.accepted:
                    nav_ready = f"{label}（{hit.score:.3f}）"
                    break
            report = {
                "scene": scene.name,
                "enter_quest_ready": bool(
                    already_in_battle or card.accepted or grand_card.accepted or grand_confirm.accepted
                ),
                "in_battle_already": already_in_battle,
                "card": card.report(),
                "grand_card": grand_card.report(),
                "grand_confirm": grand_confirm.report(),
                "last_executed": badge.report(),
                "nav_step_available": nav_ready or "无（既不在每日任务屏，也不在主界面/迦勒底之门那两跳上）",
                "display": link.display,
                "ready": True,
                "shot": info.get("path"),
            }
        else:
            report = preflight(link, plan, layout, start_at=args.start_at)
        for key, value in report.items():
            print(f"  {key}: {value}")
        if not report.get("ready"):
            print("自检未通过：不起步（这是期望行为，不是错误）")
            return 3
        if not args.execute:
            print("自检通过。要真的执行请加 --execute。")
            return 0
        try:
            runner.run(plan, start_at=args.start_at, stop_at=args.stop_at)
        except ExecutionAbort as exc:
            print(f"已按判据停下：{exc}")
            return 4
        except DeviceLinkError as exc:
            # 设备链路断了（模拟器崩了 / 驱动进程死了）：说清停在哪，别抛一堆栈让调用方猜。
            # 2026-10-16 真机撞到过一次（FGO-py 驱动侧的 Fuse 计数器把进程打断）。
            print(f"设备链路断了，已停手：{exc}")
            print("设备停在当时画面，需要人工确认（可以用 --start-at N 从断掉的那一步续跑）。")
            return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
