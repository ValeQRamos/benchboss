import asyncio

from benchboss.config import Config
from benchboss.ui.app import Benchboss


def test_app_boots_and_navigates_in_demo_mode():
    async def scenario():
        app = Benchboss(Config(), demo=True)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(2)
            assert app.current == "dash"
            await pilot.press("w")
            await pilot.pause(2)
            assert app.query_one("#actions").has_class("visible")
            await pilot.click("#apply")
            await pilot.pause(1)
            await pilot.press("f")
            await pilot.pause(2)
            assert app.current == "trash"
    asyncio.run(scenario())
