# RAG 设计与检索评测

## 1. 当前实现

```text
data/faqs.json
  → FAQEntry（问题/答案/类目/关键词）
  → 文档文本 = 问题 + 答案 + 类目 + 关键词
  → TfidfVectorizer(analyzer="char", ngram_range=(1,2), sublinear_tf=True)
  → 余弦相似度 top-k
  → 关键词/类目/安全加权
  → 返回 FAQMatch + sources
```

代码：`shopagent/knowledge.py`  
评测：`eval/rag_eval.py`、`eval/rag_report.md`

### 为什么用 TF-IDF 基线

- 25 条 FAQ 的规模，TF-IDF 稳定、零模型下载、零 API 成本。
- 字符 1-2 gram 对中文短查询召回好。
- 接口保持 `search(query) -> matches`，可以无缝替换 dense retriever。

## 2. 当前结果

```text
backend: tfidf-char-vector
queries: 25
Hit@1: 100.0%
Hit@3: 100.0%
MRR: 1.0000
```

注意：这是**自建检索集**，不是线上真实 query 分布。它证明“回归没坏”，不证明“所有用户都能搜到”。

## 3. 生产升级路线

### 3.1 Dense embedding

- 模型：`bge-m3`、`text-embedding-3-small`、`Qwen3-Embedding` 任选。
- 向量库：pgvector（已有 Postgres 时优先）、FAISS/Chroma（单机 demo）。
- Chunk：按 FAQ 条目或标题切；商品/政策文档按 300-500 字 + overlap。
- 检索：top-20 召回 → rerank top-5 → LLM 回答带引用。

### 3.2 混合检索

```text
score = 0.5 * dense_cosine + 0.3 * bm25 + 0.2 * keyword_boost
```

- 关键词精确命中（“12315”“SF 单号”“七天无理由”）用 BM25/关键词兜底。
- 语义问题（“拆开用过了还能退吗”）用 dense。

### 3.3 评测

- 检索：Hit@1、Hit@3、MRR、Recall@k。
- 回答：groundedness（是否引用 retrieved 内容）、citation accuracy、拒答率。
- 失败分类：未召回、召回错、答案与文档冲突、该拒答没拒答。

## 4. 面试怎么讲

> “我先用 TF-IDF 字符向量把 RAG 基线跑通，25 条查询 Hit@1 100%，接口保持可替换。生产我会换 bge-m3 + pgvector，做 hybrid + rerank，并用 Hit@k/MRR 和 groundedness 评测。现在的结果是回归基线，不是线上满意度。”

不要只说“我用了 RAG”，要能讲：

- chunk 怎么切
- embedding 选什么
- 召回多少、rerank 多少
- 怎么评测
- 检索不到时怎么拒答/转人工

## 5. 运行

```bash
python eval/rag_eval.py
```

输出 `eval/rag_report.md` / `eval/rag_report.json`。
