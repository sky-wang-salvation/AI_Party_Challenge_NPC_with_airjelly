from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from ktv_backend.modules.config import ServerConfig
from ktv_backend.modules.llm import KtvLlmClient, OpenAIResponsesClient
from ktv_backend.modules.orchestrator import KtvBrain
from ktv_backend.modules.protocol import parse_client_message


class ProtocolTests(unittest.TestCase):
    def test_parse_user_signal_from_payload(self) -> None:
        message = parse_client_message(
            """
            {
              "type": "user_signal",
              "session_id": "booth-a",
              "payload": {
                "pose_label": "arms_up",
                "touch_event": "give_me_5",
                "song": {
                  "title": "Go"
                }
              }
            }
            """,
            "fallback-session",
        )
        self.assertEqual(message.message_type, "user_signal")
        self.assertEqual(message.signal.session_id, "booth-a")
        self.assertEqual(message.signal.touch_event, "give_me_5")
        self.assertEqual(message.signal.song.title, "Go")

    def test_parse_song_context(self) -> None:
        message = parse_client_message(
            """
            {
              "type": "song_context",
              "payload": {
                "song": {
                  "title": "Sunny Day",
                  "artist": "Jay"
                }
              }
            }
            """,
            "fallback-session",
        )
        self.assertEqual(message.message_type, "song_context")
        self.assertEqual(message.song.title, "Sunny Day")


class BrainTests(unittest.TestCase):
    def test_rule_response_for_touch_event(self) -> None:
        config = ServerConfig()
        brain = KtvBrain(config)
        message = parse_client_message(
            """
            {
              "type": "user_signal",
              "session_id": "booth-a",
              "payload": {
                "touch_event": "heart",
                "song": {
                  "title": "Sweet Song"
                }
              }
            }
            """,
            "fallback-session",
        )

        result = asyncio.run(brain.process_signal(message.signal))
        self.assertEqual(result.action, "heart_pose")
        self.assertEqual(result.expression, "love")
        self.assertTrue(result.reply_text)

    def test_rule_response_for_high_energy_song(self) -> None:
        config = ServerConfig()
        brain = KtvBrain(config)
        message = parse_client_message(
            """
            {
              "type": "user_signal",
              "session_id": "booth-a",
              "payload": {
                "song": {
                  "title": "Fire Run"
                }
              }
            }
            """,
            "fallback-session",
        )

        result = asyncio.run(brain.process_signal(message.signal))
        self.assertIn(result.action, {"dance_fast", "dance_groove"})
        self.assertTrue(result.reply_text)


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def close(self):
        return None


class LlmClientTests(unittest.TestCase):
    def test_auto_provider_prefers_openai_when_key_exists(self) -> None:
        config = ServerConfig(openai_api_key="openai-key", step_api_key="step-key")
        client = KtvLlmClient(config)
        self.assertEqual(client.provider_name, "openai")

    def test_auto_provider_falls_back_to_stepfun(self) -> None:
        config = ServerConfig(step_api_key="step-key")
        client = KtvLlmClient(config)
        self.assertEqual(client.provider_name, "stepfun")

    def test_openai_client_parses_structured_output(self) -> None:
        config = ServerConfig(
            llm_provider="openai",
            openai_api_key="openai-key",
            openai_model="gpt-5.4-mini",
        )
        client = OpenAIResponsesClient(config)
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"reply":"跟上节奏，我们一起冲。","action":"dance_fast","expression":"excited"}',
                        }
                    ],
                }
            ]
        }

        with patch(
            "ktv_backend.modules.llm.urlopen",
            return_value=FakeHttpResponse(json_bytes(payload)),
        ):
            directive = asyncio.run(client.generate_directive("system", "user"))

        self.assertEqual(directive.action, "dance_fast")
        self.assertEqual(directive.expression, "excited")
        self.assertIn("跟上节奏", directive.reply_text)


def json_bytes(payload) -> bytes:
    import json

    return json.dumps(payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
