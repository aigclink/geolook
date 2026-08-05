import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D


class ShutdownEndpointCase(unittest.TestCase):
    def handler(self, body):
        h = D.Handler.__new__(D.Handler)
        h.path = "/api/shutdown"
        h._body = mock.Mock(return_value=body)
        h._json = mock.Mock()
        h.server = mock.Mock()
        return h

    def test_requires_explicit_confirmation(self):
        h = self.handler({})
        h.do_POST()
        h._json.assert_called_once_with(
            {"ok": False, "error": "需要明確確認關閉伺服器"}, 400
        )
        h.server.shutdown.assert_not_called()

    def test_sends_response_before_starting_shutdown_thread(self):
        h = self.handler({"confirm": True})
        thread = mock.Mock()
        with mock.patch.object(D.threading, "Thread", return_value=thread) as make_thread:
            h.do_POST()
        h._json.assert_called_once_with(
            {"ok": True, "message": "GeoLook 伺服器正在關閉"}
        )
        make_thread.assert_called_once_with(target=h.server.shutdown, daemon=True)
        thread.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
