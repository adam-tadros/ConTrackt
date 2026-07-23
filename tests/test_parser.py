import parser as ai_parser


def test_plain_json():
    text = '{"vendor": "Acme", "value": 1500, "end": "2025-01-01"}'
    out = ai_parser.map_model_text(text)
    assert out["vendor"] == "Acme"
    assert out["value"] == 1500
    assert out["end"] == "2025-01-01"


def test_json_in_code_fence():
    text = 'Here you go:\n```json\n{"vendor": "Beta", "addl": "Yes"}\n```\nthanks'
    out = ai_parser.map_model_text(text)
    assert out["vendor"] == "Beta"
    assert out["addl"] == "Yes"


def test_value_string_coerced_to_number():
    out = ai_parser.map_model_text('{"value": "$1,250.50"}')
    assert out["value"] == 1250.5


def test_null_like_values_become_none():
    out = ai_parser.map_model_text('{"vendor": "N/A", "po": "", "cat": "null"}')
    assert out["vendor"] is None
    assert out["po"] is None
    assert out["cat"] is None


def test_garbage_returns_blank_fields():
    out = ai_parser.map_model_text("the model refused to answer")
    assert set(out.keys()) == set(ai_parser.EXTRACT_KEYS)
    assert all(v is None for v in out.values())


def test_empty_input():
    out = ai_parser.map_model_text("")
    assert all(v is None for v in out.values())


def test_all_keys_present():
    out = ai_parser.map_model_text('{"vendor": "X"}')
    for k in ai_parser.EXTRACT_KEYS:
        assert k in out
