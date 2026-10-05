import subprocess
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

SCRIPT_DIR = Path("scripts")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志初始化
logger = logging.getLogger("script_manager")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt= "%Y-%m-%d %H-%M-%S",
    )
    file_handler = RotatingFileHandler(
        LOG_DIR / "main.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def search_scripts() -> list[Path]:
    if not SCRIPT_DIR.exists():
        return []
    return sorted(SCRIPT_DIR.glob("*.py"))
def main():
    logger.info("====== 脚本管理器启动 ======")
    while True:
        scripts = search_scripts()
        logger.info(f"扫描到{len(scripts)}个脚本")
        print("\n===== 脚本管理器 =====")
        if not scripts:
            print("目录下没有 .py脚本")
        for idx,name in enumerate(scripts, start=1):
            print(f"{idx}:{name}")
        print("0. 退出")
        print("===== ===== =====")
        choice = input("请选择脚本编号：").strip()
        if choice == "0":
            logger.info("用户退出")
            break
        if not choice.isdigit():
            print("请输入数字编号")
            continue
        num = int(choice) - 1
        if not (0 <= num <len(scripts)):
            print("编号超出范围")
            continue

        target = scripts[num]
        logger.info(f"正在运行：{target.name}")
        print(f"正在运行：{target.name} ... \n")

        try:
            result = subprocess.run([sys.executable, str(target)])
            logger.info(f"脚本{target.name}退出码:{result.returncode}")
            if result.returncode != 0:
                print(f"\n脚本退出码:{result.returncode}")
        except KeyboardInterrupt:
            logger.info(f"脚本{target.name}被中断")
            print("\n已中断当前脚本")
        except Exception as e :
            logger.info(f"运行{target.name}失败")
            print(f"脚本运行异常：{e}")
        input("\n按回车返回菜单···")
    logger.info("====== 脚本管理器退出 ======")
    
if __name__ == "__main__":
    main()