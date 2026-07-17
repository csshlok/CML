from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tree_sitter import Language, Parser

from backend.app.core.code_structure import FileStructure, Symbol


REGISTRY_VERSION = "odin-extractor-registry-v1"


@dataclass(frozen=True)
class ExtractorSpec:
    language_id: str
    display_name: str
    suffixes: tuple[str, ...]
    manifest_hints: tuple[str, ...]
    extractor_version: str
    grammar_version: str
    node_kinds: tuple[str, ...]
    edge_types: tuple[str, ...]
    call_support: str
    max_file_bytes: int = 1_000_000
    generated_behavior: str = "skip"


_SPECS: dict[str, ExtractorSpec] = {}
_BY_SUFFIX: dict[str, str] = {}
_BY_MANIFEST: dict[str, str] = {}
_ADAPTERS: dict[str, Callable[[str, str, str | None, ExtractorSpec], FileStructure]] = {}
_PARSERS: dict[str, Parser] = {}


def register(spec: ExtractorSpec, adapter: Callable[[str, str, str | None, ExtractorSpec], FileStructure]) -> None:
    if spec.language_id in _SPECS:
        raise ValueError(f"Duplicate extractor: {spec.language_id}")
    _SPECS[spec.language_id] = spec
    _ADAPTERS[spec.language_id] = adapter
    for suffix in spec.suffixes:
        _BY_SUFFIX[suffix.casefold()] = spec.language_id
    for name in spec.manifest_hints:
        _BY_MANIFEST[name.casefold()] = spec.language_id


def extractor_specs() -> tuple[ExtractorSpec, ...]:
    return tuple(_SPECS[key] for key in sorted(_SPECS))


def extractor_fingerprint() -> str:
    import hashlib
    value = "|".join(
        f"{spec.language_id}:{spec.extractor_version}:{spec.grammar_version}"
        for spec in extractor_specs()
    )
    return f"{REGISTRY_VERSION}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def extractor_for_path(path: str) -> ExtractorSpec | None:
    file_path = Path(path)
    language_id = _BY_MANIFEST.get(file_path.name.casefold()) or _BY_SUFFIX.get(file_path.suffix.casefold())
    return _SPECS.get(language_id or "")


def extract_file_structure(relative_path: str, text: str, language: str, source_id: str | None) -> FileStructure:
    spec = extractor_for_path(relative_path)
    if spec is None:
        return FileStructure(status="unsupported", warnings=[{
            "category": "unsupported_language", "message": "No structure extractor is registered for this file.",
            "severity": "info", "recoverable": True,
        }])
    if len(text.encode("utf-8")) > spec.max_file_bytes:
        return FileStructure(
            status="skipped", extractor_id=spec.language_id, extractor_version=spec.extractor_version,
            grammar_version=spec.grammar_version,
            warnings=[{"category": "file_too_large", "message": f"Structure extraction is limited to {spec.max_file_bytes} bytes for this language.", "severity": "info", "recoverable": True}],
        )
    try:
        result = _ADAPTERS[spec.language_id](relative_path, text, source_id, spec)
    except Exception as exc:
        result = FileStructure(
            status="failed", parse_error="extractor_exception",
            warnings=[{"category": "extractor_exception", "message": str(exc)[:300], "severity": "error", "recoverable": True}],
        )
    result.extractor_id = spec.language_id
    result.extractor_version = spec.extractor_version
    result.grammar_version = spec.grammar_version
    if result.parse_error and result.status == "parsed":
        result.status = "failed"
    return result


def _python_adapter(path: str, text: str, source_id: str | None, spec: ExtractorSpec) -> FileStructure:
    from backend.app.core.code_structure import _extract_python
    return _extract_python(path, text, source_id)


def _json_adapter(path: str, text: str, source_id: str | None, spec: ExtractorSpec) -> FileStructure:
    from backend.app.core.code_structure import _extract_json_config, _extract_package_json
    return _extract_package_json(path, text) if Path(path).name.casefold() == "package.json" else _extract_json_config(path, text, source_id)


_DECLARATIONS = {
    "javascript": {
        "class_declaration": "class", "function_declaration": "function",
        "method_definition": "method", "lexical_declaration": "exported_value",
    },
    "typescript": {
        "class_declaration": "class", "function_declaration": "function", "method_definition": "method",
        "interface_declaration": "interface", "type_alias_declaration": "schema",
        "enum_declaration": "enum", "lexical_declaration": "exported_value",
    },
    "tsx": {
        "class_declaration": "class", "function_declaration": "function", "method_definition": "method",
        "interface_declaration": "interface", "type_alias_declaration": "schema",
        "enum_declaration": "enum", "lexical_declaration": "exported_value",
    },
    "go": {"function_declaration": "function", "method_declaration": "method", "type_declaration": "type"},
    "rust": {"function_item": "function", "struct_item": "class", "enum_item": "enum", "trait_item": "interface", "impl_item": "implementation", "type_item": "schema"},
    "java": {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum", "method_declaration": "method", "constructor_declaration": "constructor"},
    "c_sharp": {"class_declaration": "class", "interface_declaration": "interface", "struct_declaration": "class", "enum_declaration": "enum", "method_declaration": "method", "constructor_declaration": "constructor"},
    "c": {"function_definition": "function", "struct_specifier": "class", "enum_specifier": "enum", "type_definition": "schema"},
    "cpp": {"function_definition": "function", "class_specifier": "class", "struct_specifier": "class", "enum_specifier": "enum", "namespace_definition": "module", "template_declaration": "template"},
}

_IMPORT_TYPES = {
    "import_statement", "export_statement", "import_declaration", "import_spec", "use_declaration",
    "using_directive", "preproc_include",
}
_CALL_TYPES = {"call_expression", "invocation_expression"}


def _tree_sitter_adapter(path: str, text: str, source_id: str | None, spec: ExtractorSpec) -> FileStructure:
    parser = _parser(spec.language_id)
    encoded = text.encode("utf-8")
    tree = parser.parse(encoded)
    result = FileStructure(status="parsed")
    module = str(Path(path).with_suffix("")).replace("\\", "/")
    declarations = _DECLARATIONS[spec.language_id]
    owners: list[Symbol] = []

    def walk(node) -> None:
        pushed = False
        if node.type in declarations:
            name_node = node.child_by_field_name("name") or _first_identifier(node)
            if name_node is not None:
                name = _node_text(encoded, name_node)
                parent_names = [owner.label for owner in owners if owner.kind in {"class", "interface", "module", "implementation"}]
                ownership = ".".join([*parent_names, name])
                signature = _declaration_signature(encoded, node, name)
                base = f"{spec.language_id}:{module}:{ownership}:{_signature_key(signature)}"
                qualified_id = _stable_unique_id(result, base)
                kind = declarations[node.type]
                if node.type == "lexical_declaration" and _contains_type(node, {"arrow_function", "function_expression"}):
                    kind = "function"
                symbol = Symbol(
                    qualified_id=qualified_id, kind=declarations[node.type], language=spec.display_name,
                    label=name, relative_path=path, source_id=source_id,
                    start_line=node.start_point.row + 1, start_column=node.start_point.column,
                    end_line=node.end_point.row + 1, end_column=node.end_point.column,
                    signature=signature, parent_qualified_id=owners[-1].qualified_id if owners else None,
                )
                symbol.kind = kind
                _inheritance(node, encoded, symbol)
                result.symbols.append(symbol)
                owners.append(symbol)
                pushed = True
        if node.type in _IMPORT_TYPES:
            _record_import(node, encoded, result)
        if node.type in _CALL_TYPES and owners:
            function = node.child_by_field_name("function") or node.child_by_field_name("expression") or (node.named_children[0] if node.named_children else None)
            if function is not None:
                target = _node_text(encoded, function).split(".")[-1]
                if re.fullmatch(r"[A-Za-z_$][\w$]*", target):
                    owners[-1].calls.append((target, node.start_point.row + 1))
                else:
                    result.unresolved_references.append({"kind": "dynamic_call", "text": target[:120], "line": node.start_point.row + 1})
        for child in node.named_children:
            walk(child)
        if pushed:
            owners.pop()

    walk(tree.root_node)
    if spec.language_id in {"javascript", "typescript", "tsx"}:
        for match in re.finditer(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)", text):
            result.imports.append((match.group(1), text.count("\n", 0, match.start()) + 1))
    if spec.language_id in {"c", "cpp"}:
        for match in re.finditer(r"^\s*#\s*include\s*<([^>]+)>", text, flags=re.MULTILINE):
            result.imports.append((match.group(1), text.count("\n", 0, match.start()) + 1))
    result.imports = list(dict.fromkeys(result.imports))
    if tree.root_node.has_error:
        result.status = "partial"
        result.parse_error = "tree_sitter_error_nodes"
        result.warnings.append({"category": "syntax_error", "message": "The parser recovered from malformed syntax.", "severity": "warning", "recoverable": True})
    return result


def _parser(language_id: str) -> Parser:
    cached = _PARSERS.get(language_id)
    if cached is not None:
        return cached
    if language_id == "javascript":
        import tree_sitter_javascript as grammar
        capsule = grammar.language()
    elif language_id in {"typescript", "tsx"}:
        import tree_sitter_typescript as grammar
        capsule = grammar.language_tsx() if language_id == "tsx" else grammar.language_typescript()
    elif language_id == "go":
        import tree_sitter_go as grammar
        capsule = grammar.language()
    elif language_id == "rust":
        import tree_sitter_rust as grammar
        capsule = grammar.language()
    elif language_id == "java":
        import tree_sitter_java as grammar
        capsule = grammar.language()
    elif language_id == "c_sharp":
        import tree_sitter_c_sharp as grammar
        capsule = grammar.language()
    elif language_id == "c":
        import tree_sitter_c as grammar
        capsule = grammar.language()
    elif language_id == "cpp":
        import tree_sitter_cpp as grammar
        capsule = grammar.language()
    else:
        raise KeyError(language_id)
    parser = Parser(Language(capsule))
    _PARSERS[language_id] = parser
    return parser


def _node_text(encoded: bytes, node) -> str:
    return encoded[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_identifier(node):
    for child in node.named_children:
        if child.type in {"identifier", "type_identifier", "property_identifier", "field_identifier", "namespace_identifier"}:
            return child
        nested = _first_identifier(child)
        if nested is not None:
            return nested
    return None


def _contains_type(node, types: set[str]) -> bool:
    return node.type in types or any(_contains_type(child, types) for child in node.named_children)


def _declaration_signature(encoded: bytes, node, name: str) -> str:
    raw = _node_text(encoded, node)
    head = raw.split("{", 1)[0].split("=>", 1)[0].strip()
    return re.sub(r"\s+", " ", head)[:400] or name


def _signature_key(signature: str) -> str:
    import hashlib
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]


def _stable_unique_id(result: FileStructure, base: str) -> str:
    existing = {symbol.qualified_id for symbol in result.symbols}
    if base not in existing:
        return base
    index = 2
    while f"{base}#{index}" in existing:
        index += 1
    return f"{base}#{index}"


def _record_import(node, encoded: bytes, result: FileStructure) -> None:
    if node.parent is not None and node.parent.type in _IMPORT_TYPES:
        return
    raw = _node_text(encoded, node)
    line = node.start_point.row + 1
    candidates = re.findall(r"[\"']([^\"']+)[\"']", raw)
    if not candidates:
        match = re.search(r"\b(?:use|using|import)\s+([\w.:/]+)", raw)
        candidates = [match.group(1)] if match else []
    for value in candidates:
        if node.type == "export_statement":
            result.exports.append((value, line))
        else:
            result.imports.append((value, line))


def _inheritance(node, encoded: bytes, symbol: Symbol) -> None:
    raw = _declaration_signature(encoded, node, symbol.label)
    extends = re.search(r"\bextends\s+([A-Za-z_$][\w$]*)", raw)
    if extends:
        symbol.inherits.append((extends.group(1), node.start_point.row + 1))
    implements = re.search(r"\bimplements\s+([^\{]+)", raw)
    if implements:
        for name in re.findall(r"[A-Za-z_$][\w$]*", implements.group(1)):
            symbol.implements.append((name, node.start_point.row + 1))
    if symbol.language == "C#" and ":" in raw:
        bases = raw.split(":", 1)[1]
        names = re.findall(r"[A-Za-z_][\w.]*", bases)
        if names:
            symbol.inherits.append((names[0].rsplit(".", 1)[-1], node.start_point.row + 1))
            symbol.implements.extend((name.rsplit(".", 1)[-1], node.start_point.row + 1) for name in names[1:])


def _spec(language_id: str, display: str, suffixes: tuple[str, ...], grammar: str, nodes: tuple[str, ...], calls: str = "authoritative_when_resolved") -> ExtractorSpec:
    return ExtractorSpec(language_id, display, suffixes, (), f"{language_id}-adapter-v1", grammar, nodes,
                         ("contains", "imports", "reexports", "extends", "implements", "calls"), calls)


register(_spec("python", "Python", (".py",), "python-ast-runtime", ("class", "function", "method", "test")), _python_adapter)
register(ExtractorSpec("json", "JSON", (".json",), ("package.json",), "json-adapter-v1", "stdlib-json", ("configuration_key", "package"), ("depends_on_package",), "unsupported"), _json_adapter)
register(_spec("javascript", "JavaScript", (".js", ".jsx", ".mjs", ".cjs"), "tree-sitter-javascript-0.25.0", ("class", "function", "method", "exported_value")), _tree_sitter_adapter)
register(_spec("typescript", "TypeScript", (".ts", ".mts", ".cts"), "tree-sitter-typescript-0.23.2", ("class", "interface", "schema", "enum", "function", "method", "exported_value")), _tree_sitter_adapter)
register(_spec("tsx", "TSX", (".tsx",), "tree-sitter-typescript-0.23.2-tsx", ("class", "interface", "schema", "enum", "function", "method", "exported_value")), _tree_sitter_adapter)
register(_spec("go", "Go", (".go",), "tree-sitter-go-0.25.0", ("function", "method", "type")), _tree_sitter_adapter)
register(_spec("rust", "Rust", (".rs",), "tree-sitter-rust-0.24.2", ("function", "class", "enum", "interface", "implementation", "schema")), _tree_sitter_adapter)
register(_spec("java", "Java", (".java",), "tree-sitter-java-0.23.5", ("class", "interface", "enum", "method", "constructor")), _tree_sitter_adapter)
register(_spec("c_sharp", "C#", (".cs",), "tree-sitter-c-sharp-0.23.5", ("class", "interface", "enum", "method", "constructor")), _tree_sitter_adapter)
register(_spec("c", "C", (".c", ".h"), "tree-sitter-c-0.24.2", ("function", "class", "enum", "schema")), _tree_sitter_adapter)
register(_spec("cpp", "C++", (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"), "tree-sitter-cpp-0.23.4", ("function", "class", "enum", "module", "template")), _tree_sitter_adapter)
