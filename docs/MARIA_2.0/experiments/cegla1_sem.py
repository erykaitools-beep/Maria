#!/usr/bin/env python
"""Cegla 1 (S-SEDZIA) -- PRZEJAZD 2 (semantyczny) wg BLUEPRINT 7-BIS.

Pytanie przejazdu 2: czy TRESC celu (embedding goal_description) przewiduje
porazke Marii PONAD tanie skalary? Przejazd 1 pokazal, ze MLP na tanich cechach
== logistyka (organ nic nie zarabia). Tu wbijamy wlasciwy pal: dodajemy embedding
treci i sprawdzamy, czy neuron na TRESCI bije B0 (pewnosc) I B1 (logistyka).

RESEARCH_ONLY, read-only. Zero dotykania zywej 1.0.

Panel modeli (trudny podzbior confidence<1.0, split czasowy 2026-06-01):
  B0          -- surowa pewnosc Marii (1-confidence_before), BEZ treningu
  B1          -- logistyka na tanich cechach (skalibrowana, bez class_weight)
  B1+gd-onehot-- KONTROLA: goal_description jako zwykla kategoria (czy sama
                 tozsamosc celu, nie semantyka, wystarcza?)
  B2-emb-only -- czysty wklad treci (embedding sam)
  B2-sem      -- organ: MLP na embedding + tanie cechy

Fix kalibracji (7-BIS.1 residual): CalibratedClassifierCV(isotonic), BEZ
class_weight='balanced' -- w przejeździe 1 balanced podbil ROC ale zepsul Brier/ECE.
"""
import json, time, hashlib, os
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
SPLIT_EPOCH = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()  # train < 06-01, test >=
EMB_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emb_cache.npz")
EMB_MODEL = "nomic-embed-text"
RNG = 0

# ---------------------------------------------------------------- ladowanie
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

# ---------------------------------------------------------------- embedding + cache
def _embed_one(text):
    payload = {"model": EMB_MODEL, "input": text}
    req = urllib.request.Request("http://localhost:11434/api/embed",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return np.asarray(r["embeddings"][0], dtype=np.float32)

def embed_unique(texts):
    """Embeduj UNIKALNE teksty z cache na dysku (keyed po sha1 tekstu). Zwraca dict text->vec."""
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
            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{len(missing)}")
        # zapisz cache
        allt = list(cache.keys())
        allv = np.vstack([cache[t] for t in allt]).astype(np.float32)
        np.savez_compressed(EMB_CACHE, texts=np.array(allt, dtype=object), vecs=allv)
    else:
        print(f"  cache HIT dla wszystkich {len(uniq)} unikalnych tekstow")
    return {t: cache[t] for t in uniq}

# ---------------------------------------------------------------- metryki
def ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    e, n = 0.0, len(y)
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= edges[i + 1])
        if m.sum() == 0: continue
        e += (m.sum() / n) * abs(y[m].mean() - p[m].mean())
    return e

def metrics(y, p):
    y = np.asarray(y); p = np.asarray(p)
    return dict(
        base=float(y.mean()), n=int(len(y)),
        roc_auc=float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        pr_auc=float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        brier=float(brier_score_loss(y, p)),
        ece=float(ece(y, p)),
    )

t0 = time.time()
print("== wczytywanie ==")
ref = load(REF, ["plan_id","action_type","confidence_before","expected_success",
                 "outcome_match","timestamp_started"])
dt  = load(DT,  ["plan_id","health_score","goal_priority","mode","k7_decision","goal_description"])
print(f"  reflections={len(ref)}  decision_traces={len(dt)}  ({time.time()-t0:.0f}s)")

# --- DEDUP OBU STRON po plan_id (KRYTYCZNE, fix po przegladzie adwersaryjnym) ---
# reflections.jsonl ma ~13.9x duplikacje na plan_id (452k wierszy / 32.6k unikalnych),
# ZALEZNA OD KLASY (match 13.8x vs mismatch 8.9x) -> bez dedupu ref: base-rate zanizony,
# izotonic kalibrowany na zduplikowanych punktach, bootstrap CI zanizone (efektywne N << rows).
# outcome_match jest SPOJNY w ramach plan_id (0 niespojnych) -> keep=last bezpieczny.
n_ref_raw = len(ref)
ref = ref[ref["plan_id"].notna() & (ref["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
dt = dt[dt["plan_id"].notna() & (dt["plan_id"] != "")].drop_duplicates("plan_id", keep="last")
print(f"  DEDUP reflections: {n_ref_raw} wierszy -> {len(ref)} unikalnych plan_id (fix ~14x inflacji)")
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
df["goal_description"] = df["goal_description"].fillna("").astype(str).str.strip()
df["goal_priority"] = pd.to_numeric(df["goal_priority"], errors="coerce").fillna(0.0)
df["health_score"]  = pd.to_numeric(df["health_score"], errors="coerce").fillna(df["health_score"].median())

# --- ANTYPRZECIEK: wejscie to WYLACZNIE pola pre-decyzji ---
# actual_success / confidence_after / outcome_match(label) / lessons NIE sa ladowane -> brak leaku z konstrukcji.
PRE_DECISION_INPUTS = ["confidence_before","expected_success","health_score","goal_priority",
                       "action_type","mode","k7_decision","goal_description"]

# --- TRUDNY PODZBIOR: confidence_before < 1.0 (klucz 7-BIS) ---
hard = df[df["confidence_before"] < 1.0].copy()
print(f"\n== trudny podzbior (7-BIS) ==")
print(f"  confidence<1.0 : N={len(hard)}  mismatch={hard['y'].mean()*100:.2f}%")
print(f"  goal_description niepuste: {100*(hard['goal_description']!='').mean():.1f}%  "
      f"unikalnych: {hard['goal_description'].nunique()}")

# --- split czasowy ---
tr = hard[hard["timestamp_started"] < SPLIT_EPOCH].copy()
te = hard[hard["timestamp_started"] >= SPLIT_EPOCH].copy()
print(f"\n== split czasowy (train<2026-06-01 / test>=) na TRUDNYM ==")
print(f"  train N={len(tr)} (mismatch {tr['y'].mean()*100:.2f}%)  |  test N={len(te)} (mismatch {te['y'].mean()*100:.2f}%)")

# --- diagnostyka niskiej kardynalnosci: ile celow testu NIE bylo w treningu? ---
gd_tr = set(tr["goal_description"].unique())
unseen_mask = ~te["goal_description"].isin(gd_tr)
print(f"  unikalnych goal_description: train={len(gd_tr)}  test={te['goal_description'].nunique()}  "
      f"test-tylko-nowe={unseen_mask.sum()} ({100*unseen_mask.mean():.1f}% wierszy testu)")
print("  [uwaga: niska kardynalnosc => embedding ~= kodowanie kategorii; kontrola B1+gd-onehot to izoluje]")

# ---------------------------------------------------------------- embedding
print(f"\n== embedding goal_description (nomic-embed-text, cache={os.path.basename(EMB_CACHE)}) ==")
emb_map = embed_unique(hard["goal_description"].tolist())
DIM = len(next(iter(emb_map.values())))
def to_emb_matrix(series):
    return np.vstack([emb_map[t] for t in series]).astype(np.float32)
EMB_tr = to_emb_matrix(tr["goal_description"])
EMB_te = to_emb_matrix(te["goal_description"])
print(f"  wymiar embeddingu={DIM}  Xtr_emb={EMB_tr.shape}  Xte_emb={EMB_te.shape}  ({time.time()-t0:.0f}s)")

# ---------------------------------------------------------------- budowa macierzy cech
NUM = ["confidence_before","expected_success","health_score","goal_priority"]
CAT = ["action_type","mode","k7_decision"]
EMB_COLS = [f"emb_{i}" for i in range(DIM)]

def with_emb(base_df, emb_mat):
    """Zwroc DataFrame: tanie cechy + kolumny embeddingu (dla ColumnTransformer passthrough)."""
    out = base_df[NUM + CAT + ["goal_description"]].reset_index(drop=True).copy()
    emb_df = pd.DataFrame(emb_mat, columns=EMB_COLS)
    return pd.concat([out, emb_df], axis=1)

Xtr = with_emb(tr, EMB_tr); Xte = with_emb(te, EMB_te)
ytr = tr["y"].values; yte = te["y"].values

def prep_cheap():
    return ColumnTransformer([
        ("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
    ], remainder="drop")

def prep_cheap_gd():
    return ColumnTransformer([
        ("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
        ("gd",  OneHotEncoder(handle_unknown="ignore", min_frequency=10), ["goal_description"]),
    ], remainder="drop")

def prep_emb_only():
    return ColumnTransformer([("emb", StandardScaler(), EMB_COLS)], remainder="drop")

def prep_cheap_emb():
    return ColumnTransformer([
        ("num", StandardScaler(), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
        ("emb", StandardScaler(), EMB_COLS),
    ], remainder="drop")

def calibrated(prep, clf):
    """Fair Brier/ECE: isotonic calibration z wewn. CV na TRENINGU (bez wycieku testu)."""
    return CalibratedClassifierCV(Pipeline([("prep", prep), ("clf", clf)]),
                                  method="isotonic", cv=3)

def logistic():
    return LogisticRegression(max_iter=3000)  # BEZ class_weight (fix 7-BIS.1)

def mlp():
    return MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500,
                         early_stopping=True, random_state=RNG)

results = {}
preds = {}  # name -> wektor P(mismatch) na tescie (do bootstrap CI)
# B0: surowa pewnosc Marii, BEZ treningu -- score porazki = 1-confidence_before
preds["B0 surowa pewnosc"] = 1.0 - te["confidence_before"].values
results["B0 surowa pewnosc"] = metrics(yte, preds["B0 surowa pewnosc"])

print("\n== trening modeli (kalibrowane, bez class_weight) ==")
def fit_eval(name, prep, clf):
    t = time.time()
    m = calibrated(prep, clf).fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    preds[name] = p
    results[name] = metrics(yte, p)
    print(f"  {name:22} gotowe ({time.time()-t:.0f}s)")

fit_eval("B1 logistyka",      prep_cheap(),    logistic())
fit_eval("B1+gd-onehot",      prep_cheap_gd(), logistic())
fit_eval("B2-emb-only (MLP)", prep_emb_only(), mlp())
fit_eval("B2-sem (organ MLP)",prep_cheap_emb(),mlp())
# --- ablacja 2x2 (klasa modelu x zestaw cech) -- izoluje CECHE od KLASY ---
fit_eval("A: MLP cheap-only",   prep_cheap(),     mlp())        # MLP bez embeddingu
fit_eval("A: LOGIT cheap+emb",  prep_cheap_emb(), logistic())   # embedding w logistyce (nie MLP)

# ---------------------------------------------------------------- wyniki
order = ["B0 surowa pewnosc","B1 logistyka","B1+gd-onehot","B2-emb-only (MLP)","B2-sem (organ MLP)",
         "A: MLP cheap-only","A: LOGIT cheap+emb"]
print("\n" + "="*80)
print("WYNIKI na TRUDNYM podzbiorze (test), metryki 7-BIS (PR-AUC/Brier = bramka, ROC=raport):")
print("="*80)
print(f"{'model':24} {'PR-AUC':>8} {'Brier':>8} {'ECE':>7} {'ROC-AUC':>8}")
for name in order:
    m = results[name]
    print(f"{name:24} {m['pr_auc']:8.4f} {m['brier']:8.4f} {m['ece']:7.4f} {m['roc_auc']:8.4f}")
print(f"\n  base-rate mismatch (trudny test): {results['B0 surowa pewnosc']['base']*100:.2f}%   N_test={results['B0 surowa pewnosc']['n']}")

# ---------------------------------------------------------------- werdykt 7-BIS
b0 = results["B0 surowa pewnosc"]; b1 = results["B1 logistyka"]; b2 = results["B2-sem (organ MLP)"]
b1gd = results["B1+gd-onehot"]
def cmp(a, b, name):
    dpr = b["pr_auc"] - a["pr_auc"]; dbr = a["brier"] - b["brier"]  # brier: mniej=lepiej -> dodatnie=poprawa
    ok = dpr > 0 and dbr > 0
    print(f"  {name:28}: dPR-AUC={dpr:+.4f}  dBrier={dbr:+.4f}  -> {'LEPSZY' if ok else 'NIE lepszy jednoznacznie'}")
    return ok
print("\n" + "="*80)
print("WERDYKT 7-BIS: organ (B2-sem) musi pobic B0 pewnosc I B1 logistyke (PR-AUC + Brier)")
print("="*80)
beat0 = cmp(b0, b2, "B2-sem vs B0 (pewnosc)")
beat1 = cmp(b1, b2, "B2-sem vs B1 (logistyka)")
print(f"\n  >>> {'ORGAN ZARABIA NA UTRZYMANIE (pobija oba)' if (beat0 and beat1) else 'ORGAN NIE pobija jednoznacznie -> falsyfikat: tresc nie dodaje sygnalu ponad skalary'}")
print("\n  --- kontrola semantyki (czy embedding > sama tozsamosc kategorii?) ---")
cmp(b1gd, b2, "B2-sem vs B1+gd-onehot")
print("  (jesli B2-sem ~= B1+gd-onehot => embedding nie wnosi semantyki ponad kodowanie 132 kategorii)")

# ---------------------------------------------------------------- bootstrap CI (istotnosc)
print("\n" + "="*80)
print("BOOTSTRAP 95% CI (paired, B=2000) -- czy delty organu sa istotne czy w granicach szumu?")
print("="*80)
B = 2000
rng = np.random.default_rng(RNG)
yte_arr = np.asarray(yte)
n = len(yte_arr)
idxs = rng.integers(0, n, size=(B, n))  # wspolne indeksy dla parowania

def boot_metric(p, fn):
    out = np.empty(B)
    for b in range(B):
        i = idxs[b]
        yi = yte_arr[i]
        if yi.min() == yi.max():   # zdegenerowany resample
            out[b] = np.nan; continue
        out[b] = fn(yi, p[i])
    return out

def ci(v):
    v = v[~np.isnan(v)]
    return np.percentile(v, 2.5), np.percentile(v, 97.5)

# CI per model dla PR-AUC i Brier
boot_pr = {name: boot_metric(preds[name], average_precision_score) for name in order}
boot_br = {name: boot_metric(preds[name], brier_score_loss) for name in order}
print(f"{'model':24} {'PR-AUC [95% CI]':>26} {'Brier [95% CI]':>26}")
for name in order:
    lp, hp = ci(boot_pr[name]); lb, hb = ci(boot_br[name])
    print(f"{name:24} {results[name]['pr_auc']:.3f} [{lp:.3f},{hp:.3f}]   {results[name]['brier']:.3f} [{lb:.3f},{hb:.3f}]")

# CI DELT (paired): B2-sem minus baseline -- czy przedzial przekracza 0?
print("\n  Delty organu B2-sem (paired bootstrap; dodatnie dPR/dBrier = organ LEPSZY):")
def delta_ci(a_name, b_name):
    dpr = boot_pr[b_name] - boot_pr[a_name]           # b - a (PR: wiecej=lepiej)
    dbr = boot_br[a_name] - boot_br[b_name]           # a - b (Brier: mniej=lepiej -> dodatnie=b lepszy)
    m = ~(np.isnan(dpr) | np.isnan(dbr))
    lp, hp = np.percentile(dpr[m], [2.5, 97.5]); lb, hb = np.percentile(dbr[m], [2.5, 97.5])
    sig_pr = "istotne" if (lp > 0 or hp < 0) else "SZUM (CI zawiera 0)"
    sig_br = "istotne" if (lb > 0 or hb < 0) else "SZUM (CI zawiera 0)"
    print(f"    vs {a_name:20} dPR-AUC={dpr[m].mean():+.4f} [{lp:+.4f},{hp:+.4f}] {sig_pr:20}  "
          f"dBrier={dbr[m].mean():+.4f} [{lb:+.4f},{hb:+.4f}] {sig_br}")
delta_ci("B0 surowa pewnosc", "B2-sem (organ MLP)")
delta_ci("B1 logistyka",      "B2-sem (organ MLP)")
delta_ci("B1+gd-onehot",      "B2-sem (organ MLP)")
print("  (organ zarabia TYLKO jesli dPR-AUC i dBrier sa istotnie DODATNIE vs B0 i B1)")

print(f"\n(czas calkowity: {time.time()-t0:.0f}s)")
