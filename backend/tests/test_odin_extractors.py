from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.extractor_registry import extract_file_structure, extractor_for_path, extractor_specs


FIXTURES = Path(__file__).parent / "fixtures" / "odin_languages"


def _normalized(path: str) -> dict:
    text = (FIXTURES / path).read_text(encoding="utf-8")
    result = extract_file_structure(path, text, "", f"source:{path}")
    return {
        "status": result.status,
        "symbols": [[symbol.kind, symbol.label] for symbol in result.symbols],
        "imports": [value for value, _line in result.imports],
        "packages": result.package_dependencies,
        "ids": [symbol.qualified_id for symbol in result.symbols],
        "extractor": [result.extractor_id, result.extractor_version, result.grammar_version],
    }


def test_tier_a_and_b_fixture_corpus_matches_reviewed_golden() -> None:
    golden = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))
    for path, expected in golden.items():
        actual = _normalized(path)
        assert actual["status"] == "parsed", path
        assert actual["symbols"] == expected["symbols"], path
        assert actual["imports"] == expected["imports"], path
        assert actual["packages"] == expected.get("packages", []), path
        assert all(actual["extractor"]), path


def test_extractors_are_deterministic_across_three_runs() -> None:
    golden = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))
    for path in golden:
        outputs = [_normalized(path) for _ in range(3)]
        assert outputs[0] == outputs[1] == outputs[2], path


def test_stable_symbol_identity_ignores_unrelated_line_moves() -> None:
    original = "class Service:\n    def execute(self):\n        return 1\n"
    moved = "# unrelated header\n\n" + original
    first = extract_file_structure("service.py", original, "Python", None)
    second = extract_file_structure("service.py", moved, "Python", None)
    assert [item.qualified_id for item in first.symbols] == [item.qualified_id for item in second.symbols]


def test_typescript_ast_handles_nested_computed_and_reexported_syntax() -> None:
    text = '''
// function commentedOut() {}
const stringLiteral = "class NotADeclaration {}";
export { thing as renamed } from "./thing";
export * from "./all";
export function outer() {
  function inner() { return helper(); }
  const arrow = (value: number) => value + 1;
}
class Box { ["computed"]() { return outer(); } }
'''
    result = extract_file_structure("edge.ts", text, "TypeScript", None)

    assert result.status == "parsed"
    assert [(symbol.kind, symbol.label) for symbol in result.symbols] == [
        ("exported_value", "stringLiteral"),
        ("function", "outer"),
        ("function", "inner"),
        ("function", "arrow"),
        ("class", "Box"),
        ("method", '["computed"]'),
    ]
    assert [path for path, _line in result.exports] == ["./thing", "./all"]
    assert all(symbol.label not in {"commentedOut", "NotADeclaration"} for symbol in result.symbols)
    outer = next(symbol for symbol in result.symbols if symbol.label == "outer")
    assert all(
        symbol.parent_qualified_id == outer.qualified_id
        for symbol in result.symbols
        if symbol.label in {"inner", "arrow"}
    )


def test_tsx_promotes_direct_arrow_components_without_promoting_callback_values() -> None:
    result = extract_file_structure(
        "Component.tsx",
        """
export const Component = () => <section>Ready</section>;
const wrapped = (() => <aside>Wrapped</aside>);
const values = items.map((item) => item.value);
""",
        "TypeScript",
        None,
    )

    kinds = {symbol.label: symbol.kind for symbol in result.symbols}
    assert kinds["Component"] == "component"
    assert kinds["wrapped"] == "function"
    assert kinds["values"] == "exported_value"


def test_typescript_records_named_type_dynamic_and_barrel_imports() -> None:
    result = extract_file_structure(
        "consumer.ts",
        """
import type { PublicType as LocalType } from "./types";
import { execute as run } from "./commands";
export { helper as publicHelper } from "./helpers";
export * from "./shared";
const lazy = import("./lazy");
""",
        "TypeScript",
        None,
    )

    assert ("LocalType", "PublicType", "./types") in {
        (binding.local_name, binding.imported_name, binding.module) for binding in result.import_bindings
    }
    assert ("run", "execute", "./commands") in {
        (binding.local_name, binding.imported_name, binding.module) for binding in result.import_bindings
    }
    assert ("publicHelper", "helper", "./helpers") in {
        (binding.local_name, binding.imported_name, binding.module) for binding in result.export_bindings
    }
    assert "./lazy" in {module for module, _line in result.imports}
    assert result.wildcard_exports == [("./shared", 5)]


def test_python_stub_extracts_declarations_without_call_edges() -> None:
    result = extract_file_structure(
        "client.pyi",
        "class Client:\n    def request(self, url: str) -> bytes: ...\n\ndef create() -> Client: ...\n",
        "Python",
        None,
    )

    assert [(symbol.kind, symbol.label) for symbol in result.symbols] == [
        ("class", "Client"),
        ("method", "request"),
        ("function", "create"),
    ]
    assert all(not symbol.calls for symbol in result.symbols)
    assert extractor_for_path("client.pyi") is not None


@pytest.mark.parametrize("path,text", [
    ("broken.py", "def broken(:\n"),
    ("broken.ts", "export function broken( {\n"),
    ("broken.rs", "fn broken( {\n"),
])
def test_malformed_files_degrade_without_crashing(path: str, text: str) -> None:
    result = extract_file_structure(path, text, "", None)
    assert result.status in {"failed", "partial"}
    assert result.parse_error


def test_unsupported_file_preserves_nonfatal_retrieval_state() -> None:
    result = extract_file_structure("notes.odt", "still retrievable", "", None)
    assert result.status == "unsupported"
    assert result.warnings[0]["recoverable"] is True


def test_registry_has_unique_suffix_ownership_and_versions() -> None:
    seen: set[str] = set()
    for spec in extractor_specs():
        assert spec.extractor_version and spec.grammar_version
        for suffix in spec.suffixes:
            assert suffix not in seen
            seen.add(suffix)
            assert extractor_for_path(f"file{suffix}") == spec


def test_windows_package_pins_every_offline_grammar() -> None:
    package_script = (Path(__file__).parents[2] / "scripts" / "packaging" / "package-windows.ps1").read_text(encoding="utf-8")
    expected = {
        "tree-sitter==0.25.2", "tree-sitter-javascript==0.25.0", "tree-sitter-typescript==0.23.2",
        "tree-sitter-go==0.25.0", "tree-sitter-rust==0.24.2", "tree-sitter-java==0.23.5",
        "tree-sitter-c-sharp==0.23.5", "tree-sitter-c==0.24.2", "tree-sitter-cpp==0.23.4",
    }
    assert all(f'"{package}"' in package_script for package in expected)
