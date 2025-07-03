from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# DATABASE_URL을 비동기 드라이버로 변환
async_database_url = str(settings.DATABASE_URL).replace(
    "postgresql://", "postgresql+asyncpg://")

# 비동기 엔진 생성
# echo=True는 개발 시 SQL 쿼리를 로깅하기 위함이며, 프로덕션에서는 False로 설정하는 것이 좋음
engine = create_async_engine(async_database_url, echo=True)

# 비동기 세션 팩토리 생성
# expire_on_commit=False는 세션이 커밋된 후에도 ORM 객체에 접근할 수 있도록 함
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession
)


async def get_db() -> AsyncSession:
    """
    FastAPI 의존성 주입을 위한 비동기 데이터베이스 세션 제너레이터.

    요청이 시작될 때 세션을 생성하고, 요청 처리가 성공적으로 완료되면
    트랜잭션을 커밋합니다. 예외가 발생하면 롤백을 수행합니다.
    요청의 성공 여부와 관계없이 세션은 항상 닫힙니다.
    """
    async_session = SessionLocal()
    try:
        yield async_session
        await async_session.commit()
    except Exception:
        await async_session.rollback()
        raise
    finally:
        await async_session.close()
