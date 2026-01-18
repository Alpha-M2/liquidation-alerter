from functools import lru_cache
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.eth import AsyncEth

from app.config import get_settings


class Web3Provider:
    _instance: AsyncWeb3 | None = None

    @classmethod
    def get_web3(cls) -> AsyncWeb3:
        if cls._instance is None:
            settings = get_settings()
            cls._instance = AsyncWeb3(
                AsyncHTTPProvider(settings.rpc_url),
                modules={"eth": (AsyncEth,)},
            )
        return cls._instance

    @classmethod
    async def is_connected(cls) -> bool:
        web3 = cls.get_web3()
        return await web3.is_connected()


@lru_cache
def get_web3() -> AsyncWeb3:
    return Web3Provider.get_web3()
