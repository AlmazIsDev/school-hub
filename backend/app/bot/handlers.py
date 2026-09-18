from ..modules.users import service
from . import bridge_bot, builder_bot, codes, duty_bot, pulse_bot


def register(dp):
    @dp.on(r"^/?(?:help|помощь|команды)$")
    async def help(event, vk):
        await vk.call(
            "messages.send",
            peer_id=event["peer_id"],
            random_id=0,
            message="Команды:\n"
            "старт — начать работу\n"
            "код <6 цифр> — привязать аккаунт с сайта\n"
            "стать помощником — зарегистрироваться в bridge\n"
            "нужна помощь — подобрать помощника\n"
            "закончить — закрыть активную пару (только в паре)\n"
            "пожаловаться — жалоба на напарника (только в паре)\n"
            "дежурство — ближайший слот дежурства\n"
            "квест — пройти квест своего класса\n"
            "отмена — прервать текущий сценарий\n"
            "help — этот список\n\n"
            "Код для привязки берётся в профиле на сайте.",
        )

    @dp.on(r"^старт$")
    async def start(event, vk):
        await vk.call(
            "messages.send",
            peer_id=event["peer_id"],
            random_id=0,
            message="Привет! Отправь «код <число>» с сайта, чтобы привязать аккаунт. "
            "Код можно взять в профиле на сайте.",
        )

    @dp.on(r"^код (\d{6})$")
    async def bind(event, vk):
        user_id = await codes.consume_code(event["match"].group(1))
        if not user_id:
            await vk.call(
                "messages.send",
                peer_id=event["peer_id"],
                random_id=0,
                message="Код не найден или истёк. Возьми новый на сайте.",
            )
            return
        u = await service.by_id(user_id)
        if not u:
            await vk.call(
                "messages.send",
                peer_id=event["peer_id"],
                random_id=0,
                message="Пользователь не найден. Возьми новый код на сайте.",
            )
            return
        u.vk_id = event["vk_user_id"]
        await u.save()
        await vk.call(
            "messages.send",
            peer_id=event["peer_id"],
            random_id=0,
            message=f"Готово, {u.full_name}! Аккаунт привязан.",
        )

    @dp.on(r"^/?(?:стать помощником|помощник)$")
    async def become_helper(event, vk):
        await bridge_bot.start_become_helper(event, vk)

    @dp.on(r"^нужна помощь$")
    async def need_help(event, vk):
        await bridge_bot.start_need_help(event, vk)

    @dp.on(r"^закончить$")
    async def finish(event, vk):
        await bridge_bot.finish_pair(event, vk)

    @dp.on(r"^пожаловаться$")
    async def complain(event, vk):
        await bridge_bot.start_report(event, vk)

    @dp.on(r"^отмена$")
    async def cancel(event, vk):
        deleted = await bridge_bot._r().delete(bridge_bot._state_key(event["vk_user_id"]))
        if deleted:
            await vk.call("messages.send", peer_id=event["peer_id"], random_id=0,
                          message="Отменено.")

    @dp.on(r"^/?(?:дежурство|деж)$")
    async def duty(event, vk):
        await duty_bot.handle_duty(event, vk)

    @dp.on(r"^/?(?:квест|квесты)$")
    async def quest(event, vk):
        await builder_bot.handle_quest(event, vk)

    # catch-all последним: кнопки опроса и bridge-сценариев (payload),
    # свободные ответы. Сценарии взаимоисключающие (разные state-ключи):
    # pulse смотрит pollstate, bridge — bridgestate и активные пары.
    @dp.on(r"")
    async def poll_step(event, vk):
        await pulse_bot.handle_message(event, vk)
        await bridge_bot.handle_message(event, vk)
        await duty_bot.handle_message(event, vk)
        await builder_bot.handle_message(event, vk)
