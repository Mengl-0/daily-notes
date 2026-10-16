"""
笔记整理脚本 —— 按年月归档 + 图片链接修正

依赖：无第三方库（纯标准库）
运行方式：
    python scripts/organize_notes.py
    （或经 main.py 调度；BASE_DIR 基于脚本位置推导，与 cwd 无关）

功能：
    1. 扫描 notes/ 一级目录下 YYYY-MM-DD.md 文件
    2. 归档到 notes/YYYY-MM/ 子目录（一层）
    3. 归档后把 md 内 ![alt](../images/x) 替换为 ![alt](../../images/x)
    4. 支持 DRY_RUN 预演，不改动任何文件
"""
import re
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

# ===================== 配置区 =====================
# 项目根目录：脚本位于 scripts/ 下，上一级的上一级即 daily-notes/
BASE_DIR = Path(__file__).resolve().parent.parent

NOTES_DIR = BASE_DIR / "notes"
LOGS_DIR  = BASE_DIR / "logs"

# 图片链接前缀：归档前 ../，归档后 ../../（因多进了一层目录）
OLD_IMG_PREFIX = "../images/"
NEW_IMG_PREFIX = "../../images/"

# 日志配置
LOG_FILE          = LOGS_DIR / "organize_run.log"
LOG_BACKUP_DAYS   = 30     # 保留最近 30 天的日志
LOG_ROTATE_INTERVAL = "D"  # 切割 D=天；H=小时；M=分钟

# 时区：统一东八区，避免本机时区与预期不一致
TIMEZONE = "Asia/Shanghai"

# 预演开关：True=只打印不改文件；False=真实执行
DRY_RUN = True
# ==================================================


def init_logger() -> logging.Logger:
    """
    初始化独立 logger（幂等）：
      - 命名 logger，不写 root，propagate=False，避免与 main.py 冲突
      - FileHandler：TimedRotatingFileHandler 按天轮转，保留 LOG_BACKUP_DAYS 份
      - StreamHandler：控制台同步输出
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("organize_notes")
    logger.setLevel(logging.INFO)
    logger.propagate = False   # 不向 root 冒泡，与 main.py 完全隔离

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = TimedRotatingFileHandler(
            filename=LOG_FILE,
            when=LOG_ROTATE_INTERVAL,
            backupCount=LOG_BACKUP_DAYS,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def parse_ym(filename: str):
    """解析 YYYY-MM-DD.md 返回 YYYY-MM，非法返回 None。"""
    pat = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.md", filename)
    if not pat:
        return None
    date_str = pat.group(1)
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str[:7]
    except ValueError:
        return None


def replace_img_links(file_path: Path, logger: logging.Logger) -> str:
    """
    替换 md 内图片链接，只处理 ![xxx](../images/xxx)。
    返回三态：'modified' | 'unchanged' | 'error'。
    """
    if not file_path.exists():
        logger.error(f"文件不存在，无法处理: {file_path}")
        return "error"

    try:
        # 读用 utf-8-sig：兼容 BOM，避免首字符匹配失败
        content = file_path.read_text(encoding="utf-8-sig")
    except Exception as e:
        logger.error(f"读取 md 失败 {file_path}: {e}")
        return "error"

    pattern = re.compile(
        r"!\[(.*?)\]\(" + re.escape(OLD_IMG_PREFIX) + r"([^)]+)\)"
    )
    new_content = pattern.sub(
        r"![\1](" + NEW_IMG_PREFIX + r"\2)", content
    )

    if new_content == content:
        logger.info(f"无需替换图片链接：{file_path}")
        return "unchanged"

    if DRY_RUN:
        logger.info(f"[预演] 将更新图片路径：{file_path}")
        return "modified"

    try:
        # 写用 utf-8：不回写 BOM
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(f"已更新图片路径：{file_path}")
        return "modified"
    except Exception as e:
        logger.error(f"写入 md 失败 {file_path}: {e}")
        return "error"


def run(logger: logging.Logger) -> None:
    """核心执行逻辑（不含日志初始化），便于 main 包裹异常。"""
    stat = {
        "scan_total": 0,
        "valid": 0,
        "move_skip": 0,
        "moved": 0,        # 真实执行=已移动；预演=计划移动
        "modified": 0,     # 链接被真正修改
        "unchanged": 0,    # 链接无需修改
        "error": 0,        # 文件非法 / 读写错误
    }

    if not NOTES_DIR.is_dir():
        logger.error(f"notes 目录不存在: {NOTES_DIR}")
        return

    # 只扫描 notes 一级文件，不进子目录
    md_list = [
        p.name for p in NOTES_DIR.iterdir()
        if p.is_file() and p.suffix == ".md"
    ]
    stat["scan_total"] = len(md_list)
    logger.info(f"在 notes 一级目录扫描到 md 文件：{stat['scan_total']} 个")

    # 按年月分组
    groups: dict[str, list[str]] = {}
    for fname in md_list:
        ym = parse_ym(fname)
        if ym is None:
            logger.warning(f"文件名格式非法，跳过：{fname}")
            stat["error"] += 1
            continue
        stat["valid"] += 1
        groups.setdefault(ym, []).append(fname)
    logger.info(f"有效可分组文件：{stat['valid']} 个，共 {len(groups)} 个年月分组")

    for ym, file_list in groups.items():
        target_dir = NOTES_DIR / ym

        # 先判断是否真有文件需要移入，避免创建空目录
        pending = [
            fn for fn in file_list
            if not (target_dir / fn).exists()
        ]

        if not target_dir.exists():
            if not DRY_RUN:
                if pending:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"创建目录 {target_dir}")
                else:
                    logger.info(f"全部文件已在目标位置，跳过创建目录 {target_dir}")
            else:
                logger.info(f"[预演] 将创建目录 {target_dir}")
        else:
            logger.info(f"目录已存在 {target_dir}")

        for fn in file_list:
            src = NOTES_DIR / fn
            dst = target_dir / fn

            # 目标已存在：跳过移动，但仍尝试修复链接
            if dst.exists():
                logger.warning(f"目标已存在，跳过移动但尝试修复链接：{dst}")
                stat["move_skip"] += 1
                result = replace_img_links(dst, logger)
                if result == "modified":
                    stat["modified"] += 1
                elif result == "unchanged":
                    stat["unchanged"] += 1
                else:
                    stat["error"] += 1
                continue

            # 移动文件
            if not DRY_RUN:
                try:
                    src.rename(dst)
                    logger.info(f"移动 {src} → {dst}")
                except Exception as e:
                    logger.error(f"移动失败 {src} → {dst}: {e}")
                    stat["error"] += 1
                    continue
            else:
                logger.info(f"[预演] 将移动 {src} → {dst}")
            stat["moved"] += 1

            # 预演时读 src（真实文件位置）；真实时读 dst
            target = dst if not DRY_RUN else src
            result = replace_img_links(target, logger)
            if result == "modified":
                stat["modified"] += 1
            elif result == "unchanged":
                stat["unchanged"] += 1
            else:
                stat["error"] += 1

    # 输出统计摘要
    mode = "【预演模式】" if DRY_RUN else "【真实执行】"
    summary = (
        f"\n===== 执行统计摘要 {mode} =====\n"
        f"扫描 md 总数        : {stat['scan_total']}\n"
        f"有效待处理          : {stat['valid']}\n"
        f"{'计划移动' if DRY_RUN else '成功移动'}          : {stat['moved']}\n"
        f"目标已存在跳过移动  : {stat['move_skip']}\n"
        f"链接实际修改        : {stat['modified']}\n"
        f"链接无需修改        : {stat['unchanged']}\n"
        f"错误/非法文件       : {stat['error']}"
    )
    logger.info(summary)
    print(summary)


def main():
    logger = init_logger()
    # 日志文件名带日期（用东八区，跨时区/云服务器也一致）
    now_str = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"===== 笔记整理脚本启动 ({now_str}) =====")
    logger.info(f"DRY_RUN={DRY_RUN} | 日志保留 {LOG_BACKUP_DAYS} 天")

    try:
        run(logger)
    except Exception:
        logger.exception("脚本执行失败")

    logger.info("===== 脚本执行结束 =====\n")


if __name__ == "__main__":
    main()