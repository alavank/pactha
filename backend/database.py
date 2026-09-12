from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    # O servidor pode fechar conexoes ociosas -> sem pre_ping o pool entrega
    # conexao morta ("connection is closed"). pre_ping valida/reconecta antes de usar;
    # recycle descarta conexoes velhas. Essencial p/ ambientes com pouco trafego.
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
