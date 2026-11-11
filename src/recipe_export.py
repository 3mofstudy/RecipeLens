"""食譜 Markdown 與截圖匯出。"""
from .media import screenshot

def export_recipe(recipe, url, duration, ffmpeg, video, work, destination):
    if not recipe["steps"]:
        raise ValueError("影片素材不足，無法辨識料理步驟。")

    print("正在擷取步驟截圖並匯出 Markdown…", flush=True)
    staged = work / "recipe"
    images = staged / "images"
    images.mkdir(parents=True, exist_ok=True)
    lines = [f"# {recipe['title']}", "", f"來源影片：<{url}>", "", "## 食材", ""]
    lines.extend(f"- {item['name']}：{item['amount']}" for item in recipe["ingredients"])
    if not recipe["ingredients"]:
        lines.append("影片未說明。")
    lines.extend(["", "## 料理步驟", ""])

    for index, step in enumerate(recipe["steps"], start=1):
        seconds = step["seconds"]
        if not 0 <= seconds < duration:
            raise ValueError(f"Codex 回傳的第 {index} 步時間超出影片範圍。")
        filename = f"step-{index:02d}.jpg"
        # Leave room to decode the last frame if the timestamp is near EOF.
        screenshot(ffmpeg, video, min(seconds, max(0, duration - 0.1)),
                   images / filename, work)
        minutes, whole_seconds = divmod(int(seconds), 60)
        lines.extend([
            f"### {index}. [{minutes:02d}:{whole_seconds:02d}]",
            "", step["instruction"], "", f"![步驟 {index}](images/{filename})", "",
        ])

    (staged / "食譜.md").write_text("\n".join(lines), encoding="utf-8")
    staged.rename(destination)
    return destination / "食譜.md"


