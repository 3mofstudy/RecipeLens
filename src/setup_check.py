"""啟動時的 AI 環境檢查：確認已安裝 ChatGPT 桌面版（Codex）或 Claude 桌面版（Claude Code）其中一種。"""
from dataclasses import dataclass

from .ai_recipe import PROVIDER_TOOLS
from .environment import find_tool


@dataclass(frozen=True)
class InstallGuide:
    provider: str
    name: str
    plan: str      # 方案需求：免費帳號能否使用
    url: str       # 官方下載頁
    command: str   # 以 winget 安裝的指令，可在 PowerShell 執行
    steps: str     # 安裝後讓 RecipeLens 找得到的步驟


# RecipeLens 呼叫桌面版內附的 Codex／Claude Code；桌面版要先開啟並登入一次才會放出這些程式。
INSTALL_GUIDES = {
    "Codex": InstallGuide(
        "Codex", "ChatGPT 桌面版（Codex）",
        "免費帳號可使用 gpt-6-luna（OpenAI 陸續開放中，少數帳號可能還不能用）；付費方案模型較多、額度較高。",
        "https://apps.microsoft.com/detail/9PLM9XGG6VKS",
        "winget install --id 9PLM9XGG6VKS -s msstore",
        "安裝後開啟 ChatGPT，登入後切換到「Codex」一次，RecipeLens 才找得到它。",
    ),
    "Claude": InstallGuide(
        "Claude", "Claude 桌面版（Claude Code）",
        "需要 Claude Pro 以上的付費方案；免費帳號不含 Claude Code，無法用來判讀食譜。",
        "https://claude.com/download",
        "winget install Anthropic.Claude",
        "安裝後開啟 Claude，登入後點左側「Code」分頁一次，等它下載完成，RecipeLens 才找得到它。",
    ),
}


def ai_tool_status(find=find_tool):
    """{"Codex": bool, "Claude": bool}；True 表示找得到可呼叫的程式。"""
    return {provider: bool(find(tool)) for provider, tool in PROVIDER_TOOLS.items()}


def missing_providers(status):
    return [provider for provider in INSTALL_GUIDES if not status.get(provider)]


def any_installed(status):
    return any(status.get(provider) for provider in INSTALL_GUIDES)


def setup_summary(status):
    """環境檢查畫面的開頭說明。"""
    if not any_installed(status):
        return ("RecipeLens 要用 AI 桌面版判讀影片、整理食譜。請至少安裝下列其中一種，安裝完成後按「重新檢查」。\n"
                "沒有付費方案的話，建議安裝 ChatGPT 桌面版。")
    installed = "、".join(INSTALL_GUIDES[p].name for p in INSTALL_GUIDES if status.get(p))
    if missing_providers(status):
        return f"已找到 {installed}，可以進入主畫面。另一種為選用，需要時再安裝。"
    return f"已找到 {installed}，可以進入主畫面。"


def missing_tool_message(provider):
    guide = INSTALL_GUIDES[provider]
    return (f"找不到 {guide.name}。{guide.steps}\n{guide.plan}\n"
            f"或在「進階設定」改選其他 AI。下載：{guide.url}")
