"""RecipeLens 入口，無參數開啟 GUI，提供網址時使用命令列模式。"""
import sys


def main():
    if len(sys.argv) > 1:
        from src.recipe_lens import main as run_cli
        run_cli()
    else:
        from src.gui import main as run_gui
        run_gui()


if __name__ == "__main__":
    main()
