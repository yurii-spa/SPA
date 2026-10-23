"""Static reader of the site's JS/Astro sources: WHICH data paths a page actually reads.

Used by ``test_site_projection_chain.py`` (ADR-373 / ADR-357 п. 5 / ADR-580): the projection
«снимок → витрина → страницы» is checked by OUTCOME — every property read a page makes on the
published data must land on a path that exists in the output of the module it reads. In JavaScript
a missing field is not an error but ``undefined``, and the page prints the word «undefined»
(the ``positions_count`` accident, ADR-373). The first guard compared top-level names by regex and
was blind to nested reads; this reader parses tokens, so nested chains, ``?.``, ``['lit']`` indexes,
destructuring, aliases (``const P = NUMBERS.headline.period``), ``(X || {}).k`` and callbacks over
tracked arrays are all followed.

What it is NOT: a full JavaScript parser. Its honesty rule (inv. #17): a tracked object that escapes
into something the reader cannot follow (an unknown function argument, a spread, an object-literal
shorthand) is reported as ``UNANALYZED`` — a named third outcome, never a silent pass. Calls into the
site's own modules are not guessed at: they are recorded as call specs and executed for real under
recording proxies (``_site_read_harness``), which sees every read those modules make.

Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# ── lexer ─────────────────────────────────────────────────────────────────────────────────────────

PUNCT = sorted("""
>>>= ... === !== **= <<= >>= >>> ?.( ?.[ &&= ||= ??=
=> == != <= >= && || ?? ?. ++ -- += -= *= /= %= &= |= ^= ** << >>
{ } ( ) [ ] ; , < > + - * / % & | ^ ! ~ ? : = . @ #
""".split(), key=len, reverse=True)

REGEX_PREV_KW = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
                 "case", "do", "else", "yield", "await"}
EXPR_START_PUNCT = {"(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%",
                    "<", ">", "~", "^", "=>", "&&", "||", "??", "==", "===", "!=", "!==", "<=",
                    ">=", "+=", "-=", "*=", "/=", "%=", "&&=", "||=", "??=", "?.", "..."}

ID_START = re.compile(r"[A-Za-z_$\u0080-￿]")
ID_CHAR = re.compile(r"[A-Za-z0-9_$\u0080-￿]")


@dataclass
class Tok:
    kind: str          # id · num · str · punct · tpl_open · tpl_sep · tpl_close · jsx_open · jsx_close · eof
    val: object
    line: int


class LexError(RuntimeError):
    pass


class Lexer:
    """JS/TS/JSX tokenizer. ``jsx=True`` enables JSX elements in expression position."""

    def __init__(self, src: str, line0: int = 1, jsx: bool = True):
        self.s = src
        self.i = 0
        self.line = line0
        self.jsx = jsx
        self.out: list[Tok] = []

    # helpers
    def _prev(self):
        return self.out[-1] if self.out else None

    def _expr_start(self) -> bool:
        p = self._prev()
        if p is None:
            return True
        if p.kind == "punct":
            return p.val in EXPR_START_PUNCT
        if p.kind == "id":
            return p.val in REGEX_PREV_KW
        if p.kind in ("tpl_sep", "tpl_open", "jsx_open"):
            return True
        return False

    def _emit(self, kind, val):
        self.out.append(Tok(kind, val, self.line))

    def _adv(self, n=1):
        seg = self.s[self.i:self.i + n]
        self.line += seg.count("\n")
        self.i += n

    def tokens(self) -> list[Tok]:
        self._run(stop=None)
        self._emit("eof", None)
        return self.out

    def _run(self, stop):
        """Lex until EOF or (when ``stop`` == '}') the brace that closes the current expression."""
        depth = 0
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c in " \t\r\n":
                self._adv()
                continue
            if s.startswith("//", self.i):
                j = s.find("\n", self.i)
                self._adv((j if j >= 0 else len(s)) - self.i)
                continue
            if s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                if j < 0:
                    raise LexError(f"unterminated comment at line {self.line}")
                self._adv(j + 2 - self.i)
                continue
            if stop == "}" and c == "}" and depth == 0:
                return
            if c in "'\"":
                self._string(c)
                continue
            if c == "`":
                self._template()
                continue
            if c.isdigit() or (c == "." and self.i + 1 < len(s) and s[self.i + 1].isdigit()):
                m = re.compile(r"0[xXbBoO][0-9a-fA-F_]+n?|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?").match(s, self.i)
                txt = m.group(0)
                self._emit("num", txt)
                self._adv(len(txt))
                continue
            if ID_START.match(c):
                j = self.i + 1
                while j < len(s) and ID_CHAR.match(s[j]):
                    j += 1
                self._emit("id", s[self.i:j])
                self._adv(j - self.i)
                continue
            if c == "/" and self._expr_start():
                self._regex()
                continue
            if c == "<" and self.jsx and self._expr_start() and self._looks_like_jsx():
                self._jsx_element()
                continue
            for p in PUNCT:
                if s.startswith(p, self.i):
                    if p == "?." and self.i + 2 < len(s) and s[self.i + 2].isdigit():
                        continue            # a ? .5 : b
                    if p in ("?.(", "?.["):
                        self._emit("punct", "?.")
                        self._adv(2)
                        break
                    if p in ("{", "(", "["):
                        depth += 1 if p == "{" else 0
                    if p == "}":
                        depth -= 1
                    self._emit("punct", p)
                    self._adv(len(p))
                    break
            else:
                raise LexError(f"unexpected character {c!r} at line {self.line}")

    def _string(self, q):
        s = self.s
        j = self.i + 1
        buf = []
        while j < len(s) and s[j] != q:
            if s[j] == "\\":
                buf.append(s[j:j + 2])
                j += 2
                continue
            if s[j] == "\n":
                raise LexError(f"newline in string at line {self.line}")
            buf.append(s[j])
            j += 1
        raw = "".join(buf)
        self._emit("str", _unescape(raw))
        self._adv(j + 1 - self.i)

    def _template(self):
        s = self.s
        self._emit("tpl_open", None)
        self._adv()
        while self.i < len(s):
            c = s[self.i]
            if c == "\\":
                self._adv(2)
                continue
            if c == "`":
                self._adv()
                self._emit("tpl_close", None)
                return
            if s.startswith("${", self.i):
                self._adv(2)
                self._emit("tpl_sep", None)
                self._run(stop="}")
                if self.i >= len(s):
                    raise LexError("unterminated template expression")
                self._adv()          # the closing }
                self._emit("tpl_sep", None)
                continue
            self._adv()
        raise LexError("unterminated template literal")

    def _regex(self):
        s = self.s
        j = self.i + 1
        cls = False
        while j < len(s):
            ch = s[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "[":
                cls = True
            elif ch == "]":
                cls = False
            elif ch == "/" and not cls:
                break
            elif ch == "\n":
                raise LexError(f"unterminated regex at line {self.line}")
            j += 1
        j += 1
        while j < len(s) and ID_CHAR.match(s[j]):
            j += 1
        self._emit("str", "<regex>")
        self._adv(j - self.i)

    def _looks_like_jsx(self) -> bool:
        s = self.s
        j = self.i + 1
        return j < len(s) and (s[j] == ">" or ID_START.match(s[j]) is not None)

    def _jsx_element(self):
        """``<tag attr=… {…}>children</tag>`` → jsx_open, expression groups, jsx_close."""
        self._emit("jsx_open", None)
        self._markup(single_element=True)
        self._emit("jsx_close", None)

    def _expr_container(self):
        """At ``{``: lex the expression up to the matching ``}`` as a separate group."""
        self._adv()      # {
        self._emit("tpl_sep", None)
        self._run(stop="}")
        self._adv()      # }
        self._emit("tpl_sep", None)

    def _tag(self):
        """At ``<``: lex one tag. Returns (name, closing, selfclosing)."""
        s = self.s
        self._adv()   # <
        closing = False
        if self.i < len(s) and s[self.i] == "/":
            closing = True
            self._adv()
        m = re.compile(r"[A-Za-z0-9_$.:\-]*").match(s, self.i)
        name = m.group(0)
        self._adv(len(name))
        while self.i < len(s):
            c = s[self.i]
            if c in " \t\r\n":
                self._adv()
                continue
            if s.startswith("/>", self.i):
                self._adv(2)
                return name, closing, True
            if c == ">":
                self._adv()
                return name, closing, False
            if c == "{":
                self._expr_container()
                continue
            if c in "'\"":
                j = s.find(c, self.i + 1)
                if j < 0:
                    raise LexError(f"unterminated attribute at line {self.line}")
                self._adv(j + 1 - self.i)
                continue
            if c == "`":       # Astro allows template-literal attributes
                self._emit("tpl_sep", None)
                self._template()
                self._emit("tpl_sep", None)
                continue
            self._adv()
        raise LexError("unterminated tag")

    def _markup(self, single_element: bool, raw_text_stop: str | None = None):
        """Scan markup. ``single_element``: return when the first element closes."""
        s = self.s
        depth = 0
        while self.i < len(s):
            if s.startswith("<!--", self.i):
                j = s.find("-->", self.i)
                self._adv((j + 3 if j >= 0 else len(s)) - self.i)
                continue
            c = s[self.i]
            if c == "{":
                self._expr_container()
                continue
            if c == "<":
                nxt = s[self.i + 1] if self.i + 1 < len(s) else ""
                if not (nxt == "/" or nxt == ">" or ID_START.match(nxt or " ")):
                    self._adv()
                    continue
                name, closing, selfc = self._tag()
                low = name.lower()
                if closing:
                    depth -= 1
                    if single_element and depth <= 0:
                        return
                    continue
                if selfc:
                    if single_element and depth == 0:
                        return
                    continue
                if low in ("script", "style") and not single_element:
                    end = s.find(f"</{low}", self.i)
                    end = len(s) if end < 0 else end
                    body = s[self.i:end]
                    if low == "script":
                        self.scripts.append((body, self.line))
                    self._adv(end - self.i)
                    k = s.find(">", self.i)
                    self._adv((k + 1 if k >= 0 else len(s)) - self.i)
                    continue
                depth += 1
                continue
            self._adv()


_ESC = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _unescape(raw: str) -> str:
    def rep(m):
        e = m.group(1)
        if e.startswith("u{"):
            return chr(int(e[2:-1], 16))
        if e[0] in "ux" and len(e) > 1:
            return chr(int(e[1:], 16))
        return _SIMPLE.get(e, e)
    return _ESC.sub(rep, raw)


@dataclass
class Unit:
    """One independently scoped token stream: a module, an Astro frontmatter+template, or a <script>."""
    file: Path
    toks: list
    label: str


def units_of(path: Path) -> list[Unit]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".astro":
        fm = ""
        rest = text
        line_rest = 1
        m = re.match(r"\s*---[^\n]*\n(.*?)\n---[^\n]*\n?", text, re.S)
        if m:
            fm = m.group(1)
            rest = text[m.end():]
            line_rest = text[:m.end()].count("\n") + 1
        lx = Lexer(fm, line0=2, jsx=True)
        lx.scripts = []
        toks = lx.tokens()[:-1]
        toks.append(Tok("punct", ";", lx.line))
        mk = Lexer(rest, line0=line_rest, jsx=True)
        mk.scripts = []
        mk._markup(single_element=False)
        toks += mk.out
        toks.append(Tok("eof", None, mk.line))
        out = [Unit(path, toks, "frontmatter+template")]
        for body, ln in mk.scripts:
            sl = Lexer(body, line0=ln, jsx=False)
            sl.scripts = []
            out.append(Unit(path, sl.tokens(), f"script@{ln}"))
        return out
    lx = Lexer(text, jsx=path.suffix in (".jsx", ".tsx"))
    lx.scripts = []
    return [Unit(path, lx.tokens(), "module")]


# ── analyzer ──────────────────────────────────────────────────────────────────────────────────────

DATA_ROOTS = {
    # (path suffix of the imported module, imported name) → root of the data it hands out
    ("lib/snapshot_view.js", "default"): "VIEW",
    ("lib/site_numbers.js", "default"): "SHELF",
    ("data/site_numbers.json", "default"): "SHELF",
    ("data/track_snapshot.json", "default"): "SNAP",
}

#: member names that are methods/properties of the built-in prototypes, not data keys; a read with
#: such a key that is ABSENT in the data is the built-in, a read that is PRESENT is data.
BUILTIN_MEMBERS = set("""
length map filter forEach find findIndex findLast some every reduce reduceRight flatMap flat slice
splice sort reverse concat includes indexOf lastIndexOf join at push pop shift unshift fill keys
values entries toString toLocaleString valueOf hasOwnProperty toFixed toPrecision replace replaceAll
split trim trimStart trimEnd startsWith endsWith padStart padEnd toUpperCase toLowerCase charAt
charCodeAt substring substr match matchAll search localeCompare normalize repeat getTime toISOString
""".split())

ELEMENT_METHODS = {"map", "filter", "forEach", "find", "findIndex", "findLast", "some", "every",
                   "flatMap", "sort"}
SAME_ARRAY_METHODS = {"filter", "slice", "sort", "concat", "reverse"}
ELEMENT_RESULT_METHODS = {"find", "findLast", "at"}

BIN_PREC = {
    "??": 1, "||": 2, "&&": 3, "|": 4, "^": 5, "&": 6,
    "==": 7, "!=": 7, "===": 7, "!==": 7,
    "<": 8, ">": 8, "<=": 8, ">=": 8, "instanceof": 8, "in": 8,
    "<<": 9, ">>": 9, ">>>": 9, "+": 10, "-": 10, "*": 11, "/": 11, "%": 11, "**": 12,
}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&&=", "||=", "??=", "**=", "<<=", ">>=", ">>>=",
              "&=", "|=", "^="}
SAFE_GLOBAL_CALLS = {"Number", "String", "Boolean", "isFinite", "parseFloat", "parseInt", "isNaN",
                     "encodeURIComponent", "Date"}
SAFE_GLOBAL_OBJ = {"Math", "Number", "Array", "Date", "String"}


@dataclass(frozen=True)
class Ref:
    root: object            # "VIEW" | "SHELF" | "SNAP" | ("CALL", spec_id)
    path: tuple = ()


@dataclass(frozen=True)
class Entries:
    ref: Ref


@dataclass(frozen=True)
class Fn:
    module: str             # absolute path of the module
    name: object            # export name, or None for a namespace import


@dataclass(frozen=True)
class Lit:
    v: object


@dataclass
class LocalFn:
    params: tuple           # (start, end) token range of the parameter list (exclusive end)
    body: tuple             # (start, end) token range; expression body when toks[start] != "{"


@dataclass
class Read:
    file: str
    line: int
    root: object
    path: tuple
    kind: str = "get"       # get · whole (JSON.stringify) · has ('k' in x)


@dataclass
class Escape:
    file: str
    line: int
    ref: Ref
    why: str


@dataclass
class Spec:
    id: int
    module: str
    name: object
    args: object            # list of arg specs, "auto" (passed as a callback), or None (export value)
    site: str


class Analysis:
    """Collects reads, escapes and call specs over many units (one analysis per page tree)."""

    def __init__(self, src_root: Path, closure: set):
        self.src_root = src_root
        self.closure = closure          # modules whose functions may read data (import closure)
        self.reads: list[Read] = []
        self.escapes: list[Escape] = []
        self.specs: list[Spec] = []
        self._spec_index: dict = {}
        self.unparsed: list[str] = []

    def spec(self, module, name, args, site) -> int:
        key = (module, name, repr(args))
        if key in self._spec_index:
            return self._spec_index[key]
        sid = len(self.specs)
        self.specs.append(Spec(sid, module, name, args, site))
        self._spec_index[key] = sid
        return sid


class UnitAnalyzer:
    def __init__(self, an: Analysis, unit: Unit):
        self.an = an
        self.unit = unit
        self.t = unit.toks
        self.file = str(unit.file)
        self.scopes: list[dict] = [{}]
        self._active_fns: set = set()
        self.match = self._matching()

    # ── infrastructure ──────────────────────────────────────────────────────────────────────────
    def _matching(self):
        m = {}
        stack = []
        pairs = {")": "(", "]": "[", "}": "{"}
        for i, tk in enumerate(self.t):
            v = tk.val if tk.kind == "punct" else tk.kind
            if v in ("(", "[", "{", "tpl_open", "jsx_open"):
                stack.append((v, i))
            elif v in (")", "]", "}", "tpl_close", "jsx_close"):
                want = {"tpl_close": "tpl_open", "jsx_close": "jsx_open"}.get(v, pairs.get(v))
                while stack and stack[-1][0] != want:
                    stack.pop()
                if stack:
                    _, j = stack.pop()
                    m[j] = i
                    m[i] = j
        return m

    def is_p(self, i, v):
        tk = self.t[i] if i < len(self.t) else None
        return tk is not None and tk.kind == "punct" and tk.val == v

    def is_id(self, i, v=None):
        tk = self.t[i] if i < len(self.t) else None
        return tk is not None and tk.kind == "id" and (v is None or tk.val == v)

    def line(self, i):
        return self.t[min(i, len(self.t) - 1)].line

    def lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def declare(self, name, val):
        self.scopes[-1][name] = val

    def assign(self, name, val):
        for sc in reversed(self.scopes):
            if name in sc:
                sc[name] = val
                return
        self.scopes[0][name] = val

    def read(self, ref: Ref, key, i, kind="get") -> Ref:
        new = Ref(ref.root, ref.path + (key,))
        self.an.reads.append(Read(self.file, self.line(i), ref.root, new.path, kind))
        return new

    def escape(self, val, i, why):
        if isinstance(val, Ref):
            self.an.escapes.append(Escape(self.file, self.line(i), val, why))
        elif isinstance(val, Entries):
            self.an.escapes.append(Escape(self.file, self.line(i), val.ref, why))

    def end(self):
        return len(self.t) - 1

    # ── statements ──────────────────────────────────────────────────────────────────────────────
    def run(self):
        self.statements(0, self.end())

    def statements(self, i, end):
        while i < end:
            j = self.statement(i, end)
            i = j if j > i else i + 1

    def markup_group(self, i, close):
        """``{expr}`` of the markup (child or attribute, incl. a component prop): a tracked OBJECT used
        whole leaves the reader — a component reads it through ``Astro.props``, a child prints
        ``[object Object]`` — so it is named, never silently accepted."""
        k2 = i + 1
        while k2 < close and self.t[k2].kind != "tpl_sep":
            if self.t[k2].kind in ("tpl_open", "jsx_open") or (
                    self.t[k2].kind == "punct" and self.t[k2].val in ("(", "[", "{")):
                k2 = self.match.get(k2, k2) + 1
                continue
            k2 += 1
        if k2 == i + 1:
            return k2 + 1
        val, j = self.expr(i + 1)
        if j == k2:
            self.escape(val, i + 1, "used whole as a markup value / component prop")
        else:
            self.statements(i + 1, k2)
        return k2 + 1

    def statement(self, i, end):
        tk = self.t[i]
        if tk.kind == "tpl_sep":
            return self.markup_group(i, end)
        if tk.kind == "eof":
            return i + 1
        if tk.kind == "punct":
            if tk.val == "{":
                close = self.match.get(i, end)
                self.scopes.append({})
                self.statements(i + 1, close)
                self.scopes.pop()
                return close + 1
            if tk.val in (";", "}", ")", "]", ",", ":"):
                return i + 1
        if tk.kind == "id":
            v = tk.val
            if v == "import" and not (self.is_p(i + 1, "(") or self.is_p(i + 1, ".")):
                return self.import_stmt(i)
            if v == "export":
                j = i + 1
                if self.is_id(j, "default"):
                    j += 1
                return j
            if v in ("const", "let", "var"):
                return self.declaration(i + 1, end)
            if v == "function" or (v == "async" and self.is_id(i + 1, "function")):
                return self.function_decl(i if v == "function" else i + 1)
            if v == "interface" and self.is_id(i + 1):
                j = i + 2
                while j < end and not self.is_p(j, "{"):
                    j += 1
                return self.match.get(j, j) + 1
            if v == "type" and self.is_id(i + 1) and (self.is_p(i + 2, "=") or self.is_p(i + 2, "<")):
                return self.skip_type(i + 2, stops=(";",))
            if v == "for" and self.is_p(i + 1, "("):
                return self.for_stmt(i + 1)
            if v in ("return", "throw", "case", "else", "do", "try", "finally", "break", "continue",
                     "default", "if", "while", "switch", "catch", "yield", "await", "new", "typeof"):
                if v in ("return",):
                    val, j = self.expr(i + 1)
                    return j
                return i + 1
        _, j = self.expr(i)
        return j

    def import_stmt(self, i):
        j = i + 1
        names = []          # (local, imported)
        if self.is_id(j, "type"):
            j += 1
        if self.t[j].kind == "str":           # side-effect import
            self.module_of(self.t[j].val)
            return j + 1
        if self.is_id(j) and not self.is_id(j, "from"):
            names.append((self.t[j].val, "default"))
            j += 1
            if self.is_p(j, ","):
                j += 1
        if self.is_p(j, "*"):
            names.append((self.t[j + 2].val, None))
            j += 3
        if self.is_p(j, "{"):
            close = self.match[j]
            k = j + 1
            while k < close:
                if self.is_id(k):
                    imp = self.t[k].val
                    loc = imp
                    if self.is_id(k + 1, "as"):
                        loc = self.t[k + 2].val
                        k += 2
                    if imp != "type":
                        names.append((loc, imp))
                k += 1
            j = close + 1
        if self.is_id(j, "from"):
            j += 1
        spec = self.t[j].val if self.t[j].kind == "str" else None
        mod = self.module_of(spec) if spec else None
        for loc, imp in names:
            self.declare(loc, self.import_value(mod, imp))
        return j + 1

    def module_of(self, spec):
        if not spec or not spec.startswith("."):
            return None
        p = (self.unit.file.parent / spec).resolve()
        return str(p)

    def import_value(self, mod, imp):
        if mod is None:
            return None
        for (suffix, name), root in DATA_ROOTS.items():
            if mod.endswith(suffix) and name == imp:
                return Ref(root, ())
        if mod.endswith(".js") or mod.endswith(".mjs"):
            return Fn(mod, imp)
        return None

    def skip_type(self, i, stops):
        depth = 0
        j = i
        while j < self.end():
            tk = self.t[j]
            if tk.kind == "punct":
                if tk.val in ("(", "[", "{", "<"):
                    depth += 1
                elif tk.val in (")", "]", "}", ">"):
                    if depth == 0:
                        return j
                    depth -= 1
                elif depth == 0 and tk.val in stops:
                    return j
            j += 1
        return j

    def declaration(self, i, end):
        while i < end:
            pat_end = self.pattern_end(i)
            j = pat_end
            if self.is_p(j, "!"):
                j += 1
            if self.is_p(j, ":"):
                j = self.skip_type(j + 1, stops=("=", ",", ";"))
            if self.is_p(j, "="):
                val, j = self.assign_expr(j + 1)
                self.bind_pattern(i, pat_end, val, declare=True)
            else:
                self.bind_pattern(i, pat_end, None, declare=True)
            if self.is_p(j, ","):
                i = j + 1
                continue
            return j
        return i

    def pattern_end(self, i):
        if self.is_p(i, "{") or self.is_p(i, "["):
            return self.match[i] + 1
        return i + 1

    def bind_pattern(self, i, end, val, declare):
        """Bind an identifier or destructuring pattern ``toks[i:end]`` to ``val``."""
        put = self.declare if declare else self.assign
        tk = self.t[i]
        if tk.kind == "id":
            put(tk.val, val)
            return
        if self.is_p(i, "{"):
            close = self.match[i]
            k = i + 1
            while k < close:
                if self.is_p(k, "..."):
                    self.escape(val, k, "object rest `...` over a tracked value")
                    if self.is_id(k + 1):
                        put(self.t[k + 1].val, None)
                    k += 2
                    continue
                if self.t[k].kind in ("id", "str", "num") or self.is_p(k, "["):
                    if self.is_p(k, "["):
                        kc = self.match[k]
                        key = self.t[k + 1].val if kc == k + 2 and self.t[k + 1].kind == "str" else "*"
                        self.expr(k + 1)
                        k = kc
                    else:
                        key = self.t[k].val
                    sub = self.read(val, key, k, "destructure") if isinstance(val, Ref) else None
                    k += 1
                    if self.is_p(k, ":"):
                        tgt = k + 1
                        tend = self.pattern_end(tgt)
                        dflt_end = tend
                        if self.is_p(tend, "="):
                            _, dflt_end = self.assign_expr(tend + 1)
                        self.bind_pattern(tgt, tend, sub, declare)
                        k = dflt_end
                    else:
                        if self.is_p(k, "="):
                            _, k = self.assign_expr(k + 1)
                        put(key, sub)
                    if self.is_p(k, ","):
                        k += 1
                    continue
                k += 1
            return
        if self.is_p(i, "["):
            close = self.match[i]
            k = i + 1
            idx = 0
            while k < close:
                if self.is_p(k, ","):
                    idx += 1
                    k += 1
                    continue
                if self.is_p(k, "..."):
                    if self.is_id(k + 1):
                        put(self.t[k + 1].val, val if isinstance(val, Ref) else None)
                    k += 2
                    continue
                tend = self.pattern_end(k)
                if isinstance(val, Entries):
                    sub = Ref(val.ref.root, val.ref.path + ("*",)) if idx == 1 else None
                elif isinstance(val, Ref):
                    sub = self.read(val, "*", k, "destructure")
                elif isinstance(val, tuple) and val and val[0] == "pair":
                    sub = val[1] if idx == 1 else None
                else:
                    sub = None
                nxt = tend
                if self.is_p(tend, "="):
                    _, nxt = self.assign_expr(tend + 1)
                self.bind_pattern(k, tend, sub, declare)
                k = nxt
            return

    def function_decl(self, i):
        j = i + 1
        if self.is_p(j, "*"):
            j += 1
        name = self.t[j].val if self.is_id(j) else None
        if name:
            j += 1
        if self.is_p(j, "<"):
            j = self.skip_type(j + 1, stops=()) + 1
        if not self.is_p(j, "("):
            return j
        pclose = self.match[j]
        b = pclose + 1
        if self.is_p(b, ":"):
            while b < self.end() and not self.is_p(b, "{"):
                b += 1
        bclose = self.match.get(b, b)
        fn = LocalFn((j + 1, pclose), (b, bclose + 1))
        if name:
            self.declare(name, fn)
        self.run_fn(fn, [])
        return bclose + 1

    def for_stmt(self, i):
        close = self.match[i]
        k = i + 1
        if self.is_id(k) and self.t[k].val in ("const", "let", "var"):
            pe = self.pattern_end(k + 1)
            if self.is_id(pe, "of") or self.is_id(pe, "in"):
                val, _ = self.expr(pe + 1)
                if self.t[pe].val == "of":
                    if isinstance(val, Entries):
                        self.scopes.append({})
                        self.bind_pattern(k + 1, pe, val, declare=True)
                    elif isinstance(val, Ref):
                        self.scopes.append({})
                        self.bind_pattern(k + 1, pe, self.read(val, "*", k), declare=True)
                    else:
                        self.scopes.append({})
                        self.bind_pattern(k + 1, pe, None, declare=True)
                else:
                    self.scopes.append({})
                    self.bind_pattern(k + 1, pe, None, declare=True)
                body = close + 1
                bend = self.match[body] + 1 if self.is_p(body, "{") else self.statement(body, self.end())
                if self.is_p(body, "{"):
                    self.statements(body + 1, bend - 1)
                self.scopes.pop()
                return bend
        self.statements(i + 1, close)
        return close + 1

    # ── functions ───────────────────────────────────────────────────────────────────────────────
    def params(self, fn: LocalFn):
        """Yield (start, end) of each parameter pattern and its default-value range."""
        s, e = fn.params
        k = s
        out = []
        while k < e:
            if self.is_p(k, "..."):
                k += 1
            pe = self.pattern_end(k)
            j = pe
            if self.is_p(j, "?"):
                j += 1
            if self.is_p(j, ":"):
                j = self.skip_type(j + 1, stops=(",", "="))
            dflt = None
            if self.is_p(j, "="):
                dflt = j + 1
                j = self.skip_expr(j + 1, e)
            out.append((k, pe, dflt))
            k = j + 1 if self.is_p(j, ",") else j + 1
        return out

    def skip_expr(self, i, end):
        j = i
        while j < end:
            tk = self.t[j]
            if tk.kind == "punct" and tk.val in ("(", "[", "{"):
                j = self.match.get(j, j) + 1
                continue
            if tk.kind == "punct" and tk.val == ",":
                return j
            j += 1
        return j

    def run_fn(self, fn: LocalFn, args: list):
        key = (fn.params, fn.body)
        if key in self._active_fns and args:
            return None
        self._active_fns.add(key)
        self.scopes.append({})
        for n, (ps, pe, dflt) in enumerate(self.params(fn)):
            val = args[n] if n < len(args) else None
            if val is None and dflt is not None:
                val, _ = self.assign_expr(dflt)
            self.bind_pattern(ps, pe, val, declare=True)
        b0, b1 = fn.body
        if self.is_p(b0, "{"):
            self.statements(b0 + 1, b1 - 1)
        else:
            self.assign_expr(b0)
        self.scopes.pop()
        self._active_fns.discard(key)
        return None

    def arrow_at(self, i):
        """If an arrow function starts at ``i``, return (LocalFn, end index)."""
        k = i
        if self.is_id(k, "async") and (self.is_p(k + 1, "(") or self.is_id(k + 1)):
            k += 1
        if self.is_id(k) and self.is_p(k + 1, "=>"):
            ps, pe, arrow = k, k + 1, k + 1
        elif self.is_p(k, "("):
            close = self.match.get(k)
            if close is None:
                return None
            arrow = close + 1
            if self.is_p(arrow, ":"):
                arrow = self.skip_type(arrow + 1, stops=("=>",))
            if not self.is_p(arrow, "=>"):
                return None
            ps, pe = k + 1, close
        else:
            return None
        b = arrow + 1
        if self.is_p(b, "{"):
            bend = self.match[b] + 1
        else:
            bend = self.expr_extent(b)
        return LocalFn((ps, pe), (b, bend)), bend

    def expr_extent(self, i):
        """End of an assignment expression starting at ``i`` (stops at , ; ) ] } at depth 0)."""
        j = i
        while j < self.end():
            tk = self.t[j]
            if tk.kind in ("tpl_sep",):
                return j
            if tk.kind == "punct":
                if tk.val in ("(", "[", "{"):
                    j = self.match.get(j, j) + 1
                    continue
                if tk.val in (",", ";", ")", "]", "}"):
                    return j
            if tk.kind in ("tpl_open", "jsx_open"):
                j = self.match.get(j, j) + 1
                continue
            j += 1
        return j

    # ── expressions ─────────────────────────────────────────────────────────────────────────────
    def expr(self, i):
        val, j = self.assign_expr(i)
        while self.is_p(j, ","):
            val, j = self.assign_expr(j + 1)
        return val, j

    def assign_expr(self, i, cb_elem=None):
        arrow = self.arrow_at(i)
        if arrow is not None:
            fn, end = arrow
            self.run_fn(fn, [cb_elem] if cb_elem is not None else [])
            return fn, end
        # simple assignment target: identifier or member chain
        if self.is_id(i) and self.t[i + 1].kind == "punct" and self.t[i + 1].val in ASSIGN_OPS:
            val, j = self.assign_expr(i + 2)
            if self.t[i + 1].val == "=":
                self.assign(self.t[i].val, val)
            return val, j
        val, j = self.conditional(i)
        if self.t[j].kind == "punct" and self.t[j].val in ASSIGN_OPS:
            rhs, j2 = self.assign_expr(j + 1)
            self.escape(rhs, j, "a tracked value is stored into a property")
            return rhs, j2
        return val, j

    def conditional(self, i):
        val, j = self.binary(i, 0)
        if self.is_p(j, "?"):
            a, j = self.assign_expr(j + 1)
            if self.is_p(j, ":"):
                b, j = self.assign_expr(j + 1)
            else:
                b = None
            return (a if self._tracked(a) else b), j
        return val, j

    @staticmethod
    def _tracked(v):
        return isinstance(v, (Ref, Entries))

    def binary(self, i, minp):
        left, j = self.unary(i)
        while True:
            tk = self.t[j]
            op = tk.val if tk.kind in ("punct", "id") else None
            if tk.kind == "id" and op in ("as", "satisfies"):
                j = self._skip_as(j + 1)
                continue
            if op not in BIN_PREC or (tk.kind == "id" and op not in ("in", "instanceof")):
                return left, j
            p = BIN_PREC[op]
            if p < minp:
                return left, j
            right, j = self.binary(j + 1, p + 1)
            if op in ("||", "??"):
                left = left if self._tracked(left) else right
            elif op == "&&":
                left = right if self._tracked(right) else None
            elif op == "in" and isinstance(right, Ref) and isinstance(left, Lit):
                self.read(right, left.v, j, "has")
                left = None
            else:
                left = None

    def _skip_as(self, j):
        if self.is_id(j, "const"):
            return j + 1
        depth = 0
        while j < self.end():
            tk = self.t[j]
            if tk.kind == "id" or (tk.kind == "punct" and tk.val in (".", "|", "&")) or tk.kind == "str":
                j += 1
                continue
            if tk.kind == "punct" and tk.val in ("<", "[", "("):
                depth += 1
                j += 1
                continue
            if tk.kind == "punct" and tk.val in (">", "]", ")") and depth > 0:
                depth -= 1
                j += 1
                continue
            if depth > 0:
                j += 1
                continue
            return j
        return j

    def unary(self, i):
        tk = self.t[i]
        if tk.kind == "punct" and tk.val in ("!", "-", "+", "~", "++", "--"):
            _, j = self.unary(i + 1)
            return None, j
        if tk.kind == "punct" and tk.val == "...":
            v, j = self.assign_expr(i + 1)
            return ("spread", v), j
        if tk.kind == "id" and tk.val in ("typeof", "void", "delete", "await"):
            _, j = self.unary(i + 1)
            return None, j
        if tk.kind == "id" and tk.val == "new":
            _, j = self.postfix(i + 1, new=True)
            return None, j
        return self.postfix(i)

    def postfix(self, i, new=False):
        val, j = self.primary(i)
        while True:
            tk = self.t[j]
            if tk.kind == "punct" and tk.val in (".", "?."):
                nxt = self.t[j + 1]
                if nxt.kind == "id":
                    val = self.member(val, nxt.val, j + 1)
                    j += 2
                    continue
                if tk.val == "?." and self.is_p(j + 1, "["):
                    j += 1
                    continue
                if tk.val == "?." and self.is_p(j + 1, "("):
                    j += 1
                    continue
                return val, j + 1
            if tk.kind == "punct" and tk.val == "[":
                close = self.match[j]
                if close == j + 2 and self.t[j + 1].kind in ("str", "num"):
                    key = self.t[j + 1].val
                    key = "*" if self.t[j + 1].kind == "num" else key
                else:
                    key = "*"
                    self.expr(j + 1)
                val = self.member(val, key, j)
                j = close + 1
                continue
            if tk.kind == "punct" and tk.val == "(":
                if new:
                    close = self.match[j]
                    self.call_args(j)
                    return None, close + 1
                val, j = self.call(val, j)
                continue
            if tk.kind == "punct" and tk.val == "!" and (self.is_p(j + 1, ".") or self.is_p(j + 1, "[")
                                                         or self.is_p(j + 1, ")")):
                j += 1
                continue
            if tk.kind == "tpl_open":
                self.template(j)
                val = None
                j = self.match[j] + 1
                continue
            if tk.kind == "punct" and tk.val in ("++", "--"):
                j += 1
                continue
            return val, j

    def member(self, val, key, i):
        if isinstance(val, Ref):
            return self.read(val, key, i)
        if isinstance(val, Fn):
            if val.name is None:
                return Fn(val.module, key)
            sid = self.an.spec(val.module, val.name, None, f"{self.file}:{self.line(i)}")
            return self.read(Ref(("CALL", sid), ()), key, i)
        if isinstance(val, Entries):
            return ("method", val, key)
        if isinstance(val, tuple) and val and val[0] == "global":
            return ("global", val[1] + "." + key)
        if isinstance(val, tuple) and val and val[0] == "pair":
            return val[1] if key == "*" else None
        return None

    def call_args(self, i):
        close = self.match[i]
        args = []
        k = i + 1
        while k < close:
            v, k2 = self.assign_expr(k)
            args.append((v, k))
            k = k2 + 1 if self.is_p(k2, ",") else max(k2, k + 1)
        return args, close

    def call(self, callee, i):
        """``callee(args)`` at ``i`` == "(" → (value, index after ')')."""
        site = f"{self.file}:{self.line(i)}"
        # method call on a tracked array / entries: bind the callback's element
        if isinstance(callee, Ref) and callee.path and callee.path[-1] in BUILTIN_MEMBERS:
            method = callee.path[-1]
            base = Ref(callee.root, callee.path[:-1])
            self.an.reads[-1].kind = "maybe_builtin"
            elem = Ref(base.root, base.path + ("*",))
            args, close = self._call_with_callback(i, elem if method in ELEMENT_METHODS else
                                                   (elem if method in ("reduce", "reduceRight") else None),
                                                   second=method in ("reduce", "reduceRight"))
            if method in SAME_ARRAY_METHODS:
                return base, close + 1
            if method in ELEMENT_RESULT_METHODS:
                return elem, close + 1
            return None, close + 1
        if isinstance(callee, tuple) and callee and callee[0] == "method":
            ent, method = callee[1], callee[2]
            pair = ("pair", Ref(ent.ref.root, ent.ref.path + ("*",)))
            args, close = self._call_with_callback(i, pair if method in ELEMENT_METHODS or method == "reduce"
                                                   else None, second=method == "reduce")
            return None, close + 1
        if isinstance(callee, tuple) and callee and callee[0] == "global":
            name = callee[1]
            args, close = self.call_args(i)
            vals = [a for a, _ in args]
            if name in ("Object.entries", "Object.values"):
                return (Entries(vals[0]) if vals and isinstance(vals[0], Ref) else None), close + 1
            if name in ("Object.keys",):
                return None, close + 1
            if name == "JSON.stringify":
                for v, k in args:
                    if isinstance(v, Ref):
                        self.an.reads.append(Read(self.file, self.line(k), v.root, v.path, "whole"))
                return None, close + 1
            if name.split(".")[0] in SAFE_GLOBAL_OBJ or name in SAFE_GLOBAL_CALLS:
                return None, close + 1
            for v, k in args:
                self.escape(v, k, f"passed to `{name}(…)`, which this reader does not follow")
            return None, close + 1
        if isinstance(callee, Fn):
            args, close = self.call_args(i)
            specs = [self.arg_spec(v, k) for v, k in args]
            if callee.module in self.an.closure or any(s[0] in ("ref", "spec") for s in specs):
                sid = self.an.spec(callee.module, callee.name, specs, site)
                return Ref(("CALL", sid), ()), close + 1
            return None, close + 1
        if isinstance(callee, LocalFn):
            args, close = self.call_args(i)
            vals = [v for v, _ in args]
            if any(self._tracked(v) for v in vals):
                self.run_fn(callee, vals)
            return None, close + 1
        args, close = self.call_args(i)
        for v, k in args:
            self.escape(v, k, "passed to a function this reader does not follow")
        return None, close + 1

    def _call_with_callback(self, i, elem, second=False):
        close = self.match[i]
        args = []
        k = i + 1
        n = 0
        while k < close:
            if n == 0 and elem is not None:
                arrow = self.arrow_at(k)
                if arrow is not None:
                    fn, end = arrow
                    if second:
                        self.run_fn(fn, [None, elem])
                    else:
                        self.run_fn(fn, [elem])
                    args.append((fn, k))
                    k = end + 1 if self.is_p(end, ",") else end
                    n += 1
                    continue
                v, k2 = self.assign_expr(k)
                if isinstance(v, Fn):
                    self.an.spec(v.module, v.name, "auto", f"{self.file}:{self.line(k)}")
                elif isinstance(v, LocalFn):
                    self.run_fn(v, [None, elem] if second else [elem])
                args.append((v, k))
                k = k2 + 1 if self.is_p(k2, ",") else max(k2, k + 1)
                n += 1
                continue
            v, k2 = self.assign_expr(k)
            args.append((v, k))
            k = k2 + 1 if self.is_p(k2, ",") else max(k2, k + 1)
            n += 1
        return args, close

    def arg_spec(self, v, k):
        if isinstance(v, Lit):
            return ("lit", v.v)
        if isinstance(v, Ref):
            if isinstance(v.root, tuple):
                return ("spec", v.root[1], v.path)
            return ("ref", v.root, v.path)
        if isinstance(v, Fn):
            return ("fn", v.module, v.name)
        if isinstance(v, tuple) and v and v[0] == "now":
            return ("now",)
        return ("unknown",)

    def primary(self, i):
        tk = self.t[i]
        if tk.kind == "num":
            try:
                return Lit(float(tk.val) if any(c in tk.val for c in ".eE") else int(tk.val, 0)), i + 1
            except ValueError:
                return None, i + 1
        if tk.kind == "str":
            return Lit(tk.val), i + 1
        if tk.kind == "tpl_open":
            self.template(i)
            return None, self.match[i] + 1
        if tk.kind == "jsx_open":
            self.template(i)
            return None, self.match[i] + 1
        if tk.kind == "id":
            v = tk.val
            if v in ("true", "false"):
                return Lit(v == "true"), i + 1
            if v == "null":
                return Lit(None), i + 1
            if v == "undefined":
                return Lit("__undefined__"), i + 1
            if v == "function" or (v == "async" and self.is_id(i + 1, "function")):
                j = i if v == "function" else i + 1
                k = j + 1
                if self.is_id(k):
                    k += 1
                pclose = self.match[k]
                b = pclose + 1
                bclose = self.match[b]
                fn = LocalFn((k + 1, pclose), (b, bclose + 1))
                self.run_fn(fn, [])
                return fn, bclose + 1
            if v == "Date" and self.is_p(i + 1, ".") and self.is_id(i + 2, "now") and self.is_p(i + 3, "("):
                return ("now",), self.match[i + 3] + 1
            val = self.lookup(v)
            if val is None and v in ("Object", "JSON", "Math", "Number", "Array", "String", "Date",
                                     "Boolean", "Promise", "console", "Intl", "Reflect"):
                return ("global", v), i + 1
            if val is None and v in SAFE_GLOBAL_CALLS:
                return ("global", v), i + 1
            return val, i + 1
        if tk.kind == "punct":
            if tk.val == "(":
                close = self.match[i]
                if close == i + 1:
                    return None, close + 1
                val, _ = self.expr(i + 1)
                return val, close + 1
            if tk.val == "[":
                close = self.match[i]
                k = i + 1
                while k < close:
                    v, k2 = self.assign_expr(k)
                    if isinstance(v, tuple) and v and v[0] == "spread":
                        self.escape(v[1], k, "array spread `[...x]` of a tracked value")
                    elif self._tracked(v):
                        self.escape(v, k, "a tracked value is put into an array literal")
                    k = k2 + 1 if self.is_p(k2, ",") else max(k2, k + 1)
                return None, close + 1
            if tk.val == "{":
                return self.object_literal(i)
            if tk.val == "<":                   # TS cast <T>x
                j = self.skip_type(i + 1, stops=()) + 1
                return self.unary(j)
        return None, i + 1

    def object_literal(self, i):
        close = self.match[i]
        k = i + 1
        while k < close:
            if self.is_p(k, "..."):
                v, k = self.assign_expr(k + 1)
                self.escape(v, k, "object spread `{...x}` of a tracked value")
            elif self.is_p(k, "["):
                kc = self.match[k]
                self.expr(k + 1)
                k = kc + 1
                if self.is_p(k, ":"):
                    v, k = self.assign_expr(k + 1)
                    self.escape(v, k, "a tracked value is stored into an object literal")
            elif self.t[k].kind in ("id", "str", "num"):
                name = self.t[k].val
                if self.is_p(k + 1, ":"):
                    v, k = self.assign_expr(k + 2)
                    self.escape(v, k, f"a tracked value is stored into an object literal (`{name}:`)")
                elif self.is_p(k + 1, "("):
                    pclose = self.match[k + 1]
                    b = pclose + 1
                    bclose = self.match.get(b, b)
                    self.run_fn(LocalFn((k + 2, pclose), (b, bclose + 1)), [])
                    k = bclose + 1
                elif self.t[k].kind == "id" and name in ("get", "set", "async") and self.t[k + 1].kind == "id":
                    k += 1
                    continue
                else:
                    v = self.lookup(name) if self.t[k].kind == "id" else None
                    self.escape(v, k, f"shorthand `{{ {name} }}` stores a tracked value into an object")
                    k += 1
                    if self.is_p(k, "="):
                        _, k = self.assign_expr(k + 1)
            else:
                k += 1
                continue
            if self.is_p(k, ","):
                k += 1
            elif k < close and not self.is_p(k, "}"):
                k += 1
        return None, close + 1

    def template(self, i):
        """Analyze each ``${…}`` / ``{…}`` group of a template literal or JSX element."""
        close = self.match[i]
        k = i + 1
        while k < close:
            if self.t[k].kind == "tpl_sep":
                k = self.markup_group(k, close)
                continue
            k += 1


def module_imports(path: Path) -> list:
    """Relative imports of a JS module (absolute paths), via the lexer — not a text search."""
    out = []
    for u in units_of(path):
        toks = u.toks
        for n, tk in enumerate(toks):
            if tk.kind == "id" and tk.val in ("import", "from") and n + 1 < len(toks) and toks[n + 1].kind == "str":
                spec = toks[n + 1].val
                if spec.startswith("."):
                    out.append(str((path.parent / spec).resolve()))
    return out


def reader_closure(src_root: Path) -> set:
    """JS modules under ``src_root`` that (transitively) import the shelf, the snapshot or the view."""
    mods = {str(p.resolve()): module_imports(p) for p in src_root.rglob("*.js")}
    data = {str((src_root / "data" / "site_numbers.json").resolve()),
            str((src_root / "data" / "track_snapshot.json").resolve())}
    reach = set()
    changed = True
    while changed:
        changed = False
        for m, deps in mods.items():
            if m not in reach and any(d in data or d in reach for d in deps):
                reach.add(m)
                changed = True
    return reach


TARGET_MODULE_SUFFIXES = ("lib/snapshot_view.js", "lib/site_numbers.js", "data/site_numbers.json",
                          "lib/realized_rate.js", "lib/book_exposure.js", "data/track_snapshot.json")


def reader_files(src_root: Path) -> list:
    """Pages, components and libs that import the view, the shelf, realized_rate or book_exposure —
    directly, or through a site module that does (``profile_view.js`` → ``site_numbers.js``): a
    component reading the shelf through ``profileView()`` reads it all the same."""
    out = []
    closure = reader_closure(src_root)
    for p in sorted(src_root.rglob("*")):
        if p.suffix not in (".astro", ".js", ".jsx", ".mjs") or not p.is_file():
            continue
        try:
            imps = module_imports(p)
        except LexError:
            out.append(p)        # unreadable reader is reported by the analysis, never skipped
            continue
        if any(i.endswith(TARGET_MODULE_SUFFIXES) or i in closure for i in imps):
            out.append(p)
    return out


def analyze(src_root: Path, files=None, sources: "dict | None" = None) -> Analysis:
    """Static reads over every reader file. ``sources`` overrides file text (negative controls)."""
    closure = reader_closure(src_root)
    an = Analysis(src_root, closure)
    for p in (files if files is not None else reader_files(src_root)):
        try:
            if sources and str(p) in sources:
                tmp_units = _units_from_text(p, sources[str(p)])
            else:
                tmp_units = units_of(p)
        except LexError as exc:
            an.unparsed.append(f"{p}: {exc}")
            continue
        for u in tmp_units:
            try:
                UnitAnalyzer(an, u).run()
            except (IndexError, KeyError) as exc:
                an.unparsed.append(f"{p} [{u.label}]: analyzer could not follow the source ({exc!r})")
    return an


def _units_from_text(p: Path, text: str) -> list:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        q = Path(d) / p.name
        q.write_text(text, encoding="utf-8")
        us = units_of(q)
    for u in us:
        u.file = p
    return us
