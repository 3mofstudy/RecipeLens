"""Facebook 單支公開影片下載。"""
from .video_download import detect_platform, download


def download_facebook(url, work, tools, subtitles="auto"):
    if detect_platform(url) != "Facebook":
        raise ValueError("Facebook 下載器收到其他平台網址。")
    return download(url, work, tools, subtitles)
