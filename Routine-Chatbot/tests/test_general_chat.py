import importlib
import os


def test_general_chat_uses_gemini_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    import chatbot

    importlib.reload(chatbot)

    captured = {}

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "I’m doing well, thank you!"}]}}
                ]
            }

    def fake_post(url, json, timeout):
        captured["url"] = url
        return MockResponse()

    monkeypatch.setattr(chatbot.requests, "post", fake_post)

    bot = chatbot.RoutineChatbot()
    response = bot.respond("how are you")

    assert "doing well" in response.lower()
    assert "generativelanguage.googleapis.com" in captured["url"]


def test_general_chat_handles_any_non_routine_question(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Paris is the capital of France."}]}}
                ]
            }

    def fake_post(url, json, timeout):
        return MockResponse()

    monkeypatch.setattr(chatbot.requests, "post", fake_post)

    response = chatbot.RoutineChatbot().respond("what is the capital of france")

    assert "paris" in response.lower()
    assert "capital" in response.lower()


def test_chatbot_uses_llm_to_recall_memories_about_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    captured = {}

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "I remember that you prefer morning meetings."}]}}
                ]
            }

    def fake_post(url, json, timeout):
        captured["payload"] = json
        return MockResponse()

    monkeypatch.setattr(chatbot.requests, "post", fake_post)

    bot = chatbot.RoutineChatbot(knowledge_base_path="knowledge_store.json")
    bot.knowledge_base.add_fact("I prefer morning meetings")
    response = bot.respond("what do you remember about me?")

    assert "remember" in response.lower()
    assert "morning" in response.lower()
    assert "I prefer morning meetings" in captured["payload"]["contents"][0]["parts"][0]["text"]


def test_memory_classifier_uses_llm_for_category_detection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    from knowledge_base import UserKnowledgeBase

    captured = {}

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [{
                    "content": {"parts": [{"text": '{"category": "preferences", "fact": "I prefer morning meetings."}' }]}
                }]
            }

    def fake_post(url, json, timeout):
        captured["called"] = True
        return MockResponse()

    monkeypatch.setattr("requests.post", fake_post)

    kb = UserKnowledgeBase(path=str(tmp_path / "memory.json"))
    saved = kb.remember_from_text("I prefer morning meetings.")

    assert saved
    assert kb.get_memory_by_category()["preferences"]
    assert captured["called"] is True


def test_chatbot_remembers_preferences_in_knowledge_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Noted. I will keep that preference in mind."}]}}
                ]
            }

    def fake_post(url, json, timeout):
        return MockResponse()

    monkeypatch.setattr(chatbot.requests, "post", fake_post)

    bot = chatbot.RoutineChatbot(knowledge_base_path="knowledge_store.json")
    bot.respond("Remember I prefer meetings in the morning and I like to keep my routine simple.")

    facts = bot.knowledge_base.get_facts()
    assert any("prefer meetings" in fact["fact"].lower() or "routine simple" in fact["fact"].lower() for fact in facts)


def test_chatbot_uses_live_supported_gemini_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    class ModelsResponse:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                ]
            }

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "I’ll draft a polished reply for that meeting request."}]}}
                ]
            }

    captured = {}

    def fake_get(url, timeout):
        captured["get_url"] = url
        return ModelsResponse()

    def fake_post(url, json, timeout):
        captured["post_url"] = url
        return MockResponse()

    monkeypatch.setattr(chatbot.requests, "get", fake_get)
    monkeypatch.setattr(chatbot.requests, "post", fake_post)

    bot = chatbot.RoutineChatbot()
    response = bot.respond("Can we meet at 8pm this evening?")

    assert "meeting request" in response.lower() or "polished reply" in response.lower()
    assert "gemini-3.6-flash" in captured["post_url"]


def test_pending_email_does_not_block_new_unrelated_questions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Paris is the capital of France."}]}}
                ]
            }

    monkeypatch.setattr(chatbot.requests, "post", lambda url, json, timeout: MockResponse())

    bot = chatbot.RoutineChatbot()
    bot.pending_email = {
        "to_email": "test@example.com",
        "subject": "Meeting request",
        "body": "Draft body",
    }

    response = bot.respond("what is the capital of france")

    assert "paris" in response.lower()
    assert "capital" in response.lower()
    assert bot.pending_email is None


def test_chatbot_uses_actual_email_and_user_context_for_email_drafts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import chatbot
    importlib.reload(chatbot)

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "I can help with that."}]}}
                ]
            }

    monkeypatch.setattr(chatbot.requests, "post", lambda url, json, timeout: MockResponse())

    bot = chatbot.RoutineChatbot()
    response = bot.respond("send email to janedoe@company.com asking her to review the quarterly budget and confirm availability before Friday")

    assert "janedoe@company.com" in response
    assert "quarterly budget" in response.lower()
    assert "Friday" in response
    assert "confirm" in response.lower()
