#!/usr/bin/env python
"""Cegla 1 (S-SEDZIA) -- PRZEJAZD 3 (bogate wejscie pre-decyzyjne) wg BLUEPRINT 7-BIS.

Przejazd 2 pokazal: embedding SZABLONOWEGO goal_description (132 unikaty) nie bije skalarow.
Otwarte pytanie Eryka: a co na BOGATSZYM wejsciu? Tu laczymy WSZYSTKIE dostepne pola
PRE-DECYZYJNE w jeden bogaty tekst i embedujemy:
    rich = goal_description || action_params || k7_reasons
(315 unikatow na trudnym vs 132 dla samego goal_description; dochodzi topic, resolved_file_ids, powod K7).

DYSCYPLINA PRZECIEKU (kluczowa dla bogatego tekstu): pola PO decyzji (result_summary, steps,
actual_success, confidence_after) NIE wchodza na wejscie -- sa TYLKO etykieta albo kontrola przecieku.

KONTROLA PRZECIEKU (protokol 7.2: "model na polach wynikowych musi miec AUC~1"): LEAK-num =
logistyka na [expected_success, actual_success, confidence_after]. actual_success+expected_success
DEFINIUJA outcome_match, wiec AUC~1 -> DOWOD ze etykieta jest wyuczalna. Jesli bogaty tekst NIE bije
skalarow a LEAK-num ~= 1.0 -> zero na pre-decyzji to PRAWDZIWY null (nie zepsuty pipeline).

RESEARCH_ONLY, read-only. Reasoning journal (/myslenie) sprawdzony: pokrywa 1.4% trudnego (same
self_analyze) -> to meta-rozumowanie K12/K13, NIE per-decyzja; niedostepne dla tego zadania.
"""
import json, time, os
from datetime import datetime, timezone
import urllib.request
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

REF = ["/mnt/storage/data/logs/reflections.jsonl", "/home/maria/maria/meta_data/reflections.jsonl"]
DT  = ["/mnt/storage/data/logs/decision_traces.jsonl", "/home/maria/maria/meta_data/decision_traces.jsonl"]
SPLIT_EPOCH = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
EMB_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emb_cache.npz")
EMB_MODEL = "nomic-embed-text"
RNG = 0

def load(paths, keys):
    rows = []
    for p in paths:
        try:
            f = open(p)
        except FileNotFoundError:
            continue
        with f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                rows.append({k: d.get(k) for k in keys})
    return pd.DataFrame(rows)

def as_text(v):
    if v is None: return ""
    if isinstance(v, (dict, list)): return json.dumps(v, ensure_ascii=False)
    return str(v)

def _embed_one(text):
    payload = {"model": EMB_MODEL, "input": text if text else " "}
    req = urllib.request.Request("http://localhost:11434/api/embed",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return np.asarray(r["embeddings"][0], dtype=np.float32)

def embed_unique(texts):
    cache = {}
    if os.path.exists(EMB_CACHE):
        z = np.load(EMB_CACHE, allow_pickle=True)
        for t, v in zip(z["texts"], z["vecs"]):
            cache[str(t)] = v.astype(np.float32)
    uniq = sorted(set(texts))
    missing = [t for t in uniq if t not in cache]
    if missing:
        print(f"  embeduje {len(missing)} nowych (cache ma {len(cache)}) ...")
        for i, t in enumerate(missing):
            cache[t] = _embed_one(t)
            if (i + 1) % 50 == 0: print(f"    {i+1}/{len(missing)}")
        allt = list(cache.keys())
        allv = np.vstack([cache[t] for t in allt]).astype(np.float32)
        np.savez_compressed(EMB_CACHE, texts=np.array(allt, dtype=object), vecs=allv)
    else:
        print(f"  cache HIT dla wszystkich {len(uniq)} unikalnych tekstow")
    return {t: cache[t] for t in uniq}

def ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1); e, n = 0.0, len(y)
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= edges[i + 1])
        if m.sum() == 0: continue
        e += (m.sum() / n) * abs(y[m].mean() - p[m].mean())
    return e

def metrics(y, p):
    y = np.asarray(y); p = np.asarray(p)
    return dict(base=float(y.mean()), n=int(len(y)),
        roc_auc=float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        pr_auc=float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        brier=float(brier_score_loss(y, p)), ece=float(ece(y, p)))

t0 = time.time()
print("== wczytywanie ==")
ref = load(REF, ["plan_id","action_type","confidence_before","expected_success","outcome_match",
                 "timestamp_started","actual_success","confidence_after"])
dt  = load(DT,  ["plan_id","health_score","goal_priority","mode","k7_decision","goal_description",
                 "action_params","k7_reasons"])
print(f"  reflections={len(ref)}  decision_traces={len(dt)}  ({time.time()-t0:.0f}s)")

# --- DEDUP OBU STRON (fix z przejazdu 2) ---
ref = ref[ref["plan_id"].notna() & (ref["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
dt  = dt[dt["plan_id"].notna() & (dt["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
df = ref.merge(dt, on="plan_id", how="left", suffixes=("", "_dt"))
df = df[df["health_score"].notna()].copy()
df = df[df["outcome_match"].isin(["match","mismatch"])].copy()
df["y"] = (df["outcome_match"] == "mismatch").astype(int)
df = df[df["confidence_before"].notna() & df["timestamp_started"].notna()].copy()
df["expected_success"] = df["expected_success"].fillna(False).astype(int)
for c in ["action_type","mode","k7_decision"]:
    df[c] = df[c].fillna("").astype(str)
df["goal_priority"] = pd.to_numeric(df["goal_priority"], errors="coerce").fillna(0.0)
df["health_score"]  = pd.to_numeric(df["health_score"], errors="coerce").fillna(df["health_score"].median())
# pola PO-decyzji (TYLKO do kontroli przecieku, NIE na wejscie modeli pre-dec)
df["actual_success"]   = df["actual_success"].map(lambda v: 1 if v is True else (0 if v is False else np.nan))
df["confidence_after"] = pd.to_numeric(df["confidence_after"], errors="coerce")

# --- BOGATY tekst PRE-DECYZYJNY ---
df["rich"] = (df["goal_description"].map(as_text) + " || "
              + df["action_params"].map(as_text) + " || "
              + df["k7_reasons"].map(as_text)).str.strip()

hard = df[df["confidence_before"] < 1.0].copy()
print(f"\n== trudny podzbior (7-BIS) N={len(hard)}  mismatch={hard['y'].mean()*100:.2f}% ==")
print(f"  bogaty tekst unikalnych: {hard['rich'].nunique()}  (vs sam goal_description: {hard['goal_description'].map(as_text).nunique()})")
print(f"  mediana dlugosci bogatego: {int(hard['rich'].str.len().median())} znakow")

tr = hard[hard["timestamp_started"] < SPLIT_EPOCH].copy()
te = hard[hard["timestamp_started"] >= SPLIT_EPOCH].copy()
print(f"  split czasowy: train N={len(tr)} (mm {tr['y'].mean()*100:.1f}%)  test N={len(te)} (mm {te['y'].mean()*100:.1f}%)")
unseen = ~te["rich"].isin(set(tr["rich"].unique()))
print(f"  bogatych tekstow test-tylko-nowe: {unseen.sum()} ({100*unseen.mean():.1f}% wierszy testu)")

# --- embedding bogatego tekstu ---
print(f"\n== embedding bogatego tekstu (nomic-embed-text, cache) ==")
emb_map = embed_unique(hard["rich"].tolist())
DIM = len(next(iter(emb_map.values())))
def to_emb(series): return np.vstack([emb_map[t] for t in series]).astype(np.float32)
EMB_tr, EMB_te = to_emb(tr["rich"]), to_emb(te["rich"])
print(f"  dim={DIM}  Xtr_emb={EMB_tr.shape}  ({time.time()-t0:.0f}s)")

NUM = ["confidence_before","expected_success","health_score","goal_priority"]
CAT = ["action_type","mode","k7_decision"]
EMB_COLS = [f"emb_{i}" for i in range(DIM)]

def build(base_df, emb_mat):
    out = base_df[NUM + CAT].reset_index(drop=True).copy()
    return pd.concat([out, pd.DataFrame(emb_mat, columns=EMB_COLS)], axis=1)
Xtr, Xte = build(tr, EMB_tr), build(te, EMB_te)
ytr, yte = tr["y"].values, te["y"].values

def prep_cheap():
    return ColumnTransformer([("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT)], remainder="drop")
def prep_cheap_emb():
    return ColumnTransformer([("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
        ("emb", StandardScaler(), EMB_COLS)], remainder="drop")
def prep_emb_only():
    return ColumnTransformer([("emb", StandardScaler(), EMB_COLS)], remainder="drop")
def calibrated(prep, clf):
    return CalibratedClassifierCV(Pipeline([("prep", prep), ("clf", clf)]), method="isotonic", cv=3)
def logistic(): return LogisticRegression(max_iter=3000)
def mlp(): return MLPClassifier(hidden_layer_sizes=(64,32), max_iter=500, early_stopping=True, random_state=RNG)

results, preds = {}, {}
preds["B0 surowa pewnosc"] = 1.0 - te["confidence_before"].values
results["B0 surowa pewnosc"] = metrics(yte, preds["B0 surowa pewnosc"])

print("\n== trening (kalibrowane, bez class_weight) ==")
def fit_eval(name, prep, clf, Xtr_=None, Xte_=None):
    t = time.time()
    A, B = (Xtr if Xtr_ is None else Xtr_), (Xte if Xte_ is None else Xte_)
    m = calibrated(prep, clf).fit(A, ytr)
    preds[name] = m.predict_proba(B)[:, 1]
    results[name] = metrics(yte, preds[name])
    print(f"  {name:26} gotowe ({time.time()-t:.0f}s)")

fit_eval("B1 logistyka (cheap)", prep_cheap(),     logistic())
fit_eval("B3-rich (MLP cheap+emb)", prep_cheap_emb(), mlp())
fit_eval("B3-rich-LOGIT (cheap+emb)", prep_cheap_emb(), logistic())
fit_eval("B3-rich-only (MLP emb)", prep_emb_only(), mlp())

# --- KONTROLA PRZECIEKU: model na polach PO-decyzji -> ma pobic pre-dec (dowod wyuczalnosci) ---
# outcome_match == (expected_success != actual_success) w ~98% -> to XOR. Liniowa logistyka XORa NIE
# ogarnie (podstep!), wiec uzywamy RandomForest, ktory naturalnie lapie interakcje z SUROWYCH pol
# wynikowych. Jesli LEAK >> modele pre-dec => pipeline lapie sygnal gdy jest => null na pre-dec PRAWDZIWY.
from sklearn.ensemble import RandomForestClassifier
leak = df[df["confidence_before"] < 1.0].copy()
leak_tr = leak[leak["timestamp_started"] < SPLIT_EPOCH]
leak_te = leak[leak["timestamp_started"] >= SPLIT_EPOCH]
LK = ["expected_success","actual_success","confidence_after"]
lk_tr = leak_tr[LK].fillna(-1.0); lk_te = leak_te[LK].fillna(-1.0)
lkm = RandomForestClassifier(n_estimators=100, random_state=RNG).fit(lk_tr, leak_tr["y"].values)
lk_p = lkm.predict_proba(lk_te)[:, 1]
leak_res = metrics(leak_te["y"].values, lk_p)
print(f"  {'LEAK-RF (pola wynikowe)':26} gotowe -- ma pobic pre-dec (etykieta wyuczalna)")

order = ["B0 surowa pewnosc","B1 logistyka (cheap)","B3-rich (MLP cheap+emb)",
         "B3-rich-LOGIT (cheap+emb)","B3-rich-only (MLP emb)"]
print("\n" + "="*82)
print("WYNIKI na TRUDNYM podzbiorze (test), metryki 7-BIS:")
print("="*82)
print(f"{'model':28} {'PR-AUC':>8} {'Brier':>8} {'ECE':>7} {'ROC-AUC':>8}")
for name in order:
    m = results[name]
    print(f"{name:28} {m['pr_auc']:8.4f} {m['brier']:8.4f} {m['ece']:7.4f} {m['roc_auc']:8.4f}")
print(f"{'LEAK-RF [KONTROLA]':28} {leak_res['pr_auc']:8.4f} {leak_res['brier']:8.4f} {leak_res['ece']:7.4f} {leak_res['roc_auc']:8.4f}   <- pola PO-decyzji, ma pobic pre-dec")
print(f"\n  base-rate mismatch (trudny test): {results['B0 surowa pewnosc']['base']*100:.2f}%   N_test={results['B0 surowa pewnosc']['n']}")

# --- WERDYKT + bootstrap CI ---
b0, b1, b3 = results["B0 surowa pewnosc"], results["B1 logistyka (cheap)"], results["B3-rich (MLP cheap+emb)"]
print("\n" + "="*82)
print("WERDYKT 7-BIS: bogaty organ (B3-rich) musi pobic B0 pewnosc I B1 logistyke (PR-AUC + Brier)")
print("="*82)
def cmp(a, b, name):
    dpr = b["pr_auc"]-a["pr_auc"]; dbr = a["brier"]-b["brier"]
    ok = dpr>0 and dbr>0
    print(f"  B3-rich vs {name:16}: dPR-AUC={dpr:+.4f}  dBrier={dbr:+.4f}  -> {'LEPSZY' if ok else 'NIE lepszy'}")
    return ok
beat0 = cmp(b0, b3, "B0 (pewnosc)"); beat1 = cmp(b1, b3, "B1 (logistyka)")
print(f"\n  >>> {'BOGATY ORGAN ZARABIA (pobija oba)' if (beat0 and beat1) else 'BOGATY ORGAN NIE pobija -> nawet bogaty tekst pre-dec nie dodaje sygnalu ponad skalary'}")

print("\n" + "="*82)
print("BOOTSTRAP 95% CI (paired, B=2000)")
print("="*82)
B = 2000; rng = np.random.default_rng(RNG)
ya = np.asarray(yte); n = len(ya); idxs = rng.integers(0, n, size=(B, n))
def boot(p, fn):
    out = np.empty(B)
    for b in range(B):
        i = idxs[b]; yi = ya[i]
        out[b] = np.nan if yi.min()==yi.max() else fn(yi, p[i])
    return out
bpr = {k: boot(preds[k], average_precision_score) for k in order}
bbr = {k: boot(preds[k], brier_score_loss) for k in order}
def dci(a, b):
    dpr = bpr[b]-bpr[a]; dbr = bbr[a]-bbr[b]; m = ~(np.isnan(dpr)|np.isnan(dbr))
    lp,hp = np.percentile(dpr[m],[2.5,97.5]); lb,hb = np.percentile(dbr[m],[2.5,97.5])
    sp = "istotne" if (lp>0 or hp<0) else "SZUM (CI zawiera 0)"
    sb = "istotne" if (lb>0 or hb<0) else "SZUM (CI zawiera 0)"
    print(f"  B3-rich vs {a:20} dPR={dpr[m].mean():+.4f} [{lp:+.4f},{hp:+.4f}] {sp:20}  dBrier={dbr[m].mean():+.4f} [{lb:+.4f},{hb:+.4f}] {sb}")
dci("B0 surowa pewnosc", "B3-rich (MLP cheap+emb)")
dci("B1 logistyka (cheap)", "B3-rich (MLP cheap+emb)")
print(f"\n(czas: {time.time()-t0:.0f}s)")
