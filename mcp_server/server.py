# ============================================================
#  LSB MCP 服务端 —— 学术论文检索
#  ------------------------------------------------------------
#
#  启动：
#      python server.py
#  端点：
#      http://127.0.0.1:8001/mcp   (streamable-http)
#
#  说明：arXiv 接口用 httpx + 标准库 XML 解析，不依赖第三方 arxiv 包，
#        减少安装体积与版本冲突。
# ============================================================
import asyncio
import logging
import os
import xml.etree.ElementTree as ET

import httpx
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lsb_mcp")

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
MCP_PATH = os.getenv("MCP_PATH", "/mcp")

# 可选：Semantic Scholar 在无密钥时会被限流，配置后可稳定使用
S2_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

mcp = FastMCP("LSB_ACADEMIC_SEARCH")


# ---------- 工具 1：arXiv 检索 ----------

@mcp.tool()
async def search_arxiv(query: str, max_results: int = 5, sort_by: str = "relevance") -> dict:
    """
    检索 arXiv 上的计算机视觉 / 深度学习论文。

    Args:
        query:       检索词，支持 arXiv 语法，例如
                     "3D gaussian splatting"、"ti:transformer AND cat:cs.CV"、
                     "au:he AND cat:cs.CV"。
        max_results: 返回条数，1~20，默认 5。
        sort_by:     排序方式，"relevance"（相关度）或 "lastUpdatedDate"（最新）。

    Returns:
        包含 papers 列表的字典，每篇论文含 title / authors / published /
        summary / arxiv_id / pdf_url / categories / comment。
    """
    import re
    from datetime import datetime
    from html.parser import HTMLParser

    max_results = max(1, min(int(max_results), 20))
    if sort_by not in ("relevance", "lastUpdatedDate", "submittedDate"):
        sort_by = "relevance"

    class _Node:
        def __init__(self, tag="", attrs=None, parent=None):
            self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
            self.children = []

        def text(self):
            return " ".join(" ".join(
                child.text() if isinstance(child, _Node) else child
                for child in self.children
            ).split())

        def find_all(self, tag=None, class_name=None):
            found = []
            classes = self.attrs.get("class", "").split()
            if (tag is None or self.tag == tag) and (class_name is None or class_name in classes):
                found.append(self)
            for child in self.children:
                if isinstance(child, _Node):
                    found.extend(child.find_all(tag, class_name))
            return found

    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = _Node()
            self.current = self.root

        def handle_starttag(self, tag, attrs):
            node = _Node(tag, attrs, self.current)
            self.current.children.append(node)
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
                self.current = node

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if self.current.tag == tag:
                self.current = self.current.parent

        def handle_endtag(self, tag):
            node = self.current
            while node.parent is not None:
                if node.tag == tag:
                    self.current = node.parent
                    return
                node = node.parent

        def handle_data(self, data):
            self.current.children.append(data)

    # arXiv 网页检索不直接支持 Atom API 的字段语法，将其转成可读关键词。
    web_query = re.sub(r"\b(?:all|ti|au|abs|co|jr|cat):", "", query, flags=re.I)
    web_query = re.sub(r"\b(?:AND|OR|ANDNOT)\b", " ", web_query, flags=re.I)
    web_query = " ".join(web_query.split())
    params = {
        "query": web_query,
        "searchtype": "all",
        "abstracts": "show",
        "order": "" if sort_by == "relevance" else "-announced_date_first",
        # arXiv 网页只接受 25/50/100/200，返回后再截取用户要求的数量。
        "size": 25,
    }
    logger.info(f"arXiv 网页检索: {web_query} (max={max_results}, sort={sort_by})")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        last_error = None
        async with httpx.AsyncClient(timeout=40.0, follow_redirects=True, headers=headers) as client:
            for attempt in range(2):
                try:
                    resp = await client.get("https://arxiv.org/search/", params=params)
                    resp.raise_for_status()
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt == 0:
                        await asyncio.sleep(1)
            else:
                raise last_error
        parser = _Parser()
        parser.feed(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"arXiv 网页检索失败: {exc}")
        return {"error": f"arXiv 检索失败: {exc}", "papers": []}

    papers = []
    for entry in parser.root.find_all("li", "arxiv-result")[:max_results]:
        def _first_text(class_name):
            nodes = entry.find_all(class_name=class_name)
            return nodes[0].text() if nodes else ""

        links = entry.find_all("a")
        abs_url = next((n.attrs.get("href", "") for n in links if "/abs/" in n.attrs.get("href", "")), "")
        arxiv_id = abs_url.rstrip("/").rsplit("/", 1)[-1] if abs_url else ""
        authors_node = entry.find_all(class_name="authors")
        authors = [a.text() for a in authors_node[0].find_all("a")] if authors_node else []
        date_text = entry.text()
        date_match = re.search(r"(?:Submitted|Announced|Updated)\s+(\d{1,2}\s+\w+,?\s+\d{4})", date_text)
        published = ""
        if date_match:
            try:
                published = datetime.strptime(date_match.group(1).replace(",", ""), "%d %B %Y").strftime("%Y-%m-%d")
            except ValueError:
                published = date_match.group(1)
        summary = _first_text("abstract-full") or _first_text("abstract-short")
        summary = re.sub(r"^(?:Abstract:\s*)|(?:\s*(?:△ Less|▽ More))$", "", summary).strip()
        categories = [n.text() for n in entry.find_all("span", "tag") if n.text()]
        comment = next((n.text().split(":", 1)[-1].strip() for n in entry.find_all("p")
                        if n.text().lower().startswith("comments:")), "")
        papers.append({
            "title": _first_text("title"),
            "authors": authors,
            "published": published,
            "updated": published,
            "summary": summary,
            "arxiv_id": arxiv_id,
            "abs_url": abs_url,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
            "categories": categories,
            "comment": comment,
        })

    logger.info(f"arXiv 命中 {len(papers)} 篇")
    if not papers:
        return {"papers": [], "message": "未检索到匹配的论文，请更换关键词或放宽条件。"}
    return {"papers": papers, "count": len(papers)}


# ---------- 工具 2：Semantic Scholar 检索 ----------

@mcp.tool()
async def search_semantic_scholar(query: str, limit: int = 5, year: str = "") -> dict:
    """
    检索 Semantic Scholar 上的论文，返回引用数、发表会议等学术影响力信息。
    适合用来判断某项工作的受关注程度与发表去向。

    Args:
        query: 检索词，支持自然语言，例如 "vision transformer object detection"。
        limit: 返回条数，1~20，默认 5。
        year:  年份过滤，例如 "2020-2026"、"2023"、"2020-"；留空表示不限。

    Returns:
        包含 papers 列表的字典，每篇含 title / year / venue / citationCount /
        authors / abstract / url。无密钥时可能因限流返回提示信息。
    """
    import re
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    limit = max(1, min(int(limit), 20))

    class _Node:
        def __init__(self, tag="", attrs=None, parent=None):
            self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
            self.children = []

        def text(self):
            return " ".join(" ".join(
                child.text() if isinstance(child, _Node) else child
                for child in self.children
            ).split())

        def find_all(self, tag=None, class_name=None):
            found = []
            classes = self.attrs.get("class", "").split()
            if (tag is None or self.tag == tag) and (class_name is None or class_name in classes):
                found.append(self)
            for child in self.children:
                if isinstance(child, _Node):
                    found.extend(child.find_all(tag, class_name))
            return found

    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = _Node()
            self.current = self.root

        def handle_starttag(self, tag, attrs):
            node = _Node(tag, attrs, self.current)
            self.current.children.append(node)
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
                self.current = node

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if self.current.tag == tag:
                self.current = self.current.parent

        def handle_endtag(self, tag):
            node = self.current
            while node.parent is not None:
                if node.tag == tag:
                    self.current = node.parent
                    return
                node = node.parent

        def handle_data(self, data):
            self.current.children.append(data)

    params = {"q": query, "hl": "en", "num": limit}
    if year:
        match = re.fullmatch(r"\s*(\d{4})?\s*(?:-\s*(\d{4})?\s*)?", year)
        if match:
            start_year, end_year = match.groups()
            if "-" not in year:
                end_year = start_year
            if start_year:
                params["as_ylo"] = start_year
            if end_year:
                params["as_yhi"] = end_year

    logger.info(f"学术网页检索: {query} (limit={limit}, year={year or '不限'})")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        last_error = None
        async with httpx.AsyncClient(timeout=40.0, follow_redirects=True, headers=headers) as client:
            for attempt in range(2):
                try:
                    resp = await client.get("https://scholar.google.com/scholar", params=params)
                    resp.raise_for_status()
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt == 0:
                        await asyncio.sleep(1)
            else:
                raise last_error
        if "not a robot" in resp.text.lower() or "unusual traffic" in resp.text.lower():
            return {"error": "学术检索网页要求人机验证，请稍后重试。", "papers": []}
        parser = _Parser()
        parser.feed(resp.text)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"学术网页检索失败: {exc}", "papers": []}

    papers = []
    for item in parser.root.find_all("div", "gs_ri")[:limit]:
        titles = item.find_all("h3", "gs_rt")
        title_node = titles[0] if titles else None
        title_links = title_node.find_all("a") if title_node else []
        title = title_node.text() if title_node else ""
        title = re.sub(r"^\s*\[[^]]+\]\s*", "", title)
        url = title_links[0].attrs.get("href", "") if title_links else ""
        if url:
            url = urljoin("https://scholar.google.com", url)

        meta_nodes = item.find_all("div", "gs_a")
        meta = meta_nodes[0].text() if meta_nodes else ""
        parts = [part.strip() for part in meta.split(" - ")]
        authors = [name.strip() for name in parts[0].split(",") if name.strip()] if parts else []
        year_match = re.search(r"\b(19|20)\d{2}\b", meta)
        paper_year = int(year_match.group(0)) if year_match else None
        venue = parts[1] if len(parts) > 1 else ""
        abstracts = item.find_all("div", "gs_rs")
        abstract = abstracts[0].text() if abstracts else ""
        footer = item.find_all("div", "gs_fl")
        footer_text = footer[0].text() if footer else ""
        citation_match = re.search(r"Cited by\s+(\d+)", footer_text, flags=re.I)
        citation_count = int(citation_match.group(1)) if citation_match else 0
        papers.append({
            "title": title,
            "year": paper_year,
            "venue": venue,
            "citationCount": citation_count,
            "authors": authors,
            "abstract": abstract,
            "url": url,
        })

    logger.info(f"Semantic Scholar 命中 {len(papers)} 篇")
    if not papers:
        return {"papers": [], "message": "未检索到匹配的论文。"}
    return {"papers": papers, "count": len(papers)}


# ---------- 本地自检 ----------

async def _self_check():
    """直接调用工具函数，确认两条数据通路都正常。"""
    print("\n🔍 MCP 工具自检")
    print("-" * 60)
    result = await search_arxiv("3D gaussian splatting", max_results=2)
    if result.get("papers"):
        for p in result["papers"]:
            print(f"  [arXiv] {p['published']} {p['title'][:70]}")
    else:
        print(f"  [arXiv] 无结果: {result.get('error') or result.get('message')}")

    result = await search_semantic_scholar("vision transformer", limit=2)
    if result.get("papers"):
        for p in result["papers"]:
            print(f"  [S2] {p['year']} 引用 {p['citationCount']} | {p['title'][:60]}")
    else:
        print(f"  [S2] 无结果: {result.get('error') or result.get('message')}")
    print("-" * 60)


# ---------- 启动 ----------

if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        asyncio.run(_self_check())
        sys.exit(0)

    logger.info(f"启动 LSB 学术检索 MCP 服务: http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}")
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
        path=MCP_PATH,
    )
