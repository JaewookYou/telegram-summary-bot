from __future__ import annotations

import asyncio
import logging
import numpy as np
from typing import List, Optional
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("app.embedding")


class UpstageEmbeddingClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.upstage.ai/v1/embeddings"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """텍스트의 임베딩 벡터를 가져옵니다."""
        try:
            # 텍스트가 비어있거나 너무 짧은 경우 처리
            if not text or len(text.strip()) < 3:
                logger.warning(f"텍스트가 너무 짧음: '{text}'")
                return None
            
            # 텍스트 길이 제한 (API 제한 고려)
            if len(text) > 8000:
                text = text[:8000]
                logger.warning(f"텍스트가 너무 길어서 잘림: {len(text)}자")
            
            payload = {
                "input": text.strip(),
                "model": "embedding-query"  # Upstage.ai 지원 모델명
            }
            
            logger.debug(f"임베딩 요청: 모델={payload['model']}, 텍스트 길이={len(text)}")
            
            # 비동기로 requests 실행
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: requests.post(
                    self.base_url, 
                    json=payload, 
                    headers=self.headers,
                    timeout=30
                )
            )
            
            # 응답 상태 코드 확인
            if response.status_code == 400:
                logger.error(f"API 요청 형식 오류: {response.text}")
                logger.error(f"요청 페이로드: {payload}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if "data" in data and len(data["data"]) > 0:
                embedding = data["data"][0]["embedding"]
                logger.debug(f"임베딩 생성 성공: {len(embedding)}차원 벡터")
                return embedding
            else:
                logger.error(f"임베딩 응답 형식 오류: {data}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"API 요청 실패: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"응답 내용: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"임베딩 생성 실패: {e}")
            return None
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """두 벡터 간의 코사인 유사도를 계산합니다."""
        try:
            vec1_array = np.array(vec1)
            vec2_array = np.array(vec2)
            
            # 정규화
            norm1 = np.linalg.norm(vec1_array)
            norm2 = np.linalg.norm(vec2_array)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            # 코사인 유사도 계산
            similarity = np.dot(vec1_array, vec2_array) / (norm1 * norm2)
            return float(similarity)
            
        except Exception as e:
            logger.error(f"코사인 유사도 계산 실패: {e}")
            return 0.0
    
    def is_similar(self, vec1: List[float], vec2: List[float], threshold: float = 0.85) -> bool:
        """두 임베딩 벡터가 유사한지 판단합니다."""
        similarity = self.cosine_similarity(vec1, vec2)
        return similarity >= threshold
    
    async def test_connection(self) -> bool:
        """API 연결 및 인증을 테스트합니다."""
        try:
            test_text = "Hello, world!"
            result = await self.get_embedding(test_text)
            if result:
                logger.info("Upstage.ai API 연결 성공")
                return True
            else:
                logger.error("Upstage.ai API 연결 실패")
                return False
        except Exception as e:
            logger.error(f"API 연결 테스트 실패: {e}")
            return False
