from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


STRUCTURE_EXTRACTOR_VERSION = "odin-structure-v2"


@dataclass
class Symbol:
    qualified_id: str
    kind: str
    language: str
    label: str
    relative_path: str
    source_id: str | None
    start_line: int | None = None
    start_column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    signature: str = ""
    parent_qualified_id: str | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)
    inherits: list[tuple[str, int]] = field(default_factory=list)
    implements: list[tuple[str, int]] = field(default_factory=list)
    routes: list[tuple[str, str, int]] = field(default_factory=list)


@dataclass
class FileStructure:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[tuple[str, int]] = field(default_factory=list)
    exports: list[tuple[str, int]] = field(default_factory=list)
    wildcard_exports: list[tuple[str, int]] = field(default_factory=list)
    import_bindings: list["SymbolBinding"] = field(default_factory=list)
    export_bindings: list["SymbolBinding"] = field(default_factory=list)
    package_dependencies: list[str] = field(default_factory=list)
    parse_error: str = ""
    status: str = "parsed"
    extractor_id: str = ""
    extractor_version: str = ""
    grammar_version: str = ""
    warnings: list[dict] = field(default_factory=list)
    unresolved_references: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolBinding:
    local_name: str
    imported_name: str
    module: str
    line: int


def build_structure_graph(
    conn, *, project: dict, snapshot_id: str, files: list, now: str,
    source_by_path: dict[str, str] | None = None,
) -> dict:
    if source_by_path is None:
        source_by_path = {
            str(row["relative_path"]): str(row["source_id"])
            for row in conn.execute(
                "SELECT relative_path, source_id FROM project_sources WHERE project_id = ?",
                (project["id"],),
            ).fetchall()
        }
    project_node = _insert_node(
        conn,
        project_id=project["id"],
        snapshot_id=snapshot_id,
        qualified_id=f"project:{project['id']}",
        kind="project",
        language="",
        label=project["name"],
        relative_path="",
        source_id=None,
        signature="",
        content_hash=_hash_text(project["name"]),
        now=now,
    )

    file_nodes: dict[str, str] = {}
    structures: dict[str, FileStructure] = {}
    parse_failures: list[dict[str, str]] = []
    file_results: list[dict] = []
    for item in files:
        file_node = _insert_node(
            conn,
            project_id=project["id"],
            snapshot_id=snapshot_id,
            qualified_id=f"file:{_path_key(item.relative_path)}",
            kind="file",
            language=item.language,
            label=Path(item.relative_path).name,
            relative_path=item.relative_path,
            source_id=source_by_path.get(item.relative_path),
            signature=item.file_role,
            content_hash=item.content_hash,
            now=now,
            extractor_version=STRUCTURE_EXTRACTOR_VERSION,
        )
        file_nodes[_path_key(item.relative_path)] = file_node
        _insert_edge(
            conn,
            project_id=project["id"],
            snapshot_id=snapshot_id,
            source_node_id=project_node,
            target_node_id=file_node,
            edge_type="contains",
            evidence_source_id=source_by_path.get(item.relative_path),
            source_line=1,
            now=now,
        )
        structure = extract_structure(item.relative_path, item.text, item.language, source_by_path.get(item.relative_path))
        structures[item.relative_path] = structure
        file_results.append({
            "path": item.relative_path,
            "status": structure.status,
            "error_category": structure.parse_error,
            "warnings": structure.warnings,
            "unresolved_reference_count": len(structure.unresolved_references),
            "extractor_id": structure.extractor_id,
            "extractor_version": structure.extractor_version,
            "grammar_version": structure.grammar_version,
        })
        if structure.status == "failed":
            parse_failures.append({"path": item.relative_path, "category": structure.parse_error})

    symbol_nodes: dict[str, str] = {}
    simple_names: dict[str, list[str]] = defaultdict(list)
    symbol_records: dict[str, Symbol] = {}
    for relative_path, structure in structures.items():
        for symbol in structure.symbols:
            node_id = _insert_node(
                conn,
                project_id=project["id"],
                snapshot_id=snapshot_id,
                qualified_id=symbol.qualified_id,
                kind=symbol.kind,
                language=symbol.language,
                label=symbol.label,
                relative_path=symbol.relative_path,
                source_id=symbol.source_id,
                signature=symbol.signature,
                content_hash=_hash_text(f"{symbol.qualified_id}:{symbol.signature}"),
                now=now,
                extractor_version=structure.extractor_version or STRUCTURE_EXTRACTOR_VERSION,
                start_line=symbol.start_line,
                start_column=symbol.start_column,
                end_line=symbol.end_line,
                end_column=symbol.end_column,
            )
            symbol_nodes[symbol.qualified_id] = node_id
            symbol_records[symbol.qualified_id] = symbol
            simple_names[symbol.label].append(symbol.qualified_id)

    route_nodes: dict[str, str] = {}
    package_nodes: dict[str, str] = {}
    module_to_file = _module_file_index(file_nodes)
    suggestions = 0
    for relative_path, structure in structures.items():
        file_node = _file_node_id(file_nodes, relative_path)
        source_id = source_by_path.get(relative_path)
        imported_paths = {
            target
            for imported, _line in structure.imports
            if (target := _resolve_import(relative_path, imported, module_to_file))
        }
        for symbol in structure.symbols:
            symbol_node = symbol_nodes[symbol.qualified_id]
            parent_node = symbol_nodes.get(symbol.parent_qualified_id or "", file_node)
            _insert_edge(conn, project["id"], snapshot_id, parent_node, symbol_node, "contains", source_id, symbol.start_line, now)
            for route_method, route_path, line in symbol.routes:
                route_key = f"route:{route_method}:{route_path}"
                route_node = route_nodes.get(route_key)
                if route_node is None:
                    route_node = _insert_node(
                        conn,
                        project_id=project["id"],
                        snapshot_id=snapshot_id,
                        qualified_id=route_key,
                        kind="route",
                        language=symbol.language,
                        label=f"{route_method} {route_path}",
                        relative_path=relative_path,
                        source_id=source_id,
                        signature=f"{route_method} {route_path}",
                        content_hash=_hash_text(route_key),
                        now=now,
                        extractor_version=structure.extractor_version or STRUCTURE_EXTRACTOR_VERSION,
                        start_line=line,
                    )
                    route_nodes[route_key] = route_node
                _insert_edge(conn, project["id"], snapshot_id, symbol_node, route_node, "defines_route", source_id, line, now)
            for target_name, line in symbol.calls:
                candidates = simple_names.get(target_name, [])
                imported_candidates = _imported_symbol_candidates(
                    relative_path,
                    target_name,
                    structures=structures,
                    module_index=module_to_file,
                    simple_names=simple_names,
                    symbol_records=symbol_records,
                )
                if len(imported_candidates) == 1 and imported_candidates[0] != symbol.qualified_id:
                    _insert_edge(
                        conn, project["id"], snapshot_id, symbol_node,
                        symbol_nodes[imported_candidates[0]], "calls", source_id, line, now,
                    )
                elif (
                    len(candidates) == 1
                    and candidates[0] != symbol.qualified_id
                    and (
                        symbol_records[candidates[0]].relative_path == relative_path
                        or symbol_records[candidates[0]].relative_path in imported_paths
                    )
                ):
                    _insert_edge(
                        conn, project["id"], snapshot_id, symbol_node,
                        symbol_nodes[candidates[0]], "calls", source_id, line, now,
                    )
                elif len(candidates) == 1 and candidates[0] != symbol.qualified_id:
                    _insert_suggestion(
                        conn,
                        project_id=project["id"],
                        snapshot_id=snapshot_id,
                        source_node_id=symbol_node,
                        target_node_id=symbol_nodes[candidates[0]],
                        suggested_type="calls",
                        score=0.65,
                        reason=f"Call target {target_name!r} is unique but not proven by a same-file or import relationship.",
                        evidence={"line": line, "candidate_qualified_ids": candidates},
                        now=now,
                    )
                    suggestions += 1
                elif len(candidates) > 1:
                    _insert_suggestion(
                        conn,
                        project_id=project["id"],
                        snapshot_id=snapshot_id,
                        source_node_id=symbol_node,
                        target_node_id=None,
                        suggested_type="calls",
                        score=0.45,
                        reason=f"Call target {target_name!r} matches {len(candidates)} indexed symbols.",
                        evidence={"line": line, "candidate_qualified_ids": candidates[:12]},
                        now=now,
                    )
                    suggestions += 1
            for target_name, line in symbol.inherits:
                candidates = simple_names.get(target_name, [])
                if len(candidates) == 1:
                    _insert_edge(conn, project["id"], snapshot_id, symbol_node, symbol_nodes[candidates[0]], "extends", source_id, line, now)
            for target_name, line in symbol.implements:
                candidates = simple_names.get(target_name, [])
                if len(candidates) == 1:
                    _insert_edge(conn, project["id"], snapshot_id, symbol_node, symbol_nodes[candidates[0]], "implements", source_id, line, now)

        for dependency in structure.package_dependencies:
            package_key = f"package:{dependency.casefold()}"
            package_node = package_nodes.get(package_key)
            if package_node is None:
                package_node = _insert_node(
                    conn,
                    project_id=project["id"],
                    snapshot_id=snapshot_id,
                    qualified_id=package_key,
                    kind="package",
                    language="",
                    label=dependency,
                    relative_path=relative_path,
                    source_id=source_id,
                    signature="dependency",
                    content_hash=_hash_text(package_key),
                    now=now,
                    extractor_version=structure.extractor_version or STRUCTURE_EXTRACTOR_VERSION,
                )
                package_nodes[package_key] = package_node
            _insert_edge(conn, project["id"], snapshot_id, file_node, package_node, "depends_on_package", source_id, 1, now)

        for unresolved in structure.unresolved_references:
            _insert_suggestion(
                conn,
                project_id=project["id"],
                snapshot_id=snapshot_id,
                source_node_id=file_node,
                target_node_id=None,
                suggested_type=str(unresolved.get("kind") or "unresolved_reference"),
                score=0.0,
                reason="The extractor found a reference that cannot be resolved authoritatively.",
                evidence={"path": relative_path, **unresolved},
                now=now,
                extractor_version=structure.extractor_version or STRUCTURE_EXTRACTOR_VERSION,
            )
            suggestions += 1

    for relative_path, structure in structures.items():
        source_id = source_by_path.get(relative_path)
        for imported, line in structure.imports:
            target_path = _resolve_import(relative_path, imported, module_to_file)
            if target_path and target_path != relative_path:
                _insert_edge(
                    conn,
                    project["id"],
                    snapshot_id,
                    _file_node_id(file_nodes, relative_path),
                    _file_node_id(file_nodes, target_path),
                    "imports",
                    source_id,
                    line,
                    now,
                )
            elif target_path is None and _is_local_relative_import(relative_path, imported):
                _insert_suggestion(
                    conn,
                    project_id=project["id"],
                    snapshot_id=snapshot_id,
                    source_node_id=_file_node_id(file_nodes, relative_path),
                    target_node_id=None,
                    suggested_type="unresolved_import",
                    score=0.0,
                    reason="A relative import escaped the project root or did not match an indexed file.",
                    evidence={"path": relative_path, "imported": imported, "line": line},
                    now=now,
                    extractor_version=structure.extractor_version or STRUCTURE_EXTRACTOR_VERSION,
                )
                suggestions += 1
        for exported, line in structure.exports:
            target_path = _resolve_import(relative_path, exported, module_to_file)
            if target_path and target_path != relative_path:
                _insert_edge(
                    conn,
                    project["id"],
                    snapshot_id,
                    _file_node_id(file_nodes, relative_path),
                    _file_node_id(file_nodes, target_path),
                    "reexports",
                    source_id,
                    line,
                    now,
                )

    node_count = conn.execute(
        "SELECT COUNT(*) AS total FROM code_nodes WHERE project_id = ? AND snapshot_id = ?",
        (project["id"], snapshot_id),
    ).fetchone()["total"]
    edge_count = conn.execute(
        "SELECT COUNT(*) AS total FROM code_edges WHERE project_id = ? AND snapshot_id = ?",
        (project["id"], snapshot_id),
    ).fetchone()["total"]
    return {
        "node_count": int(node_count),
        "edge_count": int(edge_count),
        "symbol_count": len(symbol_nodes),
        "route_count": len(route_nodes),
        "package_count": len(package_nodes),
        "suggestion_count": suggestions,
        "parse_failure_count": len(parse_failures),
        "parse_failures": parse_failures[:100],
        "file_results": file_results,
        "unsupported_count": sum(1 for item in file_results if item["status"] == "unsupported"),
        "warning_count": sum(len(item["warnings"]) for item in file_results),
        "unresolved_reference_count": sum(int(item["unresolved_reference_count"]) for item in file_results),
    }


def extract_structure(relative_path: str, text: str, language: str, source_id: str | None) -> FileStructure:
    from backend.app.core.extractor_registry import extract_file_structure

    return extract_file_structure(relative_path, text, language, source_id)


def _extract_python(relative_path: str, text: str, source_id: str | None) -> FileStructure:
    result = FileStructure()
    try:
        tree = ast.parse(text, filename=relative_path)
    except (SyntaxError, ValueError):
        result.parse_error = "python_syntax_error"
        return result
    module = _python_module(relative_path)

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[Symbol] = []

        def visit_Import(self, node: ast.Import) -> None:
            result.imports.extend((alias.name, node.lineno) for alias in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            prefix = "." * node.level
            module = prefix + (node.module or "")
            result.imports.append((module, node.lineno))
            for alias in node.names:
                if alias.name == "*":
                    continue
                binding = SymbolBinding(alias.asname or alias.name, alias.name, module, node.lineno)
                result.import_bindings.append(binding)
                result.export_bindings.append(binding)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            qual = ".".join([*(parent.label for parent in self.parents), node.name])
            qualified_id = _unique_symbol_id(result, f"py:{module}:{qual}", node.lineno)
            symbol = Symbol(
                qualified_id=qualified_id,
                kind="class",
                language="Python",
                label=node.name,
                relative_path=relative_path,
                source_id=source_id,
                start_line=node.lineno,
                start_column=node.col_offset,
                end_line=getattr(node, "end_lineno", None),
                end_column=getattr(node, "end_col_offset", None),
                signature=f"class {node.name}",
                parent_qualified_id=self.parents[-1].qualified_id if self.parents else None,
                inherits=[(_ast_name(base), node.lineno) for base in node.bases if _ast_name(base)],
            )
            result.symbols.append(symbol)
            self.parents.append(symbol)
            self.generic_visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._function(node)

        def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qual = ".".join([*(parent.label for parent in self.parents), node.name])
            args = [argument.arg for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]
            qualified_id = _unique_symbol_id(result, f"py:{module}:{qual}", node.lineno)
            symbol = Symbol(
                qualified_id=qualified_id,
                kind="method" if self.parents and self.parents[-1].kind == "class" else ("test" if node.name.startswith("test_") else "function"),
                language="Python",
                label=node.name,
                relative_path=relative_path,
                source_id=source_id,
                start_line=node.lineno,
                start_column=node.col_offset,
                end_line=getattr(node, "end_lineno", None),
                end_column=getattr(node, "end_col_offset", None),
                signature=f"{node.name}({', '.join(args)})",
                parent_qualified_id=self.parents[-1].qualified_id if self.parents else None,
            )
            for decorator in node.decorator_list:
                route = _python_route(decorator)
                if route:
                    symbol.routes.append((route[0], route[1], getattr(decorator, "lineno", node.lineno)))
            if not relative_path.casefold().endswith(".pyi"):
                call_visitor = _PythonCallVisitor()
                for statement in node.body:
                    call_visitor.visit(statement)
                symbol.calls = call_visitor.calls
            result.symbols.append(symbol)
            self.parents.append(symbol)
            for statement in node.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.visit(statement)
            self.parents.pop()

    Visitor().visit(tree)
    return result


class _PythonCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _ast_name(node.func)
        if name:
            self.calls.append((name.rsplit(".", 1)[-1], node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _extract_package_json(relative_path: str, text: str) -> FileStructure:
    result = FileStructure()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        result.parse_error = "json_syntax_error"
        return result
    if not isinstance(payload, dict):
        return result
    dependencies: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = payload.get(key)
        if isinstance(value, dict):
            dependencies.update(str(name) for name in value)
    result.package_dependencies = sorted(dependencies, key=str.casefold)
    return result


def _extract_json_config(relative_path: str, text: str, source_id: str | None) -> FileStructure:
    result = FileStructure()
    try:
        payload = json.loads(_jsonc_to_json(text))
    except json.JSONDecodeError:
        result.parse_error = "json_syntax_error"
        return result
    if isinstance(payload, dict):
        for key in list(payload)[:200]:
            result.symbols.append(
                Symbol(
                    qualified_id=f"config:{relative_path.casefold()}:{str(key).casefold()}",
                    kind="configuration_key",
                    language="JSON",
                    label=str(key),
                    relative_path=relative_path,
                    source_id=source_id,
                    start_line=1,
                    signature=str(key),
                )
            )
    return result


def _jsonc_to_json(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and following == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and following == "*":
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                index += 1
            index = min(len(text), index + 2)
            continue
        output.append(char)
        index += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(output))


def _insert_node(
    conn,
    *,
    project_id: str,
    snapshot_id: str,
    qualified_id: str,
    kind: str,
    language: str,
    label: str,
    relative_path: str,
    source_id: str | None,
    signature: str,
    content_hash: str,
    now: str,
    start_line: int | None = None,
    start_column: int | None = None,
    end_line: int | None = None,
    end_column: int | None = None,
    extractor_version: str = STRUCTURE_EXTRACTOR_VERSION,
) -> str:
    node_id = f"code-node-{uuid4()}"
    conn.execute(
        """
        INSERT OR IGNORE INTO code_nodes (
            id, project_id, snapshot_id, source_id, qualified_id, kind, language,
            display_label, relative_path, start_line, start_column, end_line, end_column,
            signature, extraction_method, extractor_version, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id, project_id, snapshot_id, source_id, qualified_id, kind, language,
            label, relative_path, start_line, start_column, end_line, end_column,
            signature, extractor_version, extractor_version, content_hash, now,
        ),
    )
    existing = conn.execute(
        "SELECT id FROM code_nodes WHERE snapshot_id = ? AND qualified_id = ?",
        (snapshot_id, qualified_id),
    ).fetchone()
    if existing is None:
        raise RuntimeError(f"Failed to persist code node {qualified_id!r}.")
    return str(existing["id"])


def _insert_edge(
    conn,
    project_id: str,
    snapshot_id: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    evidence_source_id: str | None,
    source_line: int | None,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO code_edges (
            id, project_id, snapshot_id, source_node_id, target_node_id, edge_type,
            evidence_source_id, source_line, extraction_method, confidence_class, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', ?)
        """,
        (
            f"code-edge-{uuid4()}", project_id, snapshot_id, source_node_id, target_node_id,
            edge_type, evidence_source_id, source_line, STRUCTURE_EXTRACTOR_VERSION, now,
        ),
    )


def _insert_suggestion(
    conn,
    *,
    project_id: str,
    snapshot_id: str,
    source_node_id: str | None,
    target_node_id: str | None,
    suggested_type: str,
    score: float,
    reason: str,
    evidence: dict,
    now: str,
    extractor_version: str = STRUCTURE_EXTRACTOR_VERSION,
) -> None:
    conn.execute(
        """
        INSERT INTO relationship_suggestions (
            id, project_id, snapshot_id, source_node_id, target_node_id, suggested_type,
            score, reason, evidence_json, review_state, extractor_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            f"relationship-suggestion-{uuid4()}", project_id, snapshot_id, source_node_id,
            target_node_id, suggested_type, score, reason,
            json.dumps(evidence, separators=(",", ":")), extractor_version, now, now,
        ),
    )


def _module_file_index(file_nodes: dict[str, str]) -> dict[str, str | None]:
    index: dict[str, str | None] = {}
    for path in file_nodes:
        normalized = _path_key(path)
        stem = str(Path(normalized).with_suffix("")).replace("\\", "/")
        variants = {normalized, stem, stem.replace("/", ".")}
        if stem.endswith("/index"):
            variants.add(stem[:-6])
            variants.add(stem[:-6].replace("/", "."))
        if stem.endswith("/__init__"):
            variants.add(stem[:-9])
            variants.add(stem[:-9].replace("/", "."))
        for variant in variants:
            key = _module_key(variant)
            existing = index.get(key)
            if existing is None and key not in index:
                index[key] = path
            elif existing != path:
                index[key] = _preferred_module_path(existing, path)
    return index


def _resolve_import(relative_path: str, imported: str, module_index: dict[str, str | None]) -> str | None:
    normalized = imported.replace("\\", "/")
    keys: list[str] = []
    if relative_path.casefold().endswith(".py"):
        if normalized.startswith("."):
            level = len(normalized) - len(normalized.lstrip("."))
            parent = posixpath.dirname(_path_key(relative_path))
            package_parts = [part for part in parent.split("/") if part and part != "."]
            ascent = level - 1
            if ascent > len(package_parts):
                return None
            remainder = normalized[level:]
            target_parts = package_parts[: len(package_parts) - ascent]
            if remainder:
                target_parts.extend(part for part in remainder.split(".") if part)
            keys.append("/".join(target_parts))
        else:
            keys.extend((normalized.replace(".", "/"), normalized))
    elif normalized.startswith(("./", "../")):
        candidate = posixpath.normpath(posixpath.join(posixpath.dirname(_path_key(relative_path)), normalized))
        if candidate == ".." or candidate.startswith("../"):
            return None
        keys.append(candidate)
    else:
        keys.append(normalized)
    for candidate in keys:
        variants = [candidate]
        without_suffix = re.sub(r"\.(?:c|cc|cpp|cxx|h|hpp|java|js|jsx|mjs|cjs|ts|tsx|mts|cts|py|pyi|rs)$", "", candidate, flags=re.IGNORECASE)
        if without_suffix != candidate:
            variants.append(without_suffix)
        for variant in variants:
            resolved = module_index.get(_module_key(variant))
            if resolved:
                return resolved
    return None


def _path_key(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").lstrip("/")


def _module_key(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").lstrip("/").rstrip("/").casefold()


def _preferred_module_path(existing: str | None, candidate: str) -> str | None:
    if existing is None:
        return None
    existing_path = Path(existing)
    candidate_path = Path(candidate)
    if (
        existing_path.with_suffix("").as_posix().casefold()
        == candidate_path.with_suffix("").as_posix().casefold()
        and {existing_path.suffix.casefold(), candidate_path.suffix.casefold()} == {".py", ".pyi"}
    ):
        return candidate if candidate_path.suffix.casefold() == ".pyi" else existing
    return None


def _file_node_id(file_nodes: dict[str, str], path: str) -> str:
    key = _path_key(path)
    direct = file_nodes.get(key)
    if direct is not None:
        return direct
    matches = {node_id for candidate, node_id in file_nodes.items() if candidate.casefold() == key.casefold()}
    if len(matches) == 1:
        return matches.pop()
    raise KeyError(f"No unambiguous file node for {path!r}.")


def _is_local_relative_import(relative_path: str, imported: str) -> bool:
    normalized = imported.replace("\\", "/")
    if relative_path.casefold().endswith(".py"):
        return normalized.startswith(".")
    return normalized.startswith(("./", "../"))


def _imported_symbol_candidates(
    relative_path: str,
    local_name: str,
    *,
    structures: dict[str, FileStructure],
    module_index: dict[str, str | None],
    simple_names: dict[str, list[str]],
    symbol_records: dict[str, Symbol],
) -> list[str]:
    structure = structures.get(relative_path)
    if structure is None:
        return []
    resolved: set[str] = set()
    for binding in structure.import_bindings:
        if binding.local_name != local_name:
            continue
        target_path = _resolve_import(relative_path, binding.module, module_index)
        if target_path is None:
            continue
        resolved.update(_exported_symbol_candidates(
            target_path,
            binding.imported_name,
            structures=structures,
            module_index=module_index,
            simple_names=simple_names,
            symbol_records=symbol_records,
            visited=set(),
        ))
    return sorted(resolved)


def _exported_symbol_candidates(
    relative_path: str,
    exported_name: str,
    *,
    structures: dict[str, FileStructure],
    module_index: dict[str, str | None],
    simple_names: dict[str, list[str]],
    symbol_records: dict[str, Symbol],
    visited: set[tuple[str, str]],
) -> set[str]:
    visit_key = (relative_path, exported_name)
    if visit_key in visited:
        return set()
    visited.add(visit_key)
    resolved = {
        qualified_id
        for qualified_id in simple_names.get(exported_name, [])
        if symbol_records[qualified_id].relative_path == relative_path
    }
    structure = structures.get(relative_path)
    if structure is None:
        return resolved
    for binding in structure.export_bindings:
        if binding.local_name != exported_name:
            continue
        target_path = _resolve_import(relative_path, binding.module, module_index)
        if target_path is not None:
            resolved.update(_exported_symbol_candidates(
                target_path,
                binding.imported_name,
                structures=structures,
                module_index=module_index,
                simple_names=simple_names,
                symbol_records=symbol_records,
                visited=visited,
            ))
    for module, _line in structure.wildcard_exports:
        target_path = _resolve_import(relative_path, module, module_index)
        if target_path is not None:
            resolved.update(_exported_symbol_candidates(
                target_path,
                exported_name,
                structures=structures,
                module_index=module_index,
                simple_names=simple_names,
                symbol_records=symbol_records,
                visited=visited,
            ))
    return resolved


def _python_module(relative_path: str) -> str:
    path = str(Path(relative_path).with_suffix("")).replace("\\", ".").replace("/", ".")
    return path.removesuffix(".__init__")


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _ast_name(node.value)
    return ""


def _python_route(decorator: ast.AST) -> tuple[str, str] | None:
    if not isinstance(decorator, ast.Call):
        return None
    name = _ast_name(decorator.func)
    method = name.rsplit(".", 1)[-1].upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
        return None
    path = "<dynamic>"
    if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
        path = decorator.args[0].value
    return method, path


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unique_symbol_id(structure: FileStructure, base: str, line: int = 0) -> str:
    if all(symbol.qualified_id != base for symbol in structure.symbols):
        return base
    candidate = f"{base}#2"
    suffix = 3
    existing = {symbol.qualified_id for symbol in structure.symbols}
    while candidate in existing:
        candidate = f"{base}#{suffix}"
        suffix += 1
    return candidate
