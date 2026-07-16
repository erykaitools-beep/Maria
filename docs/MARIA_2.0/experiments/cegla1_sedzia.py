#!/usr/bin/env python
"""Cegla 1 (S-SEDZIA) -- eksperyment wg BLUEPRINT 7-BIS.
Pytanie: czy uczony organ bije wlasna pewnosc Marii (B0) I tani model (B1)
na TRUDNYM podzbiorze (confidence_before < 1.0)? RESEARCH_ONLY, read-only.
"""
import json, time
from datetime import datetime, timezone
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

REF = ["/mnt/storage/data/logs/reflections.jsonl", "/home/maria/maria/meta_data/reflections.jsonl"]
DT  = ["/mnt/storage/data/logs/decision_traces.jsonl", "/home/maria/maria/meta_data/decision_traces.jsonl"]
SPLIT_EPOCH = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()  # train < 06-01, test >=

def load(paths, keys):
    rows = []
    for p in paths:
        try:
            with open(p) as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        rows.append({k: d.get(k) for k in keys})
                    except Exception:
                        pass
        except FileNotFoundError:
            pass
    return pd.DataFrame(rows)

def ece(y, p, bins=10):
    """Expected Calibration Error."""
    edges = np.linspace(0, 1, bins + 1)
    e, n = 0.0, len(y)
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= edges[i + 1])
        if m.sum() == 0: continue
        e += (m.sum() / n) * abs(y[m].mean() - p[m].mean())
    return e

def metrics(y, p):
    return dict(
        base=float(y.mean()), n=int(len(y)),
        roc_auc=float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        pr_auc=float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        brier=float(brier_score_loss(y, p)),
        ece=float(ece(np.asarray(y), np.asarray(p))),
    )

t0 = time.time()
print("== wczytywanie ==")
ref = load(REF, ["plan_id","action_type","confidence_before","expected_success",
                 "outcome_match","timestamp_started"])
dt  = load(DT,  ["plan_id","health_score","goal_priority","mode","k7_decision"])
print(f"  reflections={len(ref)}  decision_traces={len(dt)}  ({time.time()-t0:.0f}s)")

# --- DEDUP OBU STRON po plan_id (KRYTYCZNA KOREKTA 2026-07-08 po przegladzie adwersaryjnym) ---
# BUG oryginalu: dedupowano tylko dt, NIE ref. reflections.jsonl ma ~13.9x duplikacje na plan_id
# (452k wierszy / 32.6k unikalnych), ZALEZNA OD KLASY (match 13.8x vs mismatch 8.9x). Bez dedupu ref
# base-rate byl zanizony, kalibracja liczona na zduplikowanych punktach -> liczby 7-BIS.1 skazone.
# outcome_match SPOJNY w ramach plan_id (0 niespojnych) -> keep=last bezpieczny.
ref = ref[ref["plan_id"].notna() & (ref["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
dt = dt[dt["plan_id"].notna() & (dt["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
n_before = len(ref)
df = ref.merge(dt, on="plan_id", how="left", suffixes=("", "_dt"))
joined = df["health_score"].notna()
print(f"  JOIN pokrycie: {joined.mean()*100:.1f}%  (niedolaczalne {(~joined).sum()} -> odrzucone)")
df = df[joined].copy()

# --- target binarny: mismatch=1, match=0; DROP unknown/partial ---
df = df[df["outcome_match"].isin(["match","mismatch"])].copy()
df["y"] = (df["outcome_match"] == "mismatch").astype(int)

# --- czyszczenie cech pre-decyzji ---
df = df[df["confidence_before"].notna() & df["timestamp_started"].notna()].copy()
df["expected_success"] = df["expected_success"].fillna(False).astype(int)
for c in ["action_type","mode","k7_decision"]:
    df[c] = df[c].fillna("").astype(str)
df["goal_priority"] = pd.to_numeric(df["goal_priority"], errors="coerce").fillna(0.0)
df["health_score"]  = pd.to_numeric(df["health_score"], errors="coerce").fillna(df["health_score"].median())

print(f"\n== target (caly korpus po JOIN, N={len(df)}) ==")
print(f"  mismatch base-rate: {df['y'].mean()*100:.2f}%")

# --- TRUDNY PODZBIOR: confidence_before < 1.0 (klucz 7-BIS) ---
easy = df[df["confidence_before"] >= 1.0]
hard = df[df["confidence_before"] < 1.0].copy()
print(f"\n== split latwy/trudny (7-BIS) ==")
print(f"  confidence==1.0 : N={len(easy):>7}  mismatch={easy['y'].mean()*100:5.2f}%  (trywialnie bezpieczne)")
print(f"  confidence <1.0 : N={len(hard):>7}  mismatch={hard['y'].mean()*100:5.2f}%  (TU zyje pytanie)")

# --- split czasowy ---
def tsplit(d): return d[d["timestamp_started"] < SPLIT_EPOCH], d[d["timestamp_started"] >= SPLIT_EPOCH]
tr, te = tsplit(hard)
print(f"\n== split czasowy (train<2026-06-01 / test>=) na TRUDNYM ==")
print(f"  train N={len(tr)} (mismatch {tr['y'].mean()*100:.2f}%)  |  test N={len(te)} (mismatch {te['y'].mean()*100:.2f}%)")
if len(te) < 500 or te["y"].sum() < 50:
    print("  [!] maly test -- fallback: split losowy 80/20 warstwowy")
    from sklearn.model_selection import train_test_split
    tr, te = train_test_split(hard, test_size=0.2, random_state=0, stratify=hard["y"])

NUM = ["confidence_before","expected_success","health_score","goal_priority"]
CAT = ["action_type","mode","k7_decision"]
def prep():
    return ColumnTransformer([
        ("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
    ])
Xtr, ytr = tr[NUM+CAT], tr["y"].values
Xte, yte = te[NUM+CAT], te["y"].values

results = {}
# B0: surowa pewnosc Marii (1 - confidence_before) jako score porazki -- BEZ treningu
results["B0 surowa pewnosc"] = metrics(yte, (1.0 - te["confidence_before"]).values)
# B1: regresja logistyczna na tanich cechach
b1 = Pipeline([("prep", prep()), ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))]).fit(Xtr, ytr)
results["B1 logistyka"] = metrics(yte, b1.predict_proba(Xte)[:,1])
# B2: MLP (organ neuronowy) na tych samych cechach
b2 = Pipeline([("prep", prep()), ("clf", MLPClassifier(hidden_layer_sizes=(32,16), max_iter=400,
              early_stopping=True, random_state=0))]).fit(Xtr, ytr)
results["B2 MLP (organ)"] = metrics(yte, b2.predict_proba(Xte)[:,1])

# --- kontrast: B0 na CALYM tescie (nie tylko trudnym) -> pokaz napompowane AUC ---
_, te_full = tsplit(df) if len(tsplit(df)[1]) >= 500 else (None, df.sample(frac=0.2, random_state=0))
b0_full = metrics(te_full["y"].values, (1.0 - te_full["confidence_before"]).values)

print("\n" + "="*74)
print("WYNIKI na TRUDNYM podzbiorze (test), metryki 7-BIS:")
print("="*74)
print(f"{'model':22} {'PR-AUC':>8} {'ROC-AUC':>8} {'Brier':>8} {'ECE':>7}")
for name, m in results.items():
    print(f"{name:22} {m['pr_auc']:8.4f} {m['roc_auc']:8.4f} {m['brier']:8.4f} {m['ece']:7.4f}")
print(f"\n  (dla kontrastu) B0 na CALYM tescie: ROC-AUC={b0_full['roc_auc']:.4f}  <- napompowane trywialnym splitem")
print(f"  base-rate mismatch na trudnym tescie: {results['B0 surowa pewnosc']['base']*100:.2f}%")

# --- WERDYKT 7-BIS: B2 musi pobic B0 ORAZ B1 (PR-AUC + Brier) ---
b0, b1m, b2m = results["B0 surowa pewnosc"], results["B1 logistyka"], results["B2 MLP (organ)"]
print("\n" + "="*74); print("WERDYKT (7-BIS: organ B2 > B0 pewnosc I > B1 logistyka?)"); print("="*74)
def cmp(a, b, name):
    dpr = b["pr_auc"] - a["pr_auc"]; dbr = a["brier"] - b["brier"]  # brier: mniej=lepiej
    print(f"  B2 vs {name:16}: dPR-AUC={dpr:+.4f}  dBrier={dbr:+.4f}  -> {'LEPSZY' if dpr>0 and dbr>0 else 'NIE lepszy jednoznacznie'}")
    return dpr > 0 and dbr > 0
beat0 = cmp(b0, b2m, "B0 (pewnosc)")
beat1 = cmp(b1m, b2m, "B1 (logistyka)")
print(f"\n  >>> {'ORGAN ZARABIA NA UTRZYMANIE (pobija oba)' if (beat0 and beat1) else 'ORGAN NIE pobija jednoznacznie -> tani falsyfikat: sam symbol/logistyka wystarcza'}")
print(f"\n(czas: {time.time()-t0:.0f}s)")
