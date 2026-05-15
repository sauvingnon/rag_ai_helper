"""
RAG Evaluation Script — ИжГТУ Голосовой Ассистент

Запуск:
    python evaluate.py [--host http://localhost:8005] [--ref reference_answers.yaml]

Требования: Docker-сервисы подняты (ai_service на порту 8005).

Метрики:
  - Context Relevance   — средний Cross-Encoder score топ-1 чанка
  - Answer Relevance    — cosine_sim(SBERT(вопрос), SBERT(ответ))
  - Out-of-scope Rate   — % корректных отказов для вопросов вне базы
  - Latency             — retrieval / rerank / e2e (мс)
  - Hit Rate@1, @5      — попадание эталонного чанка в топ-K после CE-ранжирования
  - MRR@5               — Mean Reciprocal Rank
  - NDCG@5              — нормализованный дисконтированный кумулятивный выигрыш
  - (опц.) ROUGE-L      — если заполнен reference_answers.yaml
  - (опц.) BERTScore F1 — если заполнен reference_answers.yaml
"""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import yaml

# ─── Конфигурация ────────────────────────────────────────────────────────────

DEFAULT_HOST = "http://localhost:8005"
QUESTIONS_FILE = Path(__file__).parent.parent / "Тесты.txt"
RESULTS_DIR = Path(__file__).parent / "results"

OUT_OF_SCOPE_MARKERS = [
    "не знаю", "не могу найти", "нет информации", "не нашла",
    "не смогла найти", "отсутствует в базе", "нет данных",
    "не располагаю", "не содержит информации", "к сожалению",
]


# ─── Парсинг вопросов ─────────────────────────────────────────────────────────

_QUESTION_STARTERS = (
    "хочу", "хотел", "хотела", "расскажи", "интересует",
    "интересуюсь", "объясни", "помоги", "покажи",
)


def _is_question(line: str) -> bool:
    if "?" in line:
        return True
    return line.lower().startswith(_QUESTION_STARTERS)


def parse_questions(path: Path) -> list[dict]:
    """Читает Тесты.txt и возвращает список {category, question, id}."""
    questions = []
    current_category = "Без категории"
    qid = 1
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if _is_question(line):
            questions.append({
                "id": qid,
                "category": current_category,
                "question": line,
            })
            qid += 1
        else:
            current_category = line
    return questions


# ─── HTTP вызовы к ai_service ─────────────────────────────────────────────────

def call_eval_full(host: str, question: str) -> dict:
    """Один вызов: полный агентский цикл + метрики retrieval."""
    resp = requests.post(
        f"{host}/ai_service/eval_full",
        json={"question": question},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def call_embed(host: str, texts: list[str]) -> list[list[float]]:
    resp = requests.post(f"{host}/ai_service/embed", json={"texts": texts}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"]


# ─── Вычисление метрик ────────────────────────────────────────────────────────

def cosine_sim(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def is_out_of_scope_correct(answer: str, filtered: bool) -> bool:
    """True если система корректно отказала или не нашла."""
    if filtered:
        return True
    low = answer.lower()
    return any(m in low for m in OUT_OF_SCOPE_MARKERS)


def rouge_l(hypothesis: str, reference: str) -> float:
    """ROUGE-L F1 на уровне слов."""
    hyp = hypothesis.lower().split()
    ref = reference.lower().split()
    if not hyp or not ref:
        return 0.0
    # LCS длина
    m, n = len(ref), len(hyp)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    p = lcs / n if n else 0
    r = lcs / m if m else 0
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def compute_bertscore(hypotheses: list[str], references: list[str], host: str) -> list[float]:
    """BERTScore F1 через SBERT-эмбеддинги (приближение через cosine similarity)."""
    all_texts = hypotheses + references
    all_embs = call_embed(host, all_texts)
    n = len(hypotheses)
    scores = []
    for i in range(n):
        scores.append(cosine_sim(all_embs[i], all_embs[n + i]))
    return scores


# ─── Загрузка эталонов ────────────────────────────────────────────────────────

def load_reference_answers(path: Path) -> dict[str, str]:
    """Возвращает {вопрос: эталонный_ответ}. Пустые ответы пропускаются."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    result = {}
    for item in data:
        q = item.get("question", "").strip()
        a = item.get("reference", "").strip()
        if q and a:
            result[q] = a
    return result


def load_relevant_chunks(path: Path) -> dict[str, str]:
    """Возвращает {вопрос: имя_эталонного_чанка}. Пустые значения пропускаются."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    result = {}
    for item in data:
        q = item.get("question", "").strip()
        c = item.get("relevant_chunk", "").strip()
        if q and c:
            result[q] = c
    return result


# ─── Метрики ранжирования ──────────────────────────────────────────────────────

def hit_rate_at_k(chunk_lists: list[list[str]], relevant: str, k: int) -> int:
    """1 если эталонный чанк есть в топ-k хотя бы одного поиска."""
    for chunks in chunk_lists:
        if relevant in chunks[:k]:
            return 1
    return 0


def mrr_at_k(chunk_lists: list[list[str]], relevant: str, k: int) -> float:
    """Reciprocal Rank: лучший (максимальный) 1/(rank+1) среди всех поисков."""
    best_rr = 0.0
    for chunks in chunk_lists:
        for i, ch in enumerate(chunks[:k]):
            if ch == relevant:
                best_rr = max(best_rr, 1.0 / (i + 1))
                break
    return best_rr


def ndcg_at_k(chunk_list: list[str], relevant: str, k: int) -> float:
    """NDCG@K с бинарной релевантностью (один эталонный чанк).
    IDCG = 1.0 (если бы эталон стоял первым).
    """
    for i, ch in enumerate(chunk_list[:k]):
        if ch == relevant:
            return 1.0 / math.log2(i + 2)
    return 0.0


# ─── Агрегация результатов ────────────────────────────────────────────────────

def avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def fmt(v: float, decimals: int = 3) -> str:
    return f"{v:.{decimals}f}"


def build_category_stats(results: list[dict]) -> dict:
    from collections import defaultdict
    cats: dict[str, list] = defaultdict(list)
    for r in results:
        cats[r["category"]].append(r)

    stats = {}
    for cat, rows in cats.items():
        ctx_rels = [r["context_relevance"] for r in rows if r["context_relevance"] is not None]
        ans_rels = [r["answer_relevance"] for r in rows if r["answer_relevance"] is not None]
        ret_lats = [r["retrieval_latency_ms"] for r in rows]
        rer_lats = [r["rerank_latency_ms"] for r in rows]
        filtered = [r for r in rows if r["filtered_by_threshold"]]
        rouge_vals = [r["rouge_l"] for r in rows if r.get("rouge_l") is not None]
        bert_vals = [r["bertscore"] for r in rows if r.get("bertscore") is not None]

        rank_rows = [r for r in rows if r.get("hit_at_1") is not None]
        stats[cat] = {
            "n": len(rows),
            "context_relevance_avg": avg(ctx_rels),
            "answer_relevance_avg": avg(ans_rels),
            "retrieval_latency_avg_ms": avg(ret_lats),
            "rerank_latency_avg_ms": avg(rer_lats),
            "total_latency_avg_ms": avg([r["total_latency_ms"] for r in rows]),
            "filtered_rate": len(filtered) / len(rows),
            "rouge_l_avg": avg(rouge_vals) if rouge_vals else None,
            "bertscore_avg": avg(bert_vals) if bert_vals else None,
            "hit_at_1": avg([r["hit_at_1"] for r in rank_rows]) if rank_rows else None,
            "hit_at_5": avg([r["hit_at_5"] for r in rank_rows]) if rank_rows else None,
            "mrr_at_5": avg([r["mrr_at_5"] for r in rank_rows]) if rank_rows else None,
            "ndcg_at_5": avg([r["ndcg_at_5"] for r in rank_rows]) if rank_rows else None,
            "n_ranked": len(rank_rows),
        }
    return stats


# ─── Текстовый отчёт ──────────────────────────────────────────────────────────

def render_report(results: list[dict], cat_stats: dict, run_ts: str) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"  RAG EVALUATION REPORT — ИжГТУ Ассистент")
    lines.append(f"  {run_ts}  |  вопросов: {len(results)}")
    lines.append("=" * 70)

    # ── Глобальные метрики ────────────────────────────────────────────────────
    ctx = [r["context_relevance"] for r in results if r["context_relevance"] is not None]
    ans = [r["answer_relevance"] for r in results if r["answer_relevance"] is not None]
    total_lat = [r["total_latency_ms"] for r in results]
    ret_lat = [r["retrieval_latency_ms"] for r in results]
    rer_lat = [r["rerank_latency_ms"] for r in results]


    lines.append("")
    lines.append("ГЛОБАЛЬНЫЕ МЕТРИКИ")
    lines.append("-" * 40)
    lines.append(f"  Context Relevance (avg)   : {fmt(avg(ctx))}")
    lines.append(f"  Answer Relevance  (avg)   : {fmt(avg(ans))}")
    lines.append(f"  End-to-end latency (avg)  : {avg(total_lat):.0f} ms  (полный цикл: retrieval+LLM)")
    lines.append(f"  Retrieval isolated (avg)  : {avg(ret_lat)+avg(rer_lat):.0f} ms")
    lines.append(f"    ├─ SBERT search          : {avg(ret_lat):.0f} ms")
    lines.append(f"    └─ Cross-Encoder rerank   : {avg(rer_lat):.0f} ms")
    lines.append(f"  (ret/rer — изолированные замеры внутри eval_full; e2e включает LLM)")

    # Out-of-scope категория
    oos_rows = [r for r in results if "за пределами" in r["category"].lower()]
    if oos_rows:
        correct = sum(1 for r in oos_rows if r.get("oos_correct"))
        lines.append("")
    lines.append(f"  Out-of-scope Detection    : {correct}/{len(oos_rows)} = {correct/len(oos_rows)*100:.0f}%"
                 if oos_rows else "  Out-of-scope: нет вопросов этой категории")

    # ROUGE / BERTScore (если есть)
    rouge_vals = [r["rouge_l"] for r in results if r.get("rouge_l") is not None]
    bert_vals = [r["bertscore"] for r in results if r.get("bertscore") is not None]
    if rouge_vals:
        lines.append(f"  ROUGE-L (avg)             : {fmt(avg(rouge_vals))}")
    if bert_vals:
        lines.append(f"  BERTScore F1 (avg)        : {fmt(avg(bert_vals))}")

    # Ranking metrics (если есть relevant_chunk в YAML)
    ranked = [r for r in results if r.get("hit_at_1") is not None]
    if ranked:
        lines.append("")
        lines.append(f"  Retrieval Ranking  (n={len(ranked)})")
        lines.append(f"    Hit Rate@1              : {fmt(avg([r['hit_at_1'] for r in ranked]))}")
        lines.append(f"    Hit Rate@5              : {fmt(avg([r['hit_at_5'] for r in ranked]))}")
        lines.append(f"    MRR@5                   : {fmt(avg([r['mrr_at_5'] for r in ranked]))}")
        lines.append(f"    NDCG@5                  : {fmt(avg([r['ndcg_at_5'] for r in ranked]))}")

    # ── Метрики по категориям ─────────────────────────────────────────────────
    lines.append("")
    lines.append("МЕТРИКИ ПО КАТЕГОРИЯМ")
    lines.append("-" * 70)
    header = f"{'Категория':<38} {'N':>3}  {'CtxRel':>6}  {'AnsRel':>6}  {'Total(ms)':>9}  {'Filter%':>7}"
    lines.append(header)
    lines.append("-" * 70)

    for cat, s in cat_stats.items():
        filt_pct = f"{s['filtered_rate']*100:.0f}%"
        row = (
            f"{cat[:37]:<38} {s['n']:>3}  "
            f"{fmt(s['context_relevance_avg']):>6}  "
            f"{fmt(s['answer_relevance_avg']):>6}  "
            f"{s['total_latency_avg_ms']:>9.0f}  "
            f"{filt_pct:>7}"
        )
        lines.append(row)

    if rouge_vals or bert_vals:
        lines.append("")
        lines.append("ROUGE-L / BERTScore ПО КАТЕГОРИЯМ")
        lines.append("-" * 50)
        for cat, s in cat_stats.items():
            r = s.get("rouge_l_avg")
            b = s.get("bertscore_avg")
            if r is not None or b is not None:
                r_str = fmt(r) if r is not None else "  —  "
                b_str = fmt(b) if b is not None else "  —  "
                lines.append(f"  {cat[:35]:<36}  ROUGE-L={r_str}  BERTScore={b_str}")

    # Ranking metrics by category
    cats_with_ranking = {cat: s for cat, s in cat_stats.items() if s.get("hit_at_1") is not None}
    if cats_with_ranking:
        lines.append("")
        lines.append("РАНЖИРОВАНИЕ ПО КАТЕГОРИЯМ  (Hit@1 / Hit@5 / MRR@5 / NDCG@5)")
        lines.append("-" * 70)
        for cat, s in cats_with_ranking.items():
            nr = s["n_ranked"]
            h1 = fmt(s["hit_at_1"])
            h5 = fmt(s["hit_at_5"])
            mrr = fmt(s["mrr_at_5"])
            nd = fmt(s["ndcg_at_5"])
            lines.append(f"  {cat[:34]:<35} n={nr:>2}  {h1} / {h5} / {mrr} / {nd}")

    # ── Детали по вопросам ────────────────────────────────────────────────────
    lines.append("")
    lines.append("ДЕТАЛИ ПО ВОПРОСАМ")
    lines.append("-" * 70)
    for r in results:
        ctx_str = fmt(r["context_relevance"]) if r["context_relevance"] is not None else "  —  "
        ans_str = fmt(r["answer_relevance"]) if r["answer_relevance"] is not None else "  —  "
        filt = "FILTERED" if r["filtered_by_threshold"] else ""
        oos_str = ""
        if "за пределами" in r["category"].lower():
            oos_str = "✓" if r.get("oos_correct") else "✗"
        lines.append(
            f"[{r['id']:02d}] {r['question'][:50]:<51}"
            f" CtxRel={ctx_str}  AnsRel={ans_str}"
            f"  {filt:<8}{oos_str}"
        )
        rank_detail = ""
        if r.get("hit_at_1") is not None:
            rank_detail = (
                f"  Hit@1={r['hit_at_1']} Hit@5={r['hit_at_5']}"
                f" MRR={fmt(r['mrr_at_5'])} NDCG={fmt(r['ndcg_at_5'])}"
                f" [gt={r.get('relevant_chunk','?')[:25]}]"
            )
        lines.append(
            f"       ↳ e2e={r['total_latency_ms']:.0f}ms"
            f" [ret={r['retrieval_latency_ms']:.0f}ms rer={r['rerank_latency_ms']:.0f}ms]"
            f"{rank_detail}"
        )
        lines.append(f"         {r['answer'][:100]}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


# ─── Основной цикл ────────────────────────────────────────────────────────────

def run_evaluation(host: str, ref_path: Path) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)

    questions = parse_questions(QUESTIONS_FILE)
    references = load_reference_answers(ref_path)
    relevant_chunks = load_relevant_chunks(ref_path)

    print(f"Загружено вопросов: {len(questions)}")
    if references:
        print(f"Загружено эталонных ответов: {len(references)}")
    else:
        print("Эталонные ответы не найдены — ROUGE-L и BERTScore не будут вычислены")
    if relevant_chunks:
        print(f"Загружено эталонных чанков: {len(relevant_chunks)} — будут вычислены Hit Rate / MRR / NDCG")
    print(f"Сервис: {host}")
    print()

    results = []
    for q in questions:
        question = q["question"]
        print(f"[{q['id']:02d}/{len(questions)}] {question[:60]}", end=" ... ", flush=True)

        # ── Один вызов: retrieval + generation ───────────────────────────────
        try:
            ev = call_eval_full(host, question)
        except Exception as e:
            print(f"ОШИБКА eval_full: {e}")
            continue

        answer = ev["answer"]
        total_ms = ev["total_ms"]
        context_relevance = ev["best_score"]
        filtered = ev["filtered_by_threshold"]
        ret_ms = ev["search_ms_total"]
        rer_ms = ev["rerank_ms_total"]

        # ── Answer Relevance ──────────────────────────────────────────────────
        try:
            embs = call_embed(host, [question, answer])
            answer_relevance = cosine_sim(embs[0], embs[1])
        except Exception:
            answer_relevance = None

        # ── Out-of-scope detection ────────────────────────────────────────────
        oos_correct = None
        if "за пределами" in q["category"].lower():
            oos_correct = is_out_of_scope_correct(answer, filtered)

        # ── ROUGE-L / BERTScore (если есть эталон) ───────────────────────────
        rouge = None
        ref_answer = references.get(question)
        if ref_answer:
            rouge = rouge_l(answer, ref_answer)

        # ── Ranking metrics (если есть relevant_chunk в YAML) ────────────────
        rel_chunk = relevant_chunks.get(question)
        search_log_data = ev.get("search_log", [])
        # Собираем top_chunks из непрофильтрованных поисков
        all_top_chunks = [
            s.get("top_chunks", []) for s in search_log_data if not s.get("filtered")
        ]

        hit1 = hit5 = mrr5 = ndcg5 = None
        if rel_chunk and all_top_chunks:
            hit1 = hit_rate_at_k(all_top_chunks, rel_chunk, 1)
            hit5 = hit_rate_at_k(all_top_chunks, rel_chunk, 5)
            mrr5 = mrr_at_k(all_top_chunks, rel_chunk, 5)
            # NDCG используем список первого (или лучшего) поиска
            best_list = max(
                all_top_chunks,
                key=lambda cl: 1 if rel_chunk in cl else 0,
                default=all_top_chunks[0],
            )
            ndcg5 = ndcg_at_k(best_list, rel_chunk, 5)

        row = {
            "id": q["id"],
            "category": q["category"],
            "question": question,
            "answer": answer,
            "context_relevance": round(float(context_relevance), 4) if context_relevance is not None else None,
            "answer_relevance": round(answer_relevance, 4) if answer_relevance is not None else None,
            "filtered_by_threshold": filtered,
            "retrieval_latency_ms": round(ret_ms, 1),
            "rerank_latency_ms": round(rer_ms, 1),
            "total_latency_ms": round(total_ms, 1),
            "oos_correct": oos_correct,
            "rouge_l": round(rouge, 4) if rouge is not None else None,
            "bertscore": None,  # вычислим ниже батчом
            "top_chunk": ev.get("top_chunk"),
            "search_count": ev.get("search_count", 0),
            "relevant_chunk": rel_chunk,
            "hit_at_1": hit1,
            "hit_at_5": hit5,
            "mrr_at_5": round(mrr5, 4) if mrr5 is not None else None,
            "ndcg_at_5": round(ndcg5, 4) if ndcg5 is not None else None,
        }
        results.append(row)
        rank_str = ""
        if hit1 is not None:
            rank_str = f"  Hit@1={hit1} Hit@5={hit5} MRR={fmt(mrr5)} NDCG={fmt(ndcg5)}"
        print(f"CtxRel={fmt(float(context_relevance)) if context_relevance else '—'}  "
              f"AnsRel={fmt(answer_relevance) if answer_relevance else '—'}  "
              f"e2e={total_ms:.0f}ms  retrieval=[ret={ret_ms:.0f} rer={rer_ms:.0f}]ms"
              f"{rank_str}")

    # ── BERTScore батчом (если есть эталоны) ──────────────────────────────────
    rows_with_ref = [(i, r) for i, r in enumerate(results) if references.get(r["question"])]
    if rows_with_ref:
        print("\nВычисляю BERTScore батчом...")
        hyps = [r["answer"] for _, r in rows_with_ref]
        refs = [references[r["question"]] for _, r in rows_with_ref]
        try:
            bscores = compute_bertscore(hyps, refs, host)
            for (i, _), bs in zip(rows_with_ref, bscores):
                results[i]["bertscore"] = round(bs, 4)
        except Exception as e:
            print(f"BERTScore ошибка: {e}")

    # ── Агрегация ─────────────────────────────────────────────────────────────
    cat_stats = build_category_stats(results)
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_text = render_report(results, cat_stats, run_ts)

    # ── Сохранение ────────────────────────────────────────────────────────────
    json_path = RESULTS_DIR / f"eval_{ts_file}.json"
    txt_path = RESULTS_DIR / f"eval_{ts_file}.txt"

    json_path.write_text(
        json.dumps({"timestamp": run_ts, "results": results, "category_stats": cat_stats},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(report_text, encoding="utf-8")

    print()
    print(report_text)
    print(f"\nРезультаты сохранены:")
    print(f"  JSON : {json_path}")
    print(f"  Текст: {txt_path}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Evaluation")
    parser.add_argument("--host", default=DEFAULT_HOST, help="URL ai_service")
    parser.add_argument(
        "--ref",
        default=str(Path(__file__).parent / "reference_answers.yaml"),
        help="Путь к файлу с эталонными ответами",
    )
    args = parser.parse_args()
    run_evaluation(host=args.host, ref_path=Path(args.ref))
