from app.bot.dispatcher import Dispatcher


async def test_dispatch_by_regex():
    dp = Dispatcher()
    seen = {}

    @dp.on(r"^код (\d+)$")
    async def h(event, vk):
        seen["code"] = event["match"].group(1)

    await dp.dispatch({"text": "код 1234", "vk_user_id": 5})
    assert seen["code"] == "1234"


async def test_dispatch_no_match_is_silent():
    dp = Dispatcher()
    called = []

    @dp.on(r"^старт$")
    async def h(event, vk):
        called.append(1)

    await dp.dispatch({"text": "привет"})
    assert not called


async def test_handler_error_does_not_propagate():
    dp = Dispatcher()

    @dp.on(r"^бум$")
    async def boom(event, vk):
        raise RuntimeError("boom")

    await dp.dispatch({"text": "бум"})  # не должно кидать
