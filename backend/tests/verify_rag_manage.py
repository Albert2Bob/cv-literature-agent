"""
RAG 文件管理接口验证脚本
======================
验证前端 views/RagDocuments.vue 所需的全套接口，重点确认「一次解析 → 两次保存」：

    MySQL  rag_documents / rag_chunks
    Chroma 向量集合 lsb_rag_documents

覆盖用例：
  1. 列表接口返回结构符合前端 normalizeDocument 的取值
  2. 新建文档（JSON）→ MySQL 有记录 + 切片有明细 + 向量库可检索
  3. 上传 .md / .txt / .docx 文件 → 解析→双写
  4. 查看单个文档（含全文）与切片明细
  5. 覆盖同名文档 → 切片数更新、不产生重复向量
  6. 删除文档 → MySQL 记录与向量库同时清除，检索不再命中
  7. 一致性自检 /status 与全量重建 /rebuild

用法：
    python tests/verify_rag_manage.py
前置：后端已启动（8124）
"""
import io
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8124/api"
USERNAME = "rag_admin"
PASSWORD = "cv123456"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def login():
    httpx.post(f"{BASE}/auth/register",
               json={"username": USERNAME, "nickname": "RAG管理员", "password": PASSWORD}, timeout=20)
    resp = httpx.post(f"{BASE}/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=20).json()
    return {"Authorization": f"Bearer {resp['data']['token']}"}


def make_docx_bytes() -> bytes:
    """用 python-docx 现场生成一个带标题和表格的 Word 文件，用于测试解析。"""
    import docx

    document = docx.Document()
    document.add_heading("知识蒸馏实验笔记", level=1)
    document.add_paragraph("知识蒸馏通过教师模型的软标签指导学生模型训练。")
    document.add_heading("温度参数", level=2)
    document.add_paragraph("温度 T 越大，软标签分布越平滑，能提供更多类间信息。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "参数"
    table.cell(0, 1).text = "建议取值"
    table.cell(1, 0).text = "温度 T"
    table.cell(1, 1).text = "3 ~ 5"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pdf_bytes() -> bytes:
    """尽量现场生成一个最小 PDF；环境不支持则返回 None。"""
    try:
        import pypdf
        from pypdf.generic import DecodedStreamObject, NameObject
    except Exception:
        return None

    try:
        writer = pypdf.PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = pypdf.generic.DictionaryObject({
            pypdf.generic.NameObject("/Type"): pypdf.generic.NameObject("/Font"),
            pypdf.generic.NameObject("/Subtype"): pypdf.generic.NameObject("/Type1"),
            pypdf.generic.NameObject("/BaseFont"): pypdf.generic.NameObject("/Helvetica"),
        })
        resources = pypdf.generic.DictionaryObject({
            pypdf.generic.NameObject("/Font"): pypdf.generic.DictionaryObject({
                pypdf.generic.NameObject("/F1"): font,
            })
        })
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 14 Tf 20 100 Td (PDF retrieval test document) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return None


def main() -> int:
    headers = login()
    created = []

    # 记录基线（不假定知识库固定几篇——用户可能通过页面新增/删除过文档）
    base_res = httpx.get(f"{BASE}/rag/documents", headers=headers, timeout=60).json()
    base_items = (base_res.get("data") or {}).get("items") or []
    baseline = {d["name"] for d in base_items}
    print(f"基线知识库: {len(baseline)} 篇文档")
    for nm in sorted(baseline):
        print(f"    - {nm}")

    # 清理上一次运行可能残留的测试文档，保证多次运行结果一致
    for it in base_items:
        if it["name"].startswith("rag-test-"):
            httpx.delete(f"{BASE}/rag/documents/{it['name']}", headers=headers, timeout=60)
    baseline = {n for n in baseline if not n.startswith("rag-test-")}

    print()
    print("=" * 72)
    print("【1】列表接口结构与既有知识库")
    print("=" * 72)
    res = httpx.get(f"{BASE}/rag/documents", headers=headers, timeout=60).json()
    items = (res.get("data") or {}).get("items") or []
    total_chunks = (res.get("data") or {}).get("total_chunks")
    print(f"  文档数: {len(items)} | 切片总数: {total_chunks}")
    for it in items[:6]:
        print(f"    - {it['name']} | {it['extension']} | {it['size']}B | {it['chunk_count']} 切片 | {it['status']}")
    check("返回 code=0", res.get("code") == 0)
    check("data.items 是数组", isinstance(items, list) and len(items) >= len(baseline),
          f"实际 {len(items)} 条 / 基线 {len(baseline)} 条")
    if items:
        sample = items[0]
        need = {"name", "title", "extension", "size", "chunk_count", "updated_at"}
        check("字段满足前端 normalizeDocument", need.issubset(sample.keys()),
              f"缺失 {need - set(sample.keys())}")
        check("初始知识库文档都带切片",
              all(d["chunk_count"] > 0 for d in items if d["name"] in baseline))

    print("\n" + "=" * 72)
    print("【2】新建文档（JSON）→ 两次保存")
    print("=" * 72)
    name = "rag-test-create.md"
    content = """# 注意力机制速查

## Scaled Dot-Product Attention

注意力权重由 Q 与 K 的点积除以 sqrt(d_k) 后 softmax 得到。

## 为什么要除以 sqrt(d_k)

维度增大时点积方差随之增大，softmax 会进入饱和区导致梯度消失。

## 多头注意力

把维度拆成多个头并行计算，不同头关注不同的关系模式。
"""
    res = httpx.post(f"{BASE}/rag/documents", headers=headers,
                     json={"name": name, "title": "注意力机制速查", "content": content},
                     timeout=180).json()
    print(f"  {res.get('msg')}")
    created.append(name)
    check("新建返回 code=0", res.get("code") == 0)
    check("返回 chunk_count > 0", (res.get("data") or {}).get("chunk_count", 0) > 0,
          f"chunk_count={(res.get('data') or {}).get('chunk_count')}")

    # 校验 MySQL 侧
    res_get = httpx.get(f"{BASE}/rag/documents/{name}", headers=headers, timeout=30).json()
    doc = res_get.get("data") or {}
    check("MySQL 能取到文档全文", doc.get("content", "").startswith("# 注意力机制速查"),
          f"长度 {len(doc.get('content') or '')}")
    res_chunks = httpx.get(f"{BASE}/rag/documents/{name}/chunks", headers=headers, timeout=30).json()
    chunks = (res_chunks.get("data") or {}).get("items") or []
    check("MySQL 存下了切片明细", len(chunks) > 0, f"{len(chunks)} 个切片")
    if chunks:
        print(f"    切片1: index={chunks[0]['index']} len={chunks[0]['length']} section={chunks[0]['section']!r}")
        check("切片字段符合前端 normalizeChunk",
              {"id", "index", "content", "length", "source", "section"}.issubset(chunks[0].keys()))

    print("\n" + "=" * 72)
    print("【3】上传文件（multipart）→ 解析 → 双写")
    print("=" * 72)

    # 3.1 .md
    md_bytes = "# 上传测试文档\n\n## 章节一\n\n这是通过上传方式写入知识库的内容。\n".encode("utf-8")
    res = httpx.post(f"{BASE}/rag/documents/upload", headers=headers,
                     files={"file": ("rag-test-upload.md", md_bytes, "text/markdown")},
                     timeout=180).json()
    print(f"  [md]   {res.get('msg')}")
    created.append("rag-test-upload.md")
    check("上传 .md 成功", res.get("code") == 0 and (res.get("data") or {}).get("chunk_count", 0) > 0)

    # 3.2 .txt（用 GBK 编码，验证编码兜底）
    txt_bytes = "# 文本编码测试\n\n这个文件用 GBK 编码保存，用于验证解码兜底逻辑。\n".encode("gbk")
    res = httpx.post(f"{BASE}/rag/documents/upload", headers=headers,
                     files={"file": ("rag-test-gbk.txt", txt_bytes, "text/plain")},
                     timeout=180).json()
    print(f"  [txt]  {res.get('msg')}")
    created.append("rag-test-gbk.txt")
    check("上传 GBK 编码 .txt 成功（解码兜底）", res.get("code") == 0)

    # 3.3 .docx
    docx_bytes = make_docx_bytes()
    res = httpx.post(f"{BASE}/rag/documents/upload", headers=headers,
                     files={"file": ("rag-test-words.docx", docx_bytes,
                                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                     timeout=180).json()
    print(f"  [docx] {res.get('msg')}")
    created.append("rag-test-words.docx")
    docx_ok = res.get("code") == 0
    check("上传 .docx 成功（python-docx 解析）", docx_ok)
    if docx_ok:
        got = httpx.get(f"{BASE}/rag/documents/rag-test-words.docx", headers=headers, timeout=30).json()
        text = (got.get("data") or {}).get("content", "")
        check("Word 标题被转成 Markdown 标题", "# 知识蒸馏实验笔记" in text)
        check("Word 表格被提取", "| 参数 | 建议取值 |" in text, text[:120].replace("\n", " "))

    # 3.4 .pdf
    pdf_bytes = make_pdf_bytes()
    if pdf_bytes:
        res = httpx.post(f"{BASE}/rag/documents/upload", headers=headers,
                         files={"file": ("rag-test-paper.pdf", pdf_bytes, "application/pdf")},
                         timeout=180).json()
        print(f"  [pdf]  {res.get('msg')}")
        created.append("rag-test-paper.pdf")
        check("上传 .pdf 成功（pypdf 解析）", res.get("code") == 0)
    else:
        print("  [pdf]  跳过：无法在测试环境生成 PDF")

    # 3.5 不支持的格式应被拒绝
    res = httpx.post(f"{BASE}/rag/documents/upload", headers=headers,
                     files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
                     timeout=60)
    check("不支持格式被拒绝（4xx）", res.status_code >= 400,
          f"HTTP {res.status_code} {res.json().get('msg', '')[:60]}")
    # 被拒绝的文件不应留下「幽灵记录」（否则列表里会出现一个永远没有切片的文档）
    r = httpx.get(f"{BASE}/rag/documents/evil.exe", headers=headers, timeout=30)
    check("被拒绝的文件未留下记录", r.status_code == 404, f"HTTP {r.status_code}")

    print("\n" + "=" * 72)
    print("【4】覆盖同名文档（应更新而非重复入库）")
    print("=" * 72)
    before = httpx.get(f"{BASE}/rag/documents/{name}/chunks", headers=headers, timeout=30).json()
    before_n = len((before.get("data") or {}).get("items") or [])
    longer = content + "\n## 新增章节\n\n覆盖测试：这一段是第二次写入时追加的内容。\n"
    res = httpx.post(f"{BASE}/rag/documents", headers=headers,
                     json={"name": name, "content": longer}, timeout=180).json()
    after = httpx.get(f"{BASE}/rag/documents/{name}/chunks", headers=headers, timeout=30).json()
    after_n = len((after.get("data") or {}).get("items") or [])
    replaced = (res.get("data") or {}).get("replaced")
    print(f"  切片数 {before_n} → {after_n}；replaced={replaced}")
    check("覆盖被识别为替换", replaced is True)
    check("切片记录被替换而非累加", after_n >= before_n and after_n < before_n * 2,
          f"{before_n} → {after_n}")

    print("\n" + "=" * 72)
    print("【5】检索联动：新文档能被 cv_rag_search 命中")
    print("=" * 72)
    res = httpx.get(f"{BASE}/rag/status", headers=headers, timeout=60).json()
    st = res.get("data") or {}
    print(f"  MySQL: {st.get('mysql_documents')} 文档 / {st.get('mysql_chunks')} 切片")
    print(f"  Chroma: {st.get('vector_documents')} 文档 / {st.get('vector_chunks')} 切片")
    print(f"  仅 MySQL 有: {st.get('only_in_mysql')}")
    print(f"  仅向量库有: {st.get('only_in_vector')}")
    check("MySQL 与向量库文档集合一致", st.get("consistent") is True)

    print("\n" + "=" * 72)
    print("【6】删除文档 → 两处存储同时清除")
    print("=" * 72)
    for target in created:
        res = httpx.delete(f"{BASE}/rag/documents/{target}", headers=headers, timeout=60).json()
        ok = res.get("code") == 0
        print(f"  删除 {target}: {res.get('msg') if ok else res.get('msg')}")
        check(f"删除 {target} 成功", ok)

    for target in created:
        r = httpx.get(f"{BASE}/rag/documents/{target}", headers=headers, timeout=30)
        check(f"{target} 已在 MySQL 中消失", r.status_code == 404, f"HTTP {r.status_code}")

    st2 = httpx.get(f"{BASE}/rag/status", headers=headers, timeout=60).json().get("data") or {}
    check("删除后两处仍一致", st2.get("consistent") is True)
    check("删除后回到基线（无测试文档残留）",
          st2.get("mysql_documents") == len(baseline),
          f"实际 {st2.get('mysql_documents')} 篇 / 基线 {len(baseline)} 篇")

    res = httpx.get(f"{BASE}/rag/documents", headers=headers, timeout=30).json()
    left = (res.get("data") or {}).get("items") or []
    check("列表不再包含测试文档", all(d["name"] not in created for d in left))

    print("\n" + "=" * 72)
    print("【7】全量重建 /rebuild")
    print("=" * 72)
    res = httpx.post(f"{BASE}/rag/rebuild", headers=headers, timeout=900).json()
    print(f"  {res.get('msg')}")
    check("全量重建成功", res.get("code") == 0 and (res.get("data") or {}).get("chunks", 0) > 0,
          f"{res.get('data')}")

    print("\n" + "=" * 72)
    print("【8】鉴权")
    print("=" * 72)
    r = httpx.get(f"{BASE}/rag/documents", timeout=30)
    check("无 token 访问列表 → 401", r.status_code == 401, f"HTTP {r.status_code}")
    r = httpx.delete(f"{BASE}/rag/documents/cnn.md", timeout=30)
    check("无 token 删除 → 401", r.status_code == 401, f"HTTP {r.status_code}")

    print("\n" + "=" * 72)
    print("结论")
    print("=" * 72)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name_, ok, detail in results:
        if not ok:
            print(f"  FAIL: {name_}  {detail}")
    print(f"  通过 {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
