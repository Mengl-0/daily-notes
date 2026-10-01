import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from logging.handlers import TimedRotatingFileHandler

# ==== 配置区 ====
REPO_PATH = Path(r"D:\git\daily-notes")
IMAGES_DIR = REPO_PATH / "images"
TIMEZONE = "Asia/Shanghai"
IMG_EXTS ={".png",".jpg",".jpeg",".gif",".webp",".bmp"}
RECURSIVE = False # 不递归子目录
UPDATE_MD= True # 更新 .md 引用
DRY_RUN = False # True只打印不移动，用于预演
NOTES_DIR = REPO_PATH / "notes"
LOG_DIR = REPO_PATH / "logs"
LOG_FILE = Path(LOG_DIR) / "image_organizer.log"
LOG_BACKUP_DAYS = 30
LOG_ROTATE_INTERVAL = "D"
# 限定处理格式为 类似 2026-09-29.md
DATE_MD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$", re.IGNORECASE)
# ==== ==== ==== ====

LOG_DIR.mkdir(parents=True, exist_ok=True)
# 日志初始化
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = TimedRotatingFileHandler(
        filename= LOG_FILE,
        when= LOG_ROTATE_INTERVAL,
        backupCount= LOG_BACKUP_DAYS,
        encoding= "utf-8"
    )
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# 将文件的修改时间作为日期，格式 YYYY-MM-DD
def get_date_from_file(path:Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")

# 寻找当天后缀已用最大编号，返回下一个可用编号
def next_index(images_dir: Path, date: str) -> int:
    if not images_dir.exists():
        return 1
    pattern = re.compile(
        rf"^{re.escape(date)}_(\d+)\.\w+$",
        re.IGNORECASE,
    )
    max_n = 0
    for f in images_dir.iterdir():
        if not f.is_file():
            continue
        m = pattern.match(f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1

# 收集除 images 目录外所有待处理图片
def collect_images(repo: Path, recursive: bool) -> list[Path]:
    if recursive:
        candidates = repo.rglob("*")
    else:
        candidates = repo.glob("*")

    result = []
    for f in candidates:
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMG_EXTS:
            continue
        # 排除 images 目录里的文件
        if IMAGES_DIR == f.parent or IMAGES_DIR in f.parents:
            continue
        result.append(f)
    return result

# 对图片进行重命名以及移动到指定文件夹下或原路径(位置)
def move_and_rename(img: Path, images_dir: Path) -> tuple[Path, Path]:
    if not DRY_RUN:
        images_dir.mkdir(parents=True, exist_ok=True)

    date = get_date_from_file(img)
    ext = img.suffix.lower()

    idx = next_index(images_dir, date)
    target = images_dir / f"{date}_{idx:03d}{ext}"
    # 冲突时自动往后找空号
    while target.exists():
        idx += 1
        target = images_dir / f"{date}_{idx:03d}{ext}"
    if DRY_RUN:
        logger.info(f"[DRY_RUN] {img.name} -> {target.relative_to(REPO_PATH).as_posix()}")
    else:
        shutil.move(str(img), str(target))
    return img, target

# 把 .md 里对旧图片路径的引用替换成新路径
def update_md_references(repo:Path, moves: list[tuple[Path,Path]]):
    if not moves:
        return
    # 旧文件名 -> 新相对路径（相对repo）
    replace_map ={}
    for old, new in moves:
        replace_map[old_name] = new  # 先存 Path，替换时按 md 位置算相对路径
    
#    md_files = list(repo.rglob("*.md")) # 所有.md格式文档
    md_files= [
        f for f in NOTES_DIR.glob("*.md")
        if DATE_MD_PATTERN.match(f.name)
    ]

    if not md_files:
        logger.info("没有符合 YYYY-MM-DD.md 格式的笔记需要检查")
        return 
    update_count = 0
    for md in  md_files:
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = md.read_text(encoding="utf-8-sig")
        original = text

        for old_name, new_rel in replace_map.items():
            pattern = re.compile(
                rf"(!\[[^\]]*\]\()"          # 组1： ![alt](
                rf"([^)]*?)"                # 组2：路径前缀（可空）
                rf"(?:^|/)"                 # 路径分隔或开头
                rf"({re.escape(old_name)})" # 组3：旧文件名
                rf"(\))"                    # 组4：)
            )
            text = pattern.sub(
                lambda m: f"{m.group(1)}{new_rel}{m.group(4)}",
                text,
            )
        if text != original:
            if DRY_RUN:
                logger.info(f"[DRY_RUN] 将更新引用：{md.relative_to(repo)}")
            else:
                md.write_text(text, encoding="utf-8")
                logger.info(f"已更新引用：{md.relative_to(repo)}")
            update_count += 1
    if update_count == 0:
        logger.info("没有 .md 文件需要更新")

# 运行
def main():
    logger.info("====== 图片整理开始 ======")
    if not REPO_PATH.exists():
        logger.error(f"仓库路径不存在：{REPO_PATH}")
        raise FileNotFoundError(f"仓库路径不存在：{REPO_PATH}")

    images = collect_images(NOTES_DIR, RECURSIVE)
    if not images:
        logger.info("没有待处理的图片")
        logger.info("====== 图片整理结束 ======\n")
        return

    logger.info(f"发现{len(images)}张图片， 开始处理...")

    moves = []
    for img in images:
        old, new = move_and_rename(img, IMAGES_DIR)
        moves.append((old,new))
        rel = new.relative_to(REPO_PATH).as_posix()
        if not DRY_RUN:
            logger.info(f"{old.name} -> {rel}")

    if UPDATE_MD:
        update_md_references(REPO_PATH, moves)
    logger.info(f"\n完成，共处理{len(moves)}张图片")
    logger.info(f"目标目录：{IMAGES_DIR}")
    logger.info("====== 图片整理结束 ======\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(f"脚本执行失败：{e}")