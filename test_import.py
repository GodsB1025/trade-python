#!/usr/bin/env python3
"""
langchain_voyageai import 테스트 스크립트
"""

try:
    from langchain_voyageai import VoyageAIEmbeddings
    print("✅ langchain_voyageai import 성공!")
    print(f"VoyageAIEmbeddings 클래스: {VoyageAIEmbeddings}")
except ImportError as e:
    print(f"❌ Import 오류: {e}")
except Exception as e:
    print(f"❌ 기타 오류: {e}")

# FastAPI 앱도 테스트
try:
    from app.main import app
    print("✅ FastAPI 앱 import 성공!")
except ImportError as e:
    print(f"❌ FastAPI 앱 import 오류: {e}")
except Exception as e:
    print(f"❌ FastAPI 앱 기타 오류: {e}")
