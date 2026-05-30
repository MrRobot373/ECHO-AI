from backend.pipeline.llm import pop_complete_sentences


def test_pop_complete_sentences_leaves_tail():
    sentences, tail = pop_complete_sentences("Hello there. Still speaking")
    assert sentences == ["Hello there."]
    assert tail == "Still speaking"

