import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from dgt.api import EventApi
from mainloop import MainLoop
from server import ChannelHandler
from uci.rating import Rating


class TestServerSetPlayer(unittest.IsolatedAsyncioTestCase):
    async def _post(self, **arguments):
        handler = Mock()
        handler.shared = {}
        arguments = {"action": "set_player", **arguments}
        handler.get_argument.side_effect = lambda name, default=None: arguments.get(name, default)
        with (
            patch("server._require_auth_if_remote", return_value=True),
            patch("server.write_picochess_ini") as write_ini,
            patch("server.EventHandler.write_to_clients"),
            patch("server.Observable.fire", new_callable=AsyncMock) as fire,
        ):
            await ChannelHandler.post(handler)
        return handler, write_ini, fire

    async def test_set_player_informs_backend(self):
        handler, write_ini, fire = await self._post(name="Edu", elo="1700")

        write_ini.assert_any_call("pgn-user", "Edu")
        write_ini.assert_any_call("pgn-elo", "1700")
        fire.assert_awaited_once()
        event = fire.await_args.args[0]
        self.assertEqual(EventApi.SET_PLAYER, repr(event))
        self.assertEqual(("Edu", "1700"), (event.name, event.elo))
        self.assertEqual("1700", handler.shared["system_info"]["user_elo"])

    async def test_rating_only(self):
        _, _, fire = await self._post(elo="1650")
        event = fire.await_args.args[0]
        self.assertEqual(("", "1650"), (event.name, event.elo))

    async def test_nothing_to_change_fires_nothing(self):
        _, _, fire = await self._post()
        fire.assert_not_awaited()


class TestMainLoopSetPlayer(unittest.IsolatedAsyncioTestCase):
    def _controller(self, rating_deviation="350"):
        controller = object.__new__(MainLoop)
        controller.args = SimpleNamespace(pgn_user="Player", pgn_elo="1500", rating_deviation=rating_deviation)
        controller.state = SimpleNamespace(rating=Rating(1500.0, 350.0), interaction_mode=None)
        return controller

    def test_set_player_updates_running_values(self):
        controller = self._controller()
        controller.set_player("Edu", "1700")

        self.assertEqual("Edu", controller.args.pgn_user)
        self.assertEqual("1700", controller.args.pgn_elo)
        self.assertEqual(1700, int(controller.state.rating.rating))
        self.assertEqual(350, int(controller.state.rating.rating_deviation))

    def test_empty_values_keep_current_ones(self):
        controller = self._controller()
        controller.set_player("", "1700")
        self.assertEqual("Player", controller.args.pgn_user)
        controller.set_player("Edu", "")
        self.assertEqual("1700", controller.args.pgn_elo)

    def test_without_rating_deviation_rating_is_untouched(self):
        controller = self._controller(rating_deviation="")
        controller.set_player("", "1800")
        self.assertEqual("1800", controller.args.pgn_elo)
        self.assertEqual(1500, int(controller.state.rating.rating))

    async def test_engine_change_shows_new_rating(self):
        from dgt.util import Mode

        controller = self._controller()
        controller.state.interaction_mode = Mode.NORMAL
        controller.engine = SimpleNamespace(is_adaptive=False, engine_rating=2200)
        controller.emulation_mode = lambda: False
        controller.set_player("", "1700")
        with patch("mainloop.DisplayMsg.show", new_callable=AsyncMock) as show:
            await controller.update_elo_display()
        message = show.await_args.args[0]
        self.assertEqual("1700", message.info["user_elo"])


if __name__ == "__main__":
    unittest.main()
