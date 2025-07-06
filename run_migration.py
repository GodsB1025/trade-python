import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()


async def run_migration():
    try:
        conn = await asyncpg.connect(
            host=os.getenv("DATABASE_HOST", "localhost"),
            port=int(os.getenv("DATABASE_PORT", 5432)),
            user=os.getenv("DATABASE_USER", "postgres"),
            password=os.getenv("DATABASE_PASSWORD"),
            database=os.getenv("DATABASE_NAME", "trade_platform"),
        )

        print("트리거 함수 수정 마이그레이션 시작...")

        # 마이그레이션 파일 읽기
        with open("migration_fix_trigger_functions.sql", "r", encoding="utf-8") as f:
            migration_sql = f.read()

        # SQL 실행
        await conn.execute(migration_sql)

        print("마이그레이션 완료!")

        # 트리거 상태 확인
        trigger_query = """
        SELECT trigger_name, event_manipulation, action_statement
        FROM information_schema.triggers 
        WHERE event_object_table = 'chat_messages'
        """

        triggers = await conn.fetch(trigger_query)
        print("\n=== 현재 트리거 상태 ===")
        for trigger in triggers:
            print(f'- {trigger["trigger_name"]}: {trigger["event_manipulation"]}')

        await conn.close()

    except Exception as e:
        print(f"마이그레이션 실행 중 오류: {e}")


if __name__ == "__main__":
    asyncio.run(run_migration())
