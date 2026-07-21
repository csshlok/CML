from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.atomic_memory import (
    AtomicCitation,
    AtomicFact,
    AtomicQuantity,
    compile_semantic_atomic_session,
    deduplicate_atomic_facts,
    deterministic_atomic_facts,
    evaluate_deterministic_operation,
    export_semantic_normalization_jobs,
    extract_atomic_memory,
    import_semantic_normalization_results,
    materialize_progressive_counters,
    pack_atomic_facts,
    plan_atomic_query,
    route_atomic_question,
    source_content_hash,
    validate_atomic_contract,
)


def _session() -> dict:
    return {
        "session_id": "s1",
        "date": "2025-01-02",
        "turns": [
            {"role": "user", "content": "I bought three yellow dresses."},
            {"role": "assistant", "content": "Roscioli is the romantic restaurant."},
        ],
    }


def _fact(*, fact_id: str = "f1", object_text: str = "three yellow dresses") -> AtomicFact:
    session = _session()
    return AtomicFact(
        fact_id=fact_id,
        citation=AtomicCitation(
            session_id="s1",
            turn_index=0,
            speaker="user",
            session_date=session["date"],
            excerpt=session["turns"][0]["content"],
            source_content_hash=source_content_hash(
                session["session_id"], session["date"], session["turns"]
            ),
        ),
        subject="user",
        predicate="bought",
        object_text=object_text,
        fact_kind="event",
        observed_date=session["date"],
        confidence=0.95,
    )


def test_atomic_extraction_preserves_user_and_assistant_facts(tmp_path: Path) -> None:
    session = _session()

    def extractor(_prompt: str) -> tuple[str, dict]:
        return json.dumps(
            {
                "sessions": [
                    {
                        "session_id": "s1",
                        "facts": [
                            {
                                "fact_id": "user-purchase",
                                "citation": {
                                    "turn_index": 0,
                                    "excerpt": "I bought three yellow dresses.",
                                },
                                "subject": "user",
                                "predicate": "bought",
                                "object_text": "three yellow dresses",
                                "fact_kind": "event",
                                "confidence": 0.98,
                            },
                            {
                                "fact_id": "assistant-restaurant",
                                "citation": {
                                    "turn_index": 1,
                                    "excerpt": "Roscioli is the romantic restaurant.",
                                },
                                "subject": "Roscioli",
                                "predicate": "is",
                                "object_text": "romantic restaurant",
                                "fact_kind": "attribute",
                                "confidence": 0.99,
                            },
                        ],
                    }
                ]
            }
        ), {"prompt_tokens": 10}

    facts, diagnostics = extract_atomic_memory(
        [session],
        model="test",
        cache_dir=tmp_path,
        extractor=extractor,
        include_lossless_atoms=False,
    )

    assert len(facts) == 2
    assert {fact.citation.speaker for fact in facts} == {"user", "assistant"}
    assert diagnostics.valid_fact_count == 2
    assert diagnostics.invalid_fact_count == 0


def test_atomic_extraction_rejects_non_verbatim_citation(tmp_path: Path) -> None:
    def extractor(_prompt: str) -> tuple[str, dict]:
        return json.dumps(
            {
                "sessions": [
                    {
                        "session_id": "s1",
                        "facts": [
                            {
                                "fact_id": "invented",
                                "citation": {"turn_index": 0, "excerpt": "I bought a blue car."},
                                "subject": "user",
                                "predicate": "bought",
                                "object_text": "blue car",
                                "fact_kind": "event",
                                "confidence": 0.9,
                            }
                        ],
                    }
                ]
            }
        ), {}

    facts, diagnostics = extract_atomic_memory(
        [_session()],
        model="test",
        cache_dir=tmp_path,
        extractor=extractor,
        include_lossless_atoms=False,
    )

    assert facts == []
    assert diagnostics.invalid_by_reason == {"excerpt_not_exact": 1}


def test_semantic_compiler_chunks_long_sessions_and_restores_turn_indices() -> None:
    session = {
        "session_id": "long-session",
        "date": "2026-07-22",
        "turns": [
            {"role": "user", "content": "A" * 1_100},
            {"role": "assistant", "content": "Dr. Lee recommended rest."},
        ],
    }
    calls = 0

    def extractor(prompt: str) -> tuple[str, dict]:
        nonlocal calls
        calls += 1
        payload = json.loads(prompt.split("Sessions:\n", 1)[1])
        turns = payload[0]["turns"]
        facts = []
        for turn_index, turn in enumerate(turns):
            if "Dr. Lee" in turn["content"]:
                facts.append(
                    {
                        "fact_id": "doctor",
                        "citation": {
                            "turn_index": turn_index,
                            "excerpt": "Dr. Lee recommended rest.",
                        },
                        "subject": "Dr. Lee",
                        "predicate": "recommended",
                        "object_text": "rest",
                        "fact_kind": "recommendation",
                        "confidence": 0.98,
                    }
                )
        return json.dumps(
            {"sessions": [{"session_id": "long-session", "facts": facts}]}
        ), {"prompt_tokens": 5}

    extraction, reasons, usage = compile_semantic_atomic_session(
        session,
        extractor=extractor,
        max_source_chars=1_000,
    )

    assert calls >= 2
    assert len(extraction.facts) == 1
    assert extraction.facts[0].citation.turn_index == 1
    assert extraction.facts[0].citation.source_content_hash == source_content_hash(
        session["session_id"], session["date"], session["turns"]
    )
    assert reasons == {}
    assert usage["prompt_tokens"] == calls * 5


def test_lossless_atomic_compiler_persists_exact_table_rows(tmp_path: Path) -> None:
    session = _session()
    session["turns"][1]["content"] = (
        "| Shift | Sunday |\n| --- | --- |\n| Admon | 8 am - 4 pm |"
    )

    facts, diagnostics = extract_atomic_memory(
        [session], model="deterministic", cache_dir=tmp_path, extractor=None
    )
    resumed, resumed_diagnostics = extract_atomic_memory(
        [session], model="deterministic", cache_dir=tmp_path, extractor=None
    )

    assert any(fact.object_text == "| Admon | 8 am - 4 pm |" for fact in facts)
    assert all(
        fact.citation.excerpt
        in session["turns"][fact.citation.turn_index]["content"]
        for fact in facts
    )
    assert diagnostics.extracted_session_count == 1
    assert resumed_diagnostics.cache_hit_count == 1
    assert [fact.fact_id for fact in resumed] == [fact.fact_id for fact in facts]


def test_atomic_deduplication_is_session_and_turn_scoped() -> None:
    duplicate = _fact(fact_id="f2")
    distinct = _fact(fact_id="f3", object_text="a yellow dress")

    facts, removed = deduplicate_atomic_facts([_fact(), duplicate, distinct])

    assert removed == 1
    assert [fact.fact_id for fact in facts] == ["f1", "f3"]


def test_atomic_packer_prioritizes_question_relevant_fact() -> None:
    relevant = _fact(object_text="three yellow dresses")
    irrelevant = _fact(fact_id="f2", object_text="a bedside lamp")

    context, metadata = pack_atomic_facts(
        "How many yellow dresses did I buy?",
        [irrelevant, relevant],
        ["s1"],
        token_budget=110,
    )

    assert "three yellow dresses" in context
    assert metadata["selected_fact_count"] >= 1
    assert metadata["packed_tokens_estimate"] <= 110


def test_atomic_packer_deduplicates_repeated_assistant_units() -> None:
    first = _fact(fact_id="a1", object_text="Roscioli is the romantic restaurant")
    first = first.model_copy(
        update={
            "citation": first.citation.model_copy(update={"speaker": "assistant"}),
            "subject": "assistant",
            "qualifiers": {"atomic_origin": "deterministic_lossless"},
        }
    )
    second = first.model_copy(
        update={
            "fact_id": "a2",
            "citation": first.citation.model_copy(update={"session_id": "s2"}),
        }
    )

    context, metadata = pack_atomic_facts(
        "Which romantic restaurant was recommended?",
        [first, second],
        ["s1", "s2"],
        token_budget=200,
    )

    assert context.count("Roscioli is the romantic restaurant") == 1
    assert metadata["candidate_fact_count"] == 2
    assert metadata["presentation_fact_count"] == 1


def test_atomic_packer_retains_broad_user_history_for_count_queries() -> None:
    facts = []
    session_ids = [f"s{index}" for index in range(10)]
    for index, session_id in enumerate(session_ids):
        fact = _fact(fact_id=f"f{index}", object_text=f"I visited Dr. Person {index}")
        facts.append(
            fact.model_copy(
                update={
                    "citation": fact.citation.model_copy(
                        update={"session_id": session_id}
                    ),
                    "qualifiers": {"atomic_origin": "deterministic_lossless"},
                }
            )
        )

    context, metadata = pack_atomic_facts(
        "How many doctors did I visit?",
        facts,
        session_ids,
        token_budget=800,
    )

    assert "I visited Dr. Person 9" in context
    assert metadata["represented_session_count"] == 10
    assert metadata["safe"] is True


def test_atomic_packer_keeps_table_header_with_selected_row(tmp_path: Path) -> None:
    session = _session()
    session["turns"][1]["content"] = (
        "| Shift | Sunday |\n| --- | --- |\n| Admon | 8 am - 4 pm |"
    )
    facts, _ = extract_atomic_memory(
        [session], model="table", cache_dir=tmp_path, extractor=None
    )
    context, _ = pack_atomic_facts(
        "When is Admon's Sunday shift?", facts, ["s1"], token_budget=500
    )
    assert "| Shift | Sunday |" in context
    assert "| Admon | 8 am - 4 pm |" in context


def test_router_uses_question_semantics_without_benchmark_type() -> None:
    assert route_atomic_question(
        "How has my coffee limit changed?", retrieved_session_count=10
    ).path == "atomic"
    assert route_atomic_question(
        "Which activities came up across our conversations?",
        retrieved_session_count=10,
    ).path == "atomic"
    assert route_atomic_question(
        "What speed is my internet plan?", retrieved_session_count=10
    ).path == "claim-first"
    assert plan_atomic_query("Am I drinking more coffee than before?").operation == "state_comparison"


def test_frozen_query_generalization_suite() -> None:
    fixture = Path("backend/tests/fixtures/atomic_query_generalization_cases.json")
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    for case in cases:
        plan = plan_atomic_query(case["question"])
        route = route_atomic_question(
            case["question"], retrieved_session_count=case["sessions"], plan=plan
        )
        assert plan.operation == case["operation"], case["id"]
        assert route.path == case["path"], case["id"]


def test_frozen_query_generalization_metamorphic_suite() -> None:
    fixture = Path("backend/tests/fixtures/atomic_query_generalization_cases.json")
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    replacements = (
        ("currently", "at present"),
        ("How many", "What is the number of"),
        ("total", "combined"),
        ("average", "mean"),
        ("most recently", "latest"),
        ("first", "earliest"),
    )
    for case in cases:
        synonym = case["question"]
        for old, new in replacements:
            if old.casefold() in synonym.casefold():
                position = synonym.casefold().index(old.casefold())
                synonym = synonym[:position] + new + synonym[position + len(old):]
                break
        variants = (
            f"Could you tell me: {case['question']}",
            f"Based only on what I previously shared, {case['question']}",
            case["question"] + " Please ignore unrelated dates and prices.",
            synonym,
        )
        for index, question in enumerate(variants):
            plan = plan_atomic_query(question)
            route = route_atomic_question(
                question, retrieved_session_count=case["sessions"], plan=plan
            )
            assert plan.operation == case["operation"], (case["id"], index, question)
            assert route.path == case["path"], (case["id"], index, question)


def test_lossless_normalizer_parses_grouped_currency_without_partial_numbers() -> None:
    session = _session()
    session["turns"][0]["content"] = "We raised $1,000 for the community charity."
    quantities = [
        fact.quantity
        for fact in deterministic_atomic_facts(session)
        if fact.quantity is not None
    ]
    assert [(quantity.value, quantity.unit) for quantity in quantities] == [
        (1000.0, "dollars")
    ]


def test_extraction_records_complete_source_unit_coverage(tmp_path: Path) -> None:
    _, diagnostics = extract_atomic_memory(
        [_session()], model="coverage", cache_dir=tmp_path, extractor=None
    )
    assert diagnostics.source_unit_count == 2
    assert diagnostics.covered_source_unit_count == 2
    assert diagnostics.source_coverage_complete is True


def test_current_activity_normalizes_indirect_book_language() -> None:
    session = _session()
    session["turns"][0]["content"] = (
        'I am currently devouring "The Seven Husbands of Evelyn Hugo".'
    )
    facts = deterministic_atomic_facts(session)
    normalized = [fact for fact in facts if fact.predicate == "currently_reading"]
    assert len(normalized) == 1
    assert normalized[0].fact_kind == "state"
    assert normalized[0].qualifiers["object_type"] == "book"


def test_calendar_last_is_not_misrouted_as_event_order() -> None:
    assert plan_atomic_query(
        "Who did I go with to the music event last Saturday?"
    ).operation == "direct_lookup"


def test_count_sum_infers_subject_role_and_deduplicates_repeated_mentions() -> None:
    session = {
        "session_id": "social",
        "date": "2025-01-02",
        "turns": [
            {"role": "user", "content": "My Facebook Live got 12 comments."},
            {"role": "user", "content": "That Facebook Live received 12 comments."},
            {"role": "user", "content": "My YouTube video has 21 comments."},
            {"role": "user", "content": "I work from 8:30 AM to 12:00 PM."},
        ],
    }
    question = "What is the total number of comments on Facebook and YouTube?"
    plan = plan_atomic_query(question)
    assert plan.quantity_subject_terms == ["comment"]
    facts = deterministic_atomic_facts(session)
    selected = [fact.fact_id for fact in facts]
    contract = validate_atomic_contract(
        plan, facts, selected, {"safe": True, "safety_reasons": []}
    )
    operation = evaluate_deterministic_operation(
        question,
        facts,
        selected,
        plan=plan,
        operand_fact_ids=contract.operand_fact_ids,
    )
    assert contract.safe is True
    assert operation.resolved is True
    assert operation.result == "33 number"
    assert plan_atomic_query(
        "What artist did I start listening to last Friday?"
    ).operation == "direct_lookup"


def test_lossless_normalizer_types_written_quantities(tmp_path: Path) -> None:
    session = _session()
    session["turns"][0]["content"] = "I cut back to just one cup in the morning."
    facts, _ = extract_atomic_memory(
        [session], model="written-number", cache_dir=tmp_path, extractor=None
    )
    matching = [fact for fact in facts if "one cup" in fact.object_text]
    assert matching[0].quantity is not None
    assert matching[0].quantity.value == 1
    assert matching[0].quantity.unit == "cup"


def test_state_contract_requires_previous_and_current_operands() -> None:
    plan = plan_atomic_query("Did my morning coffee limit increase or decrease?")
    previous = _fact(fact_id="previous", object_text="one cup in the morning").model_copy(
        update={
            "fact_kind": "state",
            "observed_date": "2025-01-01",
            "quantity": AtomicQuantity(value=1, unit="cup", role="limit"),
            "supersession_key": "user:coffee_limit",
        }
    )
    current = _fact(fact_id="current", object_text="two cups in the morning").model_copy(
        update={
            "fact_kind": "state",
            "observed_date": "2025-02-01",
            "quantity": AtomicQuantity(value=2, unit="cups", role="limit"),
            "supersession_key": "user:coffee_limit",
            "citation": _fact().citation.model_copy(update={"turn_index": 1}),
        }
    )
    complete = validate_atomic_contract(
        plan,
        [previous, current],
        ["previous", "current"],
        {"safe": True, "safety_reasons": []},
    )
    incomplete = validate_atomic_contract(
        plan,
        [previous, current],
        ["current"],
        {"safe": True, "safety_reasons": []},
    )
    assert complete.safe is True
    assert incomplete.safe is False
    assert "previous_state" in incomplete.missing_slots


def test_closed_set_count_requires_normalized_category_facts() -> None:
    plan = plan_atomic_query("How many different doctors did I visit?")
    lossless = _fact(fact_id="doctor", object_text="I visited Dr. Lee").model_copy(
        update={"qualifiers": {"atomic_origin": "deterministic_lossless"}}
    )
    normalized = lossless.model_copy(
        update={
            "fact_id": "doctor-normalized",
            "predicate": "visited_doctor",
            "object_text": "doctor Dr. Lee",
            "qualifiers": {
                "category": "doctor",
                "closed_world_category": "true",
            },
        }
    )
    unsafe = validate_atomic_contract(
        plan, [lossless], [lossless.fact_id], {"safe": True, "safety_reasons": []}
    )
    safe = validate_atomic_contract(
        plan,
        [normalized],
        [normalized.fact_id],
        {"safe": True, "safety_reasons": []},
    )
    assert unsafe.safe is False
    assert "closed_world_category_coverage" in unsafe.missing_slots
    assert safe.safe is True


def test_explicit_cardinality_proves_count_without_synthetic_list_items() -> None:
    question = "How many amateur comedians did I watch perform?"
    plan = plan_atomic_query(question)
    cardinality = _fact(
        fact_id="comedian-count",
        object_text="I watched 10 amateur comedians perform",
    ).model_copy(
        update={
            "fact_kind": "quantity",
            "quantity": AtomicQuantity(value=10, unit="number", role="mentioned_quantity"),
            "qualifiers": {
                "atomic_origin": "deterministic_lossless",
                "quantity_context": "I watched 10 amateur comedians perform",
            },
        }
    )
    contract = validate_atomic_contract(
        plan,
        [cardinality],
        [cardinality.fact_id],
        {"safe": True, "safety_reasons": []},
    )
    operation = evaluate_deterministic_operation(
        question,
        [cardinality],
        [cardinality.fact_id],
        plan=plan,
        operand_fact_ids=contract.operand_fact_ids,
    )
    assert plan.quantity_subject_terms == ["amateur", "comedian"]
    assert contract.safe is True
    assert "closed_world_category_coverage" not in contract.missing_slots
    assert operation.operation == "declared_cardinality"
    assert operation.result == "10"


def test_multiple_cardinality_claims_do_not_imply_closed_world_count() -> None:
    plan = plan_atomic_query("How many amateur comedians did I watch perform?")
    facts = []
    for index, value in enumerate((8, 10)):
        facts.append(
            _fact(
                fact_id=f"comedian-count-{index}",
                object_text=f"I watched {value} amateur comedians perform",
            ).model_copy(
                update={
                    "fact_kind": "quantity",
                    "quantity": AtomicQuantity(
                        value=value, unit="number", role="mentioned_quantity"
                    ),
                    "qualifiers": {
                        "atomic_origin": "deterministic_lossless",
                        "quantity_context": f"I watched {value} amateur comedians perform",
                    },
                    "citation": _fact().citation.model_copy(update={"turn_index": index}),
                }
            )
        )
    contract = validate_atomic_contract(
        plan,
        facts,
        [fact.fact_id for fact in facts],
        {"safe": True, "safety_reasons": []},
    )
    assert contract.safe is False
    assert "closed_world_category_coverage" in contract.missing_slots


def test_numeric_sum_excludes_container_capacity_from_item_count() -> None:
    plan = plan_atomic_query("What is the total number of fish in both aquariums?")
    capacity = _fact(fact_id="tank", object_text="my 20-gallon aquarium").model_copy(
        update={
            "quantity": AtomicQuantity(value=20, unit="gallon", role="capacity"),
            "qualifiers": {"quantity_context": "my 20-gallon aquarium"},
        }
    )
    fish = []
    for index, value in enumerate((10, 7), start=1):
        fish.append(
            _fact(fact_id=f"fish-{index}", object_text=f"aquarium has {value} fish").model_copy(
                update={
                    "quantity": AtomicQuantity(
                        value=value, unit="number", role="mentioned_quantity"
                    ),
                    "qualifiers": {"quantity_context": f"aquarium has {value} fish"},
                    "citation": _fact().citation.model_copy(update={"turn_index": index}),
                }
            )
        )
    facts = [capacity, *fish]
    contract = validate_atomic_contract(
        plan,
        facts,
        [fact.fact_id for fact in facts],
        {"safe": True, "safety_reasons": []},
    )
    operation = evaluate_deterministic_operation(
        "What is the total number of fish in both aquariums?",
        facts,
        [fact.fact_id for fact in facts],
        plan=plan,
        operand_fact_ids=contract.operand_fact_ids,
    )
    assert contract.safe is True
    assert capacity.fact_id not in contract.operand_fact_ids
    assert operation.result == "17 number"


def test_write_time_state_patterns_cover_trailing_now_and_storage_location() -> None:
    session = _session()
    session["turns"][0]["content"] = (
        "I have 1300 Instagram followers right now. "
        "I currently keep my old sneakers in a shoe rack in my closet."
    )
    facts = deterministic_atomic_facts(session)
    states = [fact for fact in facts if fact.fact_kind == "state"]
    assert any(
        fact.predicate == "current_quantity"
        and fact.object_text == "1300 Instagram followers"
        and fact.supersession_key
        for fact in states
    )
    assert any(
        fact.predicate == "currently_stored_at"
        and fact.object_text == "a shoe rack in my closet"
        and fact.qualifiers.get("stored_object") == "my old sneakers"
        for fact in states
    )


def test_current_state_requires_latest_fact_to_cover_requested_concept() -> None:
    plan = plan_atomic_query("What book am I currently reading?")
    old_book = _fact(
        fact_id="old-book",
        object_text="I was reading The Left Hand of Darkness",
    ).model_copy(update={"fact_kind": "state", "supersession_key": "reading"})
    generic_latest = _fact(
        fact_id="reading-habit",
        object_text="I am currently making reading a habit loop",
    ).model_copy(
        update={
            "fact_kind": "state",
            "supersession_key": "reading",
            "observed_date": "2024-02-01",
        }
    )
    contract = validate_atomic_contract(
        plan,
        [old_book, generic_latest],
        [old_book.fact_id, generic_latest.fact_id],
        {"safe": True, "safety_reasons": []},
    )
    assert contract.safe is False
    assert "target_concept_coverage" in contract.missing_slots


def test_current_state_uses_latest_matching_supersession_chain() -> None:
    question = "What book am I currently reading?"
    plan = plan_atomic_query(question)
    current_book = _fact(
        fact_id="current-book",
        object_text="The Seven Husbands of Evelyn Hugo",
    ).model_copy(
        update={
            "predicate": "currently_reading",
            "fact_kind": "state",
            "supersession_key": "user:current_activity:reading",
            "qualifiers": {"object_type": "book"},
        }
    )
    later_habit = _fact(
        fact_id="later-habit",
        object_text="the idea of making reading a habit loop",
    ).model_copy(
        update={
            "predicate": "prefers",
            "fact_kind": "state",
            "supersession_key": "user:preference:reading_habit",
            "observed_date": "2025-02-01",
            "citation": _fact().citation.model_copy(update={"turn_index": 1}),
        }
    )
    contract = validate_atomic_contract(
        plan,
        [current_book, later_habit],
        [current_book.fact_id, later_habit.fact_id],
        {"safe": True, "safety_reasons": []},
    )
    operation = evaluate_deterministic_operation(
        question,
        [current_book, later_habit],
        [current_book.fact_id, later_habit.fact_id],
        plan=plan,
        operand_fact_ids=contract.operand_fact_ids,
    )
    assert contract.safe is True
    assert contract.operand_fact_ids == [current_book.fact_id]
    assert operation.result == "The Seven Husbands of Evelyn Hugo"


def test_deterministic_operation_falls_back_without_normalized_operands() -> None:
    fact = _fact().model_copy(
        update={
            "quantity": AtomicQuantity(value=3, unit="items", role="purchase_count"),
            "qualifiers": {"atomic_origin": "deterministic_lossless"},
        }
    )
    result = evaluate_deterministic_operation(
        "What was the average?", [fact], [fact.fact_id]
    )
    assert result.requested is True
    assert result.resolved is False
    assert result.fallback_reason


def test_deterministic_operation_returns_typed_average_with_citations() -> None:
    first = _fact(fact_id="age-1").model_copy(
        update={
            "quantity": AtomicQuantity(value=60, unit="years", role="age"),
            "predicate": "has_age",
        }
    )
    second = _fact(fact_id="age-2").model_copy(
        update={
            "quantity": AtomicQuantity(value=70, unit="years", role="age"),
            "predicate": "has_age",
        }
    )
    result = evaluate_deterministic_operation(
        "What is their average age?", [first, second], ["age-1", "age-2"]
    )
    assert result.resolved is True
    assert result.operation == "average"
    assert result.result == "65 years"
    assert len(result.citation_labels) == 2


def test_async_semantic_import_keeps_lossless_facts(tmp_path: Path) -> None:
    session = _session()
    jobs_path = tmp_path / "jobs.jsonl"
    summary = export_semantic_normalization_jobs(
        [session], model="semantic-test", cache_dir=tmp_path, output_path=jobs_path
    )
    assert summary["exported_job_count"] == 1
    job = json.loads(jobs_path.read_text(encoding="utf-8"))
    job["response"] = {"sessions": [{"session_id": "s1", "facts": []}]}
    jobs_path.write_text(json.dumps(job) + "\n", encoding="utf-8")

    imported = import_semantic_normalization_results(
        jobs_path, model="semantic-test", cache_dir=tmp_path
    )
    facts, diagnostics = extract_atomic_memory(
        [session],
        model="semantic-test",
        cache_dir=tmp_path,
        extractor=lambda _prompt: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert imported["imported_session_count"] == 1
    assert diagnostics.cache_hit_count == 1
    assert {fact.citation.speaker for fact in facts} == {"user", "assistant"}


def test_compiler_types_general_closed_world_category_counts() -> None:
    session = {
        "session_id": "counts",
        "date": "2025-01-01",
        "turns": [
            {"role": "user", "content": "I watched three amateur comedians."},
            {"role": "user", "content": "I visited 4 different doctors."},
        ],
    }
    facts = deterministic_atomic_facts(session)
    typed = [
        fact
        for fact in facts
        if fact.quantity is not None
        and fact.qualifiers.get("atomic_origin") == "deterministic_lossless"
    ]

    assert [(fact.quantity.value, fact.quantity.unit) for fact in typed] == [
        (3, "comedian"),
        (4, "doctor"),
    ]
    assert all(fact.quantity.role == "declared_cardinality" for fact in typed)
    assert all(fact.qualifiers["closed_world_category"] == "true" for fact in typed)


def test_progressive_counter_requires_snapshot_then_materializes_increment() -> None:
    sessions = [
        {
            "session_id": "base",
            "date": "2025-01-01",
            "turns": [{"role": "user", "content": "I have 4 active projects."}],
        },
        {
            "session_id": "increment",
            "date": "2025-01-02",
            "turns": [{"role": "user", "content": "I started a new project."}],
        },
    ]
    source_facts = [
        fact for session in sessions for fact in deterministic_atomic_facts(session)
    ]
    materialized = materialize_progressive_counters(source_facts)
    derived = [
        fact
        for fact in materialized
        if fact.qualifiers.get("atomic_origin") == "deterministic_derived"
    ]

    assert len(derived) == 1
    assert derived[0].quantity == AtomicQuantity(
        value=5, unit="project", role="derived_current_total"
    )
    assert derived[0].supersession_key == "user:current_quantity:project"

    no_snapshot = deterministic_atomic_facts(sessions[1])
    assert materialize_progressive_counters(no_snapshot) == no_snapshot


def test_entity_membership_normalizes_titles_and_explicit_roles_without_closure() -> None:
    session = {
        "session_id": "entities",
        "date": "2025-02-01",
        "turns": [
            {
                "role": "user",
                "content": "I visited Dr. Lee. Morgan Hale is my physician.",
            }
        ],
    }
    facts = deterministic_atomic_facts(session)
    memberships = [fact for fact in facts if fact.predicate == "category_member"]

    assert {fact.qualifiers["canonical_entity_key"] for fact in memberships} == {
        "lee",
        "morgan_hale",
    }
    assert {fact.qualifiers["entity_category"] for fact in memberships} == {"doctor"}
    assert all(fact.qualifiers["closed_world_category"] == "false" for fact in memberships)
    assert plan_atomic_query(
        "How many physicians did I visit?"
    ).candidate_aliases == ["clinician", "doctor"]
