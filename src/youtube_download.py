"""YouTube 下載與資訊欄食譜檢查。"""
import re

from .video_download import detect_platform, download, read_metadata


def inspect_youtube(url, work, tools):
    if detect_platform(url) != "YouTube":
        raise ValueError("YouTube 下載器收到其他平台網址。")
    return read_metadata(url, work, tools)


def has_complete_recipe(description):
    """保守規則，須同時含食材段落、至少兩項份量及兩個料理動作。"""
    ingredients = re.search(r"食材|材料|ingredients", description, re.I)
    method = re.search(r"做法|作法|步驟|製作方法|method|instructions|directions", description, re.I)
    if not ingredients or not method or method.start() <= ingredients.start():
        return False
    ingredient_text = description[ingredients.end():method.start()]
    amounts = re.findall(
        r"\d+(?:[./]\d+)?\s*(?:克|公克|公斤|毫升|大匙|小匙|茶匙|湯匙|顆|個|片|杯|g\b|ml\b|tsp\b|tbsp\b)",
        ingredient_text, re.I,
    )
    actions = re.findall(
        r"切|炒|煮|蒸|煎|烤|拌|加入|放入|倒入|燉|滷|mix|add|cook|bake|stir",
        description[method.end():], re.I,
    )
    return len(amounts) >= 2 and len(actions) >= 2


def download_youtube(url, work, tools, subtitles="auto"):
    if detect_platform(url) != "YouTube":
        raise ValueError("YouTube 下載器收到其他平台網址。")
    return download(url, work, tools, subtitles)
