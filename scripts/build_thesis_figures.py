"""Build figures for the thesis Chapter 3.

Reads campaign artifacts under test_runs/campaigns and produces PNGs
in docs/figures/. All figures use Cyrillic-capable fonts and a
matplotlib style suitable for embedding into a Word document.
"""
from __future__ import annotations
import json
import os
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "figure.dpi": 140,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    }
)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

CAMPAIGNS = {
    "Qwen 3.6 Plus": "stage2-extended-qwen36",
    "Gemini 3 Flash": "stage3-gemini3-flash",
    "DeepSeek V4 Pro": "stage5-deepseek-extended",
    "MiniMax M2.7": "stage7-minimax-extended",
    "Sonnet 4.6": "stage6-sonnet-extended",
}
MODELS = list(CAMPAIGNS.keys())
MODE_NAMES = {0: "Mode 0\nDirect", 1: "Mode 1\nAdapter", 2: "Mode 2\nLLM×2", 3: "Mode 3\nHybrid"}


def load_runs(cid: str):
    base = ROOT / "test_runs" / "campaigns" / cid
    camp = json.loads((base / "campaign.json").read_text(encoding="utf-8"))
    out = []
    for rid, meta in camp["runs"].items():
        p = base / "runs" / rid / "run_summary.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text(encoding="utf-8"))
        out.append(
            {
                "rid": rid,
                "case": meta["case_id"],
                "mode": meta["mode"],
                "status": meta["status"],
                "imp": s.get("nifi_import_success"),
                "errs": s.get("nifi_error_count"),
                "procs": s.get("nifi_processor_count") or 0,
                "dur": s.get("duration_sec") or 0,
                "tok": s.get("total_tokens") or 0,
                "usd": s.get("cost_usd") or 0,
            }
        )
    return out


def classify(r):
    if r["status"] == "failed_generation":
        return "fail_gen"
    if r["imp"] and r["procs"] > 0 and r["errs"] == 0:
        return "zero_err"
    if r["imp"] and r["procs"] > 0:
        return "imp_real"
    if r["imp"] and r["procs"] == 0:
        return "empty_pg"
    return "fail_imp"


# ---------------------------------------------------------------- fig 1
# Heatmap: 5 models × 4 modes, cell = useful imports (procs>0) / total.
def fig_heatmap_useful():
    data = np.zeros((len(MODELS), 4), dtype=float)
    totals = np.zeros((len(MODELS), 4), dtype=int)
    annot = np.empty((len(MODELS), 4), dtype=object)
    for i, m in enumerate(MODELS):
        runs = load_runs(CAMPAIGNS[m])
        for mode in range(4):
            r_mode = [r for r in runs if r["mode"] == mode]
            useful = sum(1 for r in r_mode if r["imp"] and r["procs"] > 0)
            data[i, mode] = useful
            totals[i, mode] = len(r_mode)
            annot[i, mode] = f"{useful}/{len(r_mode)}" if r_mode else "—"

    fig, ax = plt.subplots(figsize=(8, 4.2))
    im = ax.imshow(data, cmap="YlGn", vmin=0, vmax=7, aspect="auto")
    ax.set_xticks(range(4))
    ax.set_xticklabels([MODE_NAMES[m] for m in range(4)])
    ax.set_yticks(range(len(MODELS)))
    ax.set_yticklabels(MODELS)
    for i in range(len(MODELS)):
        for j in range(4):
            ax.text(j, i, annot[i, j], ha="center", va="center",
                    color="black" if data[i, j] < 4 else "white", fontsize=11)
    ax.set_title("Полезные импорты (число процессоров > 0) — 5 моделей × 4 режима")
    cbar = plt.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cbar.set_label("Полезных импортов из 7 кейсов")
    plt.savefig(FIG / "fig_heatmap_useful_imports.png")
    plt.close(fig)


# ---------------------------------------------------------------- fig 2
# Aggregate by mode across all 5 models — stacked bar.
def fig_modes_aggregate():
    cats = ["zero_err", "imp_real", "empty_pg", "fail_imp", "fail_gen"]
    labels = {
        "zero_err": "Импорт с 0 ошибок и procs>0",
        "imp_real": "Импорт с ошибками, procs>0",
        "empty_pg": "Импорт, но пустой PG",
        "fail_imp": "Ошибка импорта",
        "fail_gen": "Ошибка генерации",
    }
    colors = {
        "zero_err": "#2E7D32",
        "imp_real": "#9CCC65",
        "empty_pg": "#FFB300",
        "fail_imp": "#E57373",
        "fail_gen": "#B71C1C",
    }
    data = {c: [0, 0, 0, 0] for c in cats}
    for m in MODELS:
        for r in load_runs(CAMPAIGNS[m]):
            data[classify(r)][r["mode"]] += 1
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    x = np.arange(4)
    bottom = np.zeros(4)
    for c in cats:
        vals = np.array(data[c])
        ax.bar(x, vals, bottom=bottom, label=labels[c], color=colors[c], edgecolor="white", linewidth=0.5)
        for j, v in enumerate(vals):
            if v > 0:
                ax.text(j, bottom[j] + v / 2, str(v), ha="center", va="center", fontsize=10,
                        color="white" if c in ("zero_err", "fail_gen") else "black")
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels([MODE_NAMES[m] for m in range(4)])
    ax.set_ylabel("Запусков (всего по 5 моделям)")
    ax.set_title("Агрегат результатов по режиму через все 5 моделей × 7 кейсов")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9)
    plt.savefig(FIG / "fig_modes_aggregate.png")
    plt.close(fig)


# ---------------------------------------------------------------- fig 3
# Dispersion (stage4) — values of errs per case across 3 reps.
def fig_dispersion():
    base = ROOT / "test_runs" / "campaigns" / "stage4-dispersion-and-tc12"
    camp = json.loads((base / "campaign.json").read_text(encoding="utf-8"))
    dis = {}
    for rid, meta in camp["runs"].items():
        if "tc12" in rid:
            continue
        p = base / "runs" / rid / "run_summary.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text(encoding="utf-8"))
        if s.get("nifi_error_count") is None:
            continue
        dis.setdefault(meta["case_id"], []).append(s["nifi_error_count"])
    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    cases = sorted(dis)
    positions = np.arange(len(cases))
    for i, c in enumerate(cases):
        vals = dis[c]
        ax.scatter([i] * len(vals), vals, s=80, alpha=0.75, edgecolor="black", linewidth=0.6,
                    color="#1976D2")
        if len(vals) > 1:
            mean = statistics.mean(vals)
            std = statistics.stdev(vals)
            ax.errorbar([i], [mean], yerr=[std], fmt="_", color="black",
                        capsize=10, elinewidth=1.5, markersize=20)
            ax.text(i, mean + std + 0.3, f"μ={mean:.1f}\nσ={std:.1f}",
                    ha="center", va="bottom", fontsize=9)
    ax.set_xticks(positions)
    ax.set_xticklabels([c.replace("-", "\n") for c in cases])
    ax.set_ylabel("Число ошибок валидации NiFi")
    ax.set_title("Дисперсия в режиме адаптера (Qwen 3.6 Plus, повторений на конфигурацию: 3)")
    ax.set_ylim(-0.5, max(max(v) for v in dis.values()) + 1.5)
    ax.grid(axis="y", alpha=0.3)
    plt.savefig(FIG / "fig_dispersion.png")
    plt.close(fig)


# ---------------------------------------------------------------- fig 4
# Cost-vs-quality scatter across 5 models.
def fig_cost_quality():
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    pts = []
    for m in MODELS:
        runs = load_runs(CAMPAIGNS[m])
        errs = [r["errs"] for r in runs if r["imp"] and r["procs"] > 0 and r["errs"] is not None]
        cost = sum(r["usd"] for r in runs)
        useful = sum(1 for r in runs if r["imp"] and r["procs"] > 0)
        if errs:
            avg = statistics.mean(errs)
        else:
            avg = 0
        pts.append((m, cost, avg, useful))
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    sizes = [200 + 80 * p[3] for p in pts]
    colors = ["#1976D2", "#388E3C", "#F57C00", "#7B1FA2", "#C2185B"]
    ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.8, edgecolor="black", linewidth=1.0)
    for (m, c, e, u), x, y in zip(pts, xs, ys):
        ax.annotate(f"{m}\n({u} полезных)", (x, y), xytext=(8, 8), textcoords="offset points", fontsize=9)
    ax.set_xlabel("Суммарная стоимость кампании, USD")
    ax.set_ylabel("Среднее число ошибок валидации NiFi")
    ax.set_xscale("log")
    ax.set_title("Экономика моделей: стоимость vs качество структуры (28 запусков на модель)")
    ax.grid(True, alpha=0.3)
    plt.savefig(FIG / "fig_cost_quality.png")
    plt.close(fig)


# ---------------------------------------------------------------- fig 5
# Manual vs FlowArchitect TC-01 time bar.
def fig_manual_vs_proto():
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    labels = ["TC-01\nHTTP→File", "TC-03\nPG→File"]
    manual = [18, 40]
    proto = [2.5, 12.5]
    x = np.arange(len(labels))
    w = 0.36
    b1 = ax.bar(x - w/2, manual, w, label="Ручная разработка", color="#E57373", edgecolor="black", linewidth=0.5)
    b2 = ax.bar(x + w/2, proto, w, label="FlowArchitect", color="#66BB6A", edgecolor="black", linewidth=0.5)
    for b, v, suffix in zip(list(b1) + list(b2),
                            manual + proto,
                            ["", " (не доведено)", "", " (оценка с учётом DBCP)"]):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.6, f"{v} мин{suffix}", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Время разработки, минут")
    ax.set_title("Контрольный замер: ручная разработка vs FlowArchitect")
    ax.legend()
    ax.set_ylim(0, max(manual) * 1.25)
    plt.savefig(FIG / "fig_manual_vs_proto.png")
    plt.close(fig)


def fig_m1_vs_m3():
    """Paired comparison of Mode 1 vs Mode 3 across all models.

    Shows that LLM correction (Mode 3) is neutral on average: improves
    in ~38% of cases, worsens in ~33%, no change in ~29%. Token cost
    is uniformly higher (full-document rewrite)."""
    points = []  # (model, case, e1, e3, t1, t3)
    for model, cid in CAMPAIGNS.items():
        runs = load_runs(cid)
        by_case = {}
        for r in runs:
            by_case.setdefault(r["case"], {})[r["mode"]] = r
        for case, mm in by_case.items():
            r1 = mm.get(1); r3 = mm.get(3)
            if not r1 or not r3: continue
            if not (r1["imp"] and r1["procs"] > 0 and r3["imp"] and r3["procs"] > 0): continue
            if r1["errs"] is None or r3["errs"] is None: continue
            points.append((model, case, r1["errs"], r3["errs"], r1["tok"], r3["tok"]))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.0), gridspec_kw={"width_ratios": [1.2, 1]})

    # Left: paired-arrow plot per (model,case)
    n = len(points)
    y = np.arange(n)[::-1]
    for i, (model, case, e1, e3, _, _) in enumerate(points):
        yy = y[i]
        color = "#2E7D32" if e3 < e1 else ("#C62828" if e3 > e1 else "#757575")
        ax1.plot([e1, e3], [yy, yy], color=color, linewidth=1.6, alpha=0.85)
        ax1.scatter([e1], [yy], color="#1976D2", s=55, zorder=3, edgecolor="black", linewidth=0.5)
        ax1.scatter([e3], [yy], color="#F57C00", s=55, zorder=3, edgecolor="black", linewidth=0.5,
                    marker="s" if e3 > e1 else ("D" if e3 < e1 else "o"))
    ax1.set_yticks(y)
    ax1.set_yticklabels([f"{m[:14]} · {c[:18]}" for m, c, *_ in points], fontsize=8)
    ax1.set_xlabel("Число ошибок валидации NiFi")
    ax1.set_title("Парное сравнение Mode 1 → Mode 3 на сопоставимых запусках")
    ax1.grid(axis="x", alpha=0.3)
    from matplotlib.lines import Line2D
    legend = [
        Line2D([], [], marker="o", color="white", markerfacecolor="#1976D2", markeredgecolor="black", markersize=8, label="Mode 1 (адаптер)"),
        Line2D([], [], marker="o", color="white", markerfacecolor="#F57C00", markeredgecolor="black", markersize=8, label="Mode 3 без изм."),
        Line2D([], [], marker="D", color="white", markerfacecolor="#F57C00", markeredgecolor="black", markersize=8, label="Mode 3 лучше"),
        Line2D([], [], marker="s", color="white", markerfacecolor="#F57C00", markeredgecolor="black", markersize=8, label="Mode 3 хуже"),
    ]
    ax1.legend(handles=legend, loc="lower right", fontsize=8)

    # Right: summary counts + token overhead
    better = sum(1 for _, _, e1, e3, *_ in points if e3 < e1)
    worse = sum(1 for _, _, e1, e3, *_ in points if e3 > e1)
    same = sum(1 for _, _, e1, e3, *_ in points if e3 == e1)
    extra_tok = sum(t3 - t1 for _, _, _, _, t1, t3 in points)
    avg_extra = extra_tok / max(1, n)
    cats = ["Улучшила", "Не изменила", "Ухудшила"]
    vals = [better, same, worse]
    colors = ["#2E7D32", "#757575", "#C62828"]
    bars = ax2.bar(cats, vals, color=colors, edgecolor="black", linewidth=0.5)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.15, str(v),
                 ha="center", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Число пар (case × model)")
    ax2.set_title(f"Эффект LLM-коррекции на {n} парах\nСредний перерасход: +{int(avg_extra):,} токенов / запуск".replace(",", " "))
    ax2.set_ylim(0, max(vals) * 1.25)

    plt.tight_layout()
    plt.savefig(FIG / "fig_m1_vs_m3.png")
    plt.close(fig)


def main():
    fig_heatmap_useful()
    fig_modes_aggregate()
    fig_dispersion()
    fig_cost_quality()
    fig_manual_vs_proto()
    fig_m1_vs_m3()
    print("All figures saved to", FIG)


if __name__ == "__main__":
    main()
