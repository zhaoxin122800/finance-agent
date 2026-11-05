"""quant-kb 简易关键词检索。

设计 §4.9 尾注:quant-kb 不单独成页,作为 RAG 上下文。
YAGNI:不用向量库,按段落分块 + 关键词子串匹配,足够自用场景。
"""
from __future__ import annotations

import logging
import re

from app.config import QUANT_KB_DIR

log = logging.getLogger("finance-agent.kb")

MAX_SNIPPET_CHARS = 600
MAX_SNIPPETS = 8


def _split_paragraphs(text: str) -> list[str]:
    """按空行/标题分块,保留小段落。"""
    blocks = re.split(r"\n(?=#{1,4}\s)|\n{2,}", text)
    return [b.strip() for b in blocks if b.strip()]


def search(keywords: list[str]) -> list[str]:
    """在 quant-kb 全部 md 里按关键词召回段落。返回去重后的 snippet 列表。"""
    if not keywords:
        return []
    snippets: list[str] = []
    seen: set[str] = set()
    if not QUANT_KB_DIR.exists():
        return []
    for md_path in sorted(QUANT_KB_DIR.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("读取 %s 失败: %s", md_path, e)
            continue
        for para in _split_paragraphs(text):
            if any(kw in para for kw in keywords):
                snippet = para[:MAX_SNIPPET_CHARS]
                if snippet in seen:
                    continue
                seen.add(snippet)
                snippets.append(snippet)
                if len(snippets) >= MAX_SNIPPETS:
                    return snippets
    return snippets


def format_for_prompt(snippets: list[str]) -> str:
    """把召回的 snippet 拼成可塞进 prompt 的字符串。"""
    if not snippets:
        return ""
    return "\n---\n".join(snippets)
