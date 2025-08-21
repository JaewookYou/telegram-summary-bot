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
            payload = {
                "input": text,
                "model": "solar-embedding-1-large"  # Upstage의 임베딩 모델
            }
            
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
            
            response.raise_for_status()
            data = response.json()
            
            if "data" in data and len(data["data"]) > 0:
                embedding = data["data"][0]["embedding"]
                logger.debug(f"임베딩 생성 성공: {len(embedding)}차원 벡터")
                return embedding
            else:
                logger.error(f"임베딩 응답 형식 오류: {data}")
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
