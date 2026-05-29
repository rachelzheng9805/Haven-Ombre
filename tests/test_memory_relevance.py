from memory_relevance import (
    active_facets,
    facets_for_node,
    facets_for_text,
    memory_relevance_options_from_config,
    relevance_decision,
)


def test_ai_relationship_query_is_identity_not_intimacy():
    facets = facets_for_text("人机恋 / AI relationship")

    assert facets["relationship_identity"] > 0
    assert facets.get("intimacy", 0) == 0


def test_identity_query_suppresses_intimacy_candidate():
    decision = relevance_decision(
        "AI relationship",
        {
            "content": "A private sexual intimacy memory.",
            "metadata": {"importance": 10},
        },
    )

    assert decision.suppress


def test_non_sensitive_conflict_with_direct_evidence_is_demoted_not_suppressed():
    decision = relevance_decision(
        "给客户发邮件 email",
        {
            "content": "客户 hardware protocol note that mentions sending email to vendor.",
            "metadata": {"tags": ["hardware_protocol"], "importance": 10},
        },
    )

    assert not decision.suppress
    assert 0 < decision.multiplier < 1
    assert "communication_action_vs_hardware_protocol_demoted" in decision.reasons


def test_explicit_intimacy_query_allows_intimacy_candidate():
    decision = relevance_decision(
        "亲密身体",
        {
            "content": "A private intimacy memory about body closeness.",
            "metadata": {"importance": 10},
        },
    )

    assert not decision.suppress
    assert decision.multiplier > 1


def test_config_aliases_blocked_facets_and_section_hints_extend_defaults():
    options = memory_relevance_options_from_config(
        {
            "memory_relevance": {
                "aliases": {"communication_action": ["工单回复"]},
                "blocked_facets": ["intimacy"],
                "section_hints": {"protocol_note": ["hardware_protocol"]},
            }
        }
    )

    query_facets = facets_for_text("工单回复", options)
    node_facets = facets_for_node({"section": "protocol_note", "text": ""}, options)

    assert "communication_action" in active_facets(query_facets)
    assert "hardware_protocol" in active_facets(node_facets)
    assert facets_for_text("亲密", options).get("intimacy", 0) == 0
