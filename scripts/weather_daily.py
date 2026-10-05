from datetime import datetime
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from logging.handlers import TimedRotatingFileHandler
import requests
import subprocess
import logging
import re

# ==== 配置区 ====
# 地区的纬度
LAT = 30.11
# 地区的经度
LON = 116.89
# 本地git仓库完整路径，r 防止转义
REPO_PATH = Path(r"D:\git\daily-notes")
# 统一使用东八区时间，避免本机时区与API 时区不一致
TIMEZONE = "Asia/Shanghai"
# 获取当前时间，格式化为：年/月/日 例如"2026-09-28"
today = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")
# 拼接笔记名：例如"2026-09-28.md"
md_filename = f"{today}.md"
# 笔记存放文件夹
NOTES_DIR = REPO_PATH / "notes"
# 拼接完整笔记路径
md_full_path = NOTES_DIR / md_filename
# 日志存放文件夹
LOG_DIR = REPO_PATH / "logs"
# 日志文件路径
LOG_FILE = Path(LOG_DIR) / "weather_run.log"
# 日志保留配置
LOG_BACKUP_DAYS = 30   # 保留最近30天的日志，更早的自动删除
LOG_ROTATE_INTERVAL = "D"   # 切割 D=天；H=小时；M=分钟
# 标记常量
MARKER_TEMPLATE = "<!-- daily-note-{date} -->"
WEATHER_START = "<!-- weather-start -->"
WEATHER_END = "<!-- weather-end -->"
PLAN_START = "<!-- plan-start -->"
PLAN_END = "<!-- plan-end -->"
# ==== ==== ==== ====

REPO_PATH_OBJ = Path(REPO_PATH)
if not REPO_PATH_OBJ.exists():
    raise FileNotFoundError(f"仓库路径不存在:{REPO_PATH}")

NOTES_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
# 日志初始化配置
# 输出到 文件 + 控制台；每条日志带时间、级别、消息
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = TimedRotatingFileHandler(
        filename=LOG_FILE,
        when=LOG_ROTATE_INTERVAL,
        backupCount=LOG_BACKUP_DAYS,
        encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(fmt)

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# 获取天气数据
def get_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min"],
        "current": ["temperature_2m", "relative_humidity_2m", "weather_code"],
        "timezone": TIMEZONE
    }
    logger.info("开始请求天气API")
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()   # 非 2xx 直接异常，避免拿到错误页面还继续解析
    try:
        data = resp.json()
    except ValueError as e:
        logger.error(f"API 返回不合法 JSON:{resp.text[:200]}")
        raise ValueError(f"API 返回不合法 JSON:{resp.text[:200]}") from e

    # 校验返回结构，避免API 改版/限流时直接 KeyError
    if "current" not in data or "daily" not in data:
        logger.error(f"API 返回结构异常：{data}")
        raise ValueError(f"API 返回结构异常：{data}")
    current = data["current"]
    daily = data["daily"]
    required = ["temperature_2m", "relative_humidity_2m", "weather_code"]
    if not all(k in current for k in required):
        logger.error(f"current 缺少字段：{current}")
        raise ValueError(f"current 缺少字段:{current}")
    if not daily["temperature_2m_max"] or not daily["temperature_2m_min"]:
        logger.error("API 返回的 daily 数据缺失")
        raise ValueError("API 返回的 daily 数据缺失")

    weather_map = {
        0: "☀️ 晴天", 1: "🌤 大部晴朗", 2: "⛅ 多云", 3: "☁️ 阴天",
        45: "🌫 雾", 48: "🌫 霜雾",
        51: "🌧 小毛毛雨", 53: "🌧 中毛毛雨", 55: "🌧 大毛毛雨",
        56: "🌧 冻毛毛雨（轻）", 57: "🌧 冻毛毛雨（强）",
        61: "🌧 小雨", 63: "🌧 中雨", 65: "🌧 大雨",
        66: "🌧 冻雨（轻）", 67: "🌧 冻雨（强）",
        71: "❄️ 小雪", 73: "❄️ 中雪", 75: "❄️ 大雪", 77: "❄️ 雪粒",
        80: "🌦 小阵雨", 81: "🌦 中阵雨", 82: "⛈ 强阵雨",
        85: "🌨 小阵雪", 86: "🌨 大阵雪",
        95: "⛈ 雷暴", 96: "⛈ 雷暴伴小冰雹", 99: "⛈ 雷暴伴大冰雹",
    }

    weather_text = weather_map.get(current["weather_code"], "❓未知天气")

    weather_info = {
        "weather": weather_text,
        "temp_now": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "temp_max": daily["temperature_2m_max"][0],
        "temp_min": daily["temperature_2m_min"][0],
    }
    logger.info(f"天气获取成功：{weather_info}")
    return weather_info


# 读取昨天笔记里的明日计划，作为今天的今日计划
def read_yesterday_plan():
    yesterday = (datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = NOTES_DIR / f"{yesterday}.md"
    if not yesterday_path.exists():
        logger.info(f"昨日文件不存在：{yesterday}.md, 今日计划留空")
        return ""

    text = yesterday_path.read_text(encoding="utf-8-sig")

    # 关键：用 \s* 兼容"冒号后同一行写内容"和"冒号后换行写内容"两种写法
    match = re.search(r"> 明日计划：\s*(.*?)(?=\n\s*---|\Z)", text, re.S)
    if not match:
        logger.info("昨日文件中未读取到明日计划")
        return ""

    plan = match.group(1).strip()
    if not plan:
        logger.info("昨日计划为空，今日计划留空")
        return ""

    logger.info(f"已读取到昨天的明日计划：{plan[:50].replace(chr(10), ' ')}")
    return plan


# 生成天气区域的内容
def build_weather_block(weather):
    return f"""{WEATHER_START}
## 今日天气
- 当前天气：{weather['weather']}
- 当前温度：{weather['temp_now']} ℃
- 湿度：{weather['humidity']} %
- 今日最高温：{weather['temp_max']} ℃
- 今日最低温：{weather['temp_min']} ℃
{WEATHER_END}"""


# 创建完整模版
def build_markdown(weather, date_str):
    yesterday_plan = read_yesterday_plan()
    plan_section = yesterday_plan if yesterday_plan else ""
    md = f"""{MARKER_TEMPLATE.format(date=date_str)}
# {date_str} 学习记录

{build_weather_block(weather)}

{PLAN_START}
> 今日计划：
{plan_section}
{PLAN_END}
---
## 今日总结
### 刷题记录

### 问题记录

### 收获

> 明日计划：

---
"""
    return md


# 更新天气区域的内容
def update_weather_section(existing_text, weather):
    pattern = re.compile(
        re.escape(WEATHER_START) + r".*?" + re.escape(WEATHER_END),
        re.S,
    )
    new_weather = build_weather_block(weather)

    if pattern.search(existing_text):
        updated = pattern.sub(new_weather, existing_text)
        logger.info("天气区域已更新")
        return updated, True
    else:
        logger.warning("未找到天气区域，无法更新")
        return existing_text, False


# 取出计划区当前的内容（用于判断是否为空）
def extract_plan_content(existing_text):
    pattern = re.compile(
        re.escape(PLAN_START) + r"(.*?)" + re.escape(PLAN_END),
        re.S,
    )
    match = pattern.search(existing_text)
    if not match:
        return None
    content = match.group(1).strip()
    # 去掉 "> 今日计划：" 这一行，剩下的才是真正的计划内容
    content = re.sub(r"^>\s*今日计划：\s*", "", content).strip()
    return content


# 更新计划区域的内容
def update_plan_section(existing_text, plan_text):
    pattern = re.compile(
        re.escape(PLAN_START) + r".*?" + re.escape(PLAN_END),
        re.S,
    )
    new_plan = f"""{PLAN_START}
> 今日计划：
{plan_text}
{PLAN_END}"""

    if pattern.search(existing_text):
        updated = pattern.sub(new_plan, existing_text)
        logger.info("计划区域已更新")
        return updated, True
    else:
        logger.warning("未找到计划区域标记，无法更新")
        return existing_text, False


# 生成md内容
def write_md(content, date_str, weather):
    marker = MARKER_TEMPLATE.format(date=date_str)

    # 情况 1：文件不存在 → 新建
    if not md_full_path.exists():
        with open(md_full_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"新建文件：{md_filename}")
        return

    # 读取已有内容
    existing = md_full_path.read_text(encoding="utf-8-sig")

    # 情况 2：文件存在且含今天标记 → 刷新天气 + 按需补计划
    if marker in existing:
        updated = existing
        changed = False

        # 2.1 刷新天气区域
        updated, ok = update_weather_section(updated, weather)
        if ok:
            changed = True

        # 2.2 若计划区为空，用昨天的计划补上
        current_plan = extract_plan_content(updated)
        if current_plan == "":
            yesterday_plan = read_yesterday_plan()
            if yesterday_plan:
                updated, ok2 = update_plan_section(updated, yesterday_plan)
                if ok2:
                    changed = True
                    logger.info("计划区为空，已补填昨日计划")
            else:
                logger.info("计划区为空，且昨日无计划可补")
        elif current_plan is None:
            logger.warning("未找到计划区标记，跳过计划补填")

        # 写回
        if changed:
            with open(md_full_path, "w", encoding="utf-8") as f:
                f.write(updated)
            logger.info(f"{md_filename}已存在，天气/计划已更新，其余内容保留")
        else:
            logger.info(f"{md_filename}已存在，无需更新")
        return

    # 情况 3：文件存在但没有今天标记 → 追加
    with open(md_full_path, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    logger.info(f"已追加到现有文件：{md_filename}")


# 实现git提交
def git_commit():
    if not md_full_path.exists():
        logger.warning(f"{md_filename} 不存在，跳过git提交")
        return
    try:
        subprocess.run(
            ["git", "add", f"notes/{md_filename}"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"git add 失败:{e.stderr.strip()}")
        return

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO_PATH,
        capture_output=True,
    )
    if diff.returncode == 0:
        logger.info("暂存区无变更，无需commit")
        return
    elif diff.returncode != 1:
        logger.error(f"git diff 检查失败，returncode={diff.returncode}")
        return

    result = subprocess.run(
        ["git", "commit", "-m", f"自动更新{today}天气与笔记"],
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        logger.info(f"本地commit完成!文件:{md_filename}")
        logger.warning("需要手动同步")
    else:
        logger.error(f"commit 失败：{result.stderr.strip() or result.stdout.strip()}")


if __name__ == "__main__":
    try:
        weather_data = get_weather()
        md_text = build_markdown(weather_data, today)
        write_md(md_text, today, weather_data)
#       git_commit()
    except Exception as e:
        logger.exception(f"脚本执行失败：{e}")
    logger.info("====== 脚本运行结束 ======\n")