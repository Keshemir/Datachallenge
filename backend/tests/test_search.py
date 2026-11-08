from cqa.storage import Store


def test_search_covers_late_messages_and_hidden_preview(tmp_path, conversation):
    store = Store(tmp_path / "search.sqlite3")
    store.initialize()
    conversation.transcript[0].text = "Начало обращения " * 30
    conversation.transcript[-1].text = "Уникальная фраза в конце разговора"
    digest = store.save_conversations([conversation])[0]
    result = store.list_conversations("ФРАЗА В КОНЦЕ")
    assert [r["hash"] for r in result] == [digest]
    assert "Уникальная" not in result[0]["preview"]
    assert store.list_conversations("нет такого текста") == []
    assert store.list_conversations(conversation.conversation_id)[0]["hash"] == digest
