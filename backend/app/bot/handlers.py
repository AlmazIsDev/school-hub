from ..modules.users import service
from . import codes


def register(dp):
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
