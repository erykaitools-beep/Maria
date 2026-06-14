#!/usr/bin/env python3
"""
M.A.R.I.A. Web UI Linter

Static checks for the failure classes that the Web UI v2 extraction (ADR-017)
left in rarely-opened pages. The pattern: a refactor renames something, updates
the main pages (chat/status), and silently breaks a secondary page (profile,
architecture) because nobody opens it -- so it rots undetected. This lint is the
immune response: a future rename that breaks a page fails here instead of in
production.

Checks every maria_ui/static/js/*.js for:

  A. Dead helper -- a file calls moFetch(...) without defining it. The shared
     helper is MariaUI.apiFetch; a bare global `moFetch` is undefined, so the
     call throws ReferenceError and the page never fetches.
     (profile.js, fixed 0d4d23f.)

  B. Stale element id -- getElementById('x') / M.$('x') where 'x' exists in
     neither the page's host template, base.html, nor anything the JS creates
     itself (HTML `id="x"` in a template string, or a `.id = 'x'` assignment).
     A missing element returns null; touching it in init() throws and the page
     goes blank. (architecture.js #graphArea, fixed 8fa89a4.)

  C. Dead endpoint -- a "/api/..." URL with no matching @app.route /
     @socketio.on in maria_ui/app.py.

Scope: catches these three static failure modes only. It does NOT prove a page
renders perfectly (logic bugs, runtime data-shape errors, an init() that is
never called are out of scope). Heuristic flags (esp. B) can be false positives
for ids built in another file -- read the context before "fixing".

Exit codes: 0 = clean, 1 = issues found, 2 = lint could not run.

Usage:
    python scripts/ui_lint.py            # full per-file report
    python scripts/ui_lint.py --quiet    # print only if issues (CI / pre-commit)
"""

import re
import os
import sys
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "maria_ui", "static", "js")
TPL_DIR = os.path.join(ROOT, "maria_ui", "templates")
APP_PY = os.path.join(ROOT, "maria_ui", "app.py")

_ID_ATTR = re.compile(r"""id=["']([\w-]+)["']""")
_ID_ASSIGN = re.compile(r"""\.id\s*=\s*["']([\w-]+)["']""")
_GET_BY_ID = re.compile(r"""getElementById\(["']([\w-]+)["']\)""")
_DOLLAR = re.compile(r"""(?:M|MariaUI)\.\$\(["']([\w-]+)["']\)""")
_MOFETCH_USE = re.compile(r"""\bmoFetch\s*\(""")
_MOFETCH_DEF = re.compile(r"""\bmoFetch\s*=""")
_API_URL = re.compile(r"""["'`](/api/[\w/-]+)""")
_ROUTE = re.compile(r"""@(?:app\.route|socketio\.on)\(\s*["']([^"']+)["']""")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _html_ids(text):
    return set(_ID_ATTR.findall(text))


def _js_created_ids(text):
    """ids the JS makes available: HTML id="x" in template strings + .id='x'."""
    return set(_ID_ATTR.findall(text)) | set(_ID_ASSIGN.findall(text))


def _js_id_refs(text):
    return set(_GET_BY_ID.findall(text)) | set(_DOLLAR.findall(text))


def _host_templates(js_name, template_texts):
    """Templates whose <script src> pulls in this JS file."""
    needle = f"js/{js_name}"
    return [name for name, text in template_texts.items() if needle in text]


def _route_prefixes(app_src):
    prefixes = set()
    for route in _ROUTE.findall(app_src):
        prefixes.add(route.rstrip("/"))
        prefixes.add(route.split("<")[0].rstrip("/"))  # strip <param> tail
    prefixes.discard("")
    return prefixes


def _url_known(url, prefixes):
    u = url.rstrip("/")
    return any(u == p or u.startswith(p + "/") for p in prefixes)


def run_lint():
    """Run all checks. Returns a list of (js_name, klass, detail) tuples."""
    if not os.path.isdir(JS_DIR):
        raise FileNotFoundError(f"JS dir not found: {JS_DIR}")

    template_texts = {
        os.path.basename(p): _read(p) for p in glob.glob(os.path.join(TPL_DIR, "*.html"))
    }
    base_ids = _html_ids(template_texts.get("base.html", ""))
    route_prefixes = _route_prefixes(_read(APP_PY))

    issues = []
    for js_path in sorted(glob.glob(os.path.join(JS_DIR, "*.js"))):
        name = os.path.basename(js_path)
        text = _read(js_path)

        # A. dead moFetch helper (used but never defined in this file)
        if _MOFETCH_USE.search(text) and not _MOFETCH_DEF.search(text):
            issues.append((name, "A:dead-helper",
                           "calls moFetch(...) but never defines it -- use MariaUI.apiFetch"))

        # B. stale element ids
        hosts = _host_templates(name, template_texts)
        available = set(base_ids) | _js_created_ids(text)
        for h in hosts:
            available |= _html_ids(template_texts[h])
        for ref in sorted(_js_id_refs(text) - available):
            host_str = ", ".join(hosts) or "(no host template)"
            issues.append((name, "B:stale-id",
                           f"#{ref} not in {host_str} / base.html / self"))

        # C. dead /api endpoints
        for url in sorted(set(_API_URL.findall(text))):
            if not _url_known(url, route_prefixes):
                issues.append((name, "C:dead-endpoint", f"{url} has no @app.route"))

    return issues


def main():
    parser = argparse.ArgumentParser(description="M.A.R.I.A. Web UI linter")
    parser.add_argument("--quiet", action="store_true",
                        help="print only if issues found (CI / pre-commit)")
    args = parser.parse_args()

    try:
        issues = run_lint()
    except Exception as exc:  # noqa: BLE001 - report any lint failure clearly
        print(f"[ui_lint] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if not issues:
        if not args.quiet:
            print("[ui_lint] OK -- no dead helpers, stale element ids, or dead endpoints.")
        sys.exit(0)

    print(f"[ui_lint] {len(issues)} issue(s) found:")
    for name, klass, detail in issues:
        print(f"  {name:<18} [{klass}] {detail}")
    sys.exit(1)


if __name__ == "__main__":
    main()
