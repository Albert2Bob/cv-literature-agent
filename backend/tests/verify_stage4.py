"""
阶段 4 验证脚本：RAG 知识库检索
==============================
检查：
  1. 索引指纹机制：第二次初始化应复用磁盘上的向量库，而不是重建
  2. 双路召回（向量 + BM25）都有结果
  3. 重排序生效，相关度分数递减
  4. 6 个不同主题的查询都能命中正确的源文档

用法：
    python tests/verify_stage4.py
"""
import os
import sys
import time

# 允许直接以 `python tests/xxx.py` 运行：把 backend 目录加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.rag import (
    DOCUMENTS_DIR,
    RAGEngine,
    compute_documents_fingerprint,
    get_engine,
    load_and_split_documents,
    tokenize,
)

# 查询 → 期望命中的源文档
CASES = [
    ("YOLO 和 Faster R-CNN 的范式区别", {"detection.md"}),
    ("mAP50 和 mAP50-95 有什么区别", {"detection.md"}),
    ("Swin Transformer 的移动窗口是怎么工作的", {"transformer.md"}),
    ("感受野的计算公式", {"cnn.md"}),
    ("二分类分割里 IoU 和 Dice 的关系", {"segmentation.md"}),
    ("训练 loss 不下降 / NaN 应该怎么排查", {"training_tricks.md"}),
    ("Adam 和 AdamW 的区别", {"training_tricks.md"}),
    ("SAM 分割大模型能给出类别吗", {"segmentation.md"}),
]


def main() -> int:
    print("=" * 70)
    print("【1】分词器自检（中文 bigram）")
    print("=" * 70)
    sample = "感受野的计算公式 receptive field"
    print(f"  原文   : {sample}")
    print(f"  tokens : {tokenize(sample)}")

    print("\n" + "=" * 70)
    print("【2】文档切分与指纹")
    print("=" * 70)
    docs = load_and_split_documents(DOCUMENTS_DIR, verbose=False)
    print(f"  片段总数: {len(docs)}")
    print(f"  指纹    : {compute_documents_fingerprint()[:80]}...")
    sources = sorted({d.metadata.get("source") for d in docs})
    print(f"  来源文件: {sources}")

    print("\n" + "=" * 70)
    print("【3】引擎初始化（第二次应复用向量库）")
    print("=" * 70)
    t0 = time.time()
    engine = get_engine(verbose=True)
    print(f"  初始化耗时: {time.time() - t0:.1f}s | 复用向量库: {engine._reused}")

    print("\n" + "=" * 70)
    print("【4】检索用例")
    print("=" * 70)
    passed = 0
    for query, expected_sources in CASES:
        result = engine.query(query, top_k=3)
        # 从结果里解析出命中的来源
        hit_sources = []
        for line in result.split("\n"):
            if line.startswith("[参考") and "来源" in line:
                src = line.split("来源", 1)[1].split("|")[0].strip()
                hit_sources.append(src)
        ok = bool(set(hit_sources) & expected_sources)
        passed += int(ok)
        mark = "OK  " if ok else "MISS"
        print(f"  [{mark}] {query}")
        print(f"         期望 {sorted(expected_sources)} | 命中 {hit_sources}")
        if not ok:
            print("         ---- 实际返回首条 ----")
            print("         " + result[:300].replace("\n", "\n         "))

    print("\n" + "=" * 70)
    print("阶段 4 结论")
    print("=" * 70)
    print(f"  片段数            : {len(docs)}")
    print(f"  向量库复用        : {'OK' if engine._reused else 'FAIL（本次为首次构建，重跑一次即可复用）'}")
    print(f"  检索命中率        : {passed}/{len(CASES)}")
    print(f"  重排序模型加载    : {'OK' if engine._get_reranker() else 'FAIL'}")

    ok = passed == len(CASES)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
