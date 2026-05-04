"""
check_imports.py — 모듈 간 import 정합성 자동 검증
실행: python check_imports.py
모듈 분리 후, 새 기능 추가 후 항상 실행하세요.
"""
import re, ast, sys

FILES = [
    'constants.py', 'db_models.py', 'threads.py',
    'meters.py', 'video_panel.py', 'right_panel.py', 'main.py'
]
MODULE_NAMES = set(f.replace('.py', '') for f in FILES)

def read_source(fname):
    return open(fname, encoding='utf-8').read()

def get_exports(fname):
    """__all__ 우선, 없으면 def/class/전역변수"""
    c = read_source(fname)
    m = re.search(r"__all__\s*=\s*\[([^\]]+)\]", c)
    if m:
        return set(re.findall(r"'([^']+)'", m.group(1)))
    tree = ast.parse(c)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names

def check_cross_imports(exports):
    """각 파일의 from <local_module> import X 에서 X가 실제로 export되는지"""
    errors = []
    for fname in FILES:
        c = read_source(fname)
        tree = ast.parse(c)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            mod = node.module or ''
            if mod not in MODULE_NAMES:
                continue
            src_file = mod + '.py'
            available = exports.get(src_file, set())
            for alias in node.names:
                sym = alias.name
                if sym == '*':
                    continue
                if sym not in available:
                    errors.append(
                        f"  FAIL {fname} L{node.lineno}: "
                        f"'{sym}' not exported by {src_file}"
                    )
    return errors

def check_circular():
    deps = {}
    for fname in FILES:
        mod = fname.replace('.py', '')
        c = read_source(fname)
        deps[mod] = []
        tree = ast.parse(c)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                src = node.module or ''
                if src in MODULE_NAMES and src != mod and src not in deps[mod]:
                    deps[mod].append(src)

    def find_cycle(graph, start, path=None):
        if path is None: path = []
        if start in path:
            return path + [start]
        path = path + [start]
        for node in graph.get(start, []):
            result = find_cycle(graph, node, path)
            if result: return result
        return None

    cycles = []
    seen = set()
    for mod in MODULE_NAMES:
        c = find_cycle(deps, mod)
        if c:
            key = frozenset(c)
            if key not in seen:
                seen.add(key)
                cycles.append(' → '.join(c))
    return cycles

def check_syntax():
    errors = []
    for fname in FILES:
        try:
            ast.parse(read_source(fname))
        except SyntaxError as e:
            errors.append(f"  FAIL {fname} L{e.lineno}: {e.msg}")
    return errors

def main():
    print("=" * 55)
    print("  MXF QC Player - Import consistency check")
    print("=" * 55)
    all_ok = True

    print("\n[1] 문법 검사")
    syntax_errors = check_syntax()
    if syntax_errors:
        all_ok = False
        for e in syntax_errors: print(e)
    else:
        for f in FILES:
            n = len(read_source(f).splitlines())
            print(f"  OK {f} ({n} lines)")

    print("\n[2] 순환 import 검사")
    cycles = check_circular()
    if cycles:
        all_ok = False
        for c in cycles: print(f"  FAIL circular import: {c}")
    else:
        print("  OK no circular imports")

    print("\n[3] 모듈 간 심볼 정합성")
    exports = {f: get_exports(f) for f in FILES}
    errors = check_cross_imports(exports)
    if errors:
        all_ok = False
        for e in errors: print(e)
    else:
        print("  OK all imported symbols exist")

    print()
    print("=" * 55)
    if all_ok:
        print("  OK all checks passed")
    else:
        print("  FAIL issues found; fix and rerun")
    print("=" * 55)
    return 0 if all_ok else 1

if __name__ == '__main__':
    sys.exit(main())
