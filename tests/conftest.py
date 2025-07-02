"""
Pytest 공용 Fixture 설정 파일 (Mock 기반)
"""
from unittest.mock import MagicMock
import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

# 테스트 실행 시 프로젝트 루트를 sys.path에 추가하여 모듈 임포트 문제를 해결
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..')))

# --- 환경 변수 설정 ---


@pytest.fixture(scope="session", autouse=True)
def settings_override():
    """테스트 환경 변수 설정"""
    os.environ["ENVIRONMENT"] = "test"
    os.environ["ANTHROPIC_API_KEY"] = "test_key"
    os.environ["VOYAGE_API_KEY"] = "test_key"

# --- Mock 기반 DB 세션 ---


@pytest.fixture
def mock_db_session():
    """Mock 기반 데이터베이스 세션"""
    session = AsyncMock(spec=AsyncSession)

    # 기본 메서드들을 AsyncMock으로 설정
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    return session


# 서비스 테스트에서 필요한 최소한의 외부 라이브러리만 Mock 처리
# (실제 서비스 클래스와 LangChain 메시지 클래스는 유지)
essential_mock_modules = [
    'langchain_voyageai',
    'langchain_postgres.vectorstores'
]

for module_name in essential_mock_modules:
    sys.modules[module_name] = MagicMock()
