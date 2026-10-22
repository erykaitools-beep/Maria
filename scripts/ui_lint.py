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

  C. Dead endpoint -- a "/api/..." URL with no matching application route or
     statically registered Flask Blueprint route (no application import).

Scope: catches these three static failure modes only. It does NOT prove a page
renders perfectly (logic bugs, runtime data-shape errors, an init() that is
never called are out of scope). Heuristic flags (esp. B) can be false positives
for ids built in another file -- read the context before "fixing".

Exit codes: 0 = clean, 1 = issues found, 2 = lint could not run.

Usage:
    python scripts/ui_lint.py            # full per-file report
    python scripts/ui_lint.py --quiet    # print only if issues (CI / pre-commit)
"""

import ast
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


def _scope_nodes(node):
    """Walk executable scope, excluding nested functions/classes and decorators."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _scope_nodes(child)


def _route_functions(node):
    """Decorated functions in this scope, without entering sibling factories."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child
        elif not isinstance(child, (ast.ClassDef, ast.Lambda)):
            yield from _route_functions(child)


def _bindings(body):
    result = {}
    for statement in body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            result[statement.target.id] = statement.value
    return result


def _literal_string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


def _blueprint_route_paths(app_path):
    """Resolve local Blueprint objects/factories used by register_blueprint.

    Only routes on the returned Blueprint count, not every decorator in every
    imported file. Static literal URL prefixes follow Flask's registration
    override rule. Unsupported dynamic factories fail lint rather than invent
    endpoints. This deliberately never executes/imports the application.
    """
    root = os.path.dirname(os.path.dirname(app_path))
    cache = {}

    def module_info(module):
        if module not in cache:
            path = os.path.join(root, *module.split('.')) + '.py'
            tree = ast.parse(_read(path), filename=path)
            imports = {}
            for item in tree.body:
                if isinstance(item, ast.ImportFrom):
                    package = module.split('.')[:-item.level] if item.level else []
                    source = '.'.join(package + ([item.module] if item.module else []))
                    for alias in item.names:
                        imports[alias.asname or alias.name] = (source, alias.name)
                elif isinstance(item, ast.Import):
                    for alias in item.names:
                        imports[alias.asname or alias.name] = (alias.name, None)
            cache[module] = (tree, imports, _bindings(tree.body))
        return cache[module]

    def symbol(expr, imports):
        if isinstance(expr, ast.Name):
            return imports.get(expr.id)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            origin = imports.get(expr.value.id)
            if origin and origin[1] is None:
                return (origin[0], expr.attr)
        return None

    def resolve(expr, module, scope=None, seen=None, container=None):
        seen = set() if seen is None else seen
        tree, imports, globals_ = module_info(module)
        bindings = {**globals_, **(scope or {})}
        if isinstance(expr, ast.Name) and expr.id in bindings:
            key = (module, expr.id)
            if key in seen:
                raise ValueError('Cyclic Blueprint binding')
            return resolve(bindings[expr.id], module, scope, seen | {key}, container)
        if isinstance(expr, ast.Call):
            target = symbol(expr.func, imports)
            if target == ('flask', 'Blueprint'):
                return (module, expr, scope or {}, container or tree)
            if target:
                return factory(*target)
            if isinstance(expr.func, ast.Name):
                return factory(module, expr.func.id)
        target = symbol(expr, imports)
        if target:
            other, name = target
            other_tree, _, other_bindings = module_info(other)
            if name in other_bindings:
                return resolve(other_bindings[name], other)
        raise ValueError('Cannot statically resolve registered Blueprint')

    def factory(module, name):
        tree, _, _ = module_info(module)
        fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
        if fn is None:
            raise ValueError('Registered Blueprint factory missing: ' + str(name))
        returns = [n.value for n in _scope_nodes(fn) if isinstance(n, ast.Return)]
        if len(returns) != 1:
            raise ValueError('Blueprint factory needs one statically identifiable return')
        return resolve(returns[0], module, _bindings(fn.body), container=fn)

    app_module = os.path.relpath(app_path, root)[:-3].replace(os.sep, '.')
    app_tree, _, _ = module_info(app_module)
    routes = set()
    for node in _scope_nodes(app_tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'app'
                and node.func.attr == 'register_blueprint'):
            continue
        if not node.args:
            raise ValueError('Blueprint registration has no object')
        _, constructor, scope, source_tree = resolve(node.args[0], app_module)
        prefix_expr = _keyword(node, 'url_prefix')
        if prefix_expr is None:
            prefix_expr = _keyword(constructor, 'url_prefix')
        prefix = '' if prefix_expr is None else _literal_string(prefix_expr)
        if prefix is None:
            raise ValueError('Dynamic Blueprint URL prefix is unsupported')
        owner_names = {name for name, value in scope.items() if value is constructor}
        if not owner_names:
            # Directly imported module-level Blueprint instance.
            owner_names = {name for name, value in _bindings(source_tree.body).items() if value is constructor}
        for fn in _route_functions(source_tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in fn.decorator_list:
                if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                        and isinstance(deco.func.value, ast.Name) and deco.func.value.id in owner_names
                        and deco.func.attr in {'route','get','post','put','patch','delete','options','head'}
                        and deco.args):
                    route = _literal_string(deco.args[0])
                    if route is None:
                        raise ValueError('Dynamic Blueprint route is unsupported')
                    routes.add(prefix.rstrip('/') + '/' + route.lstrip('/'))
    return routes


def _registered_route_prefixes(app_path):
    routes = _route_prefixes(_read(app_path))
    for route in _blueprint_route_paths(app_path):
        routes.add(route.rstrip('/'))
        routes.add(route.split('<')[0].rstrip('/'))
    routes.discard('')
    return routes


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
    route_prefixes = _registered_route_prefixes(APP_PY)

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
                issues.append((name, "C:dead-endpoint", f"{url} has no registered route"))

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
