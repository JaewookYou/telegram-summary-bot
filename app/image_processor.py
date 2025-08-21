from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional
from PIL import Image
import easyocr

logger = logging.getLogger("app.image")


class ImageProcessor:
    def __init__(self):
        logger.info("EasyOCR 이미지 처리기 초기화 중...")
        try:
            # EasyOCR 리더 초기화 (한국어 + 영어)
            self.reader = easyocr.Reader(['ko', 'en'], gpu=False)
            logger.info("EasyOCR 초기화 완료")
        except Exception as e:
            logger.error(f"EasyOCR 초기화 실패: {e}")
            self.reader = None

    async def extract_text_from_image(self, image_data: bytes) -> Optional[str]:
        """이미지에서 텍스트 추출 (EasyOCR 사용)"""
        if not self.reader:
            logger.error("EasyOCR이 초기화되지 않음")
            return None
            
        if not image_data:
            logger.error("이미지 데이터가 비어있음")
            return None
            
        try:
            # 이미지 데이터를 BytesIO로 변환
            image_bytes = io.BytesIO(image_data)
            
            # 이미지 로드 및 검증
            try:
                image = Image.open(image_bytes)
                # 이미지가 실제로 로드되었는지 확인
                image.verify()
                # 이미지를 다시 열기 (verify 후에는 닫힘)
                image = Image.open(io.BytesIO(image_data))
                
                # 이미지 크기 확인 (너무 크면 리사이즈)
                if image.size[0] > 2000 or image.size[1] > 2000:
                    image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                    logger.info(f"이미지 리사이즈: {image.size}")
                    
            except Exception as img_error:
                logger.error(f"이미지 로드 실패: {img_error}")
                return None
            
            logger.info(f"이미지 처리: {image.format}, {image.size}, {image.mode}")
            
            # EasyOCR로 텍스트 추출
            results = await asyncio.get_event_loop().run_in_executor(
                None, 
                self.reader.readtext, 
                image
            )
            
            # 결과에서 텍스트 추출
            texts = []
            for (bbox, text, confidence) in results:
                if confidence > 0.5:  # 신뢰도 50% 이상만 사용
                    texts.append(text.strip())
                    logger.debug(f"텍스트 감지: '{text}' (신뢰도: {confidence:.2f})")
            
            if texts:
                full_text = ' '.join(texts)
                logger.info(f"이미지에서 텍스트 추출 성공: {len(full_text)}자, {len(texts)}개 텍스트 블록")
                return full_text
            else:
                logger.info("이미지에서 텍스트를 찾을 수 없음")
                return None
                
        except Exception as e:
            logger.error(f"이미지 텍스트 추출 실패: {e}")
            return None

    def analyze_image_content(self, text: str) -> dict:
        """추출된 텍스트를 분석하여 내용 요약"""
        if not text:
            return {
                "content_type": "image",
                "description": "텍스트가 없는 이미지",
                "summary": "이미지 파일"
            }
        
        # 간단한 키워드 기반 분석
        keywords = {
            "가격": ["가격", "price", "cost", "원", "$", "₩"],
            "차트": ["차트", "chart", "그래프", "graph", "candle"],
            "뉴스": ["뉴스", "news", "발표", "announcement"],
            "이벤트": ["이벤트", "event", "프로모션", "promotion"],
            "코인": ["코인", "coin", "토큰", "token", "btc", "eth"],
            "거래": ["거래", "trade", "매수", "매도", "buy", "sell"]
        }
        
        found_keywords = []
        for category, words in keywords.items():
            for word in words:
                if word.lower() in text.lower():
                    found_keywords.append(category)
                    break
        
        if found_keywords:
            content_type = "image_with_text"
            description = f"텍스트 포함 이미지 ({', '.join(found_keywords)})"
            summary = f"이미지에 {', '.join(found_keywords)} 관련 텍스트가 포함되어 있습니다."
        else:
            content_type = "image_with_text"
            description = "텍스트 포함 이미지"
            summary = f"이미지에서 '{text[:50]}{'...' if len(text) > 50 else ''}' 텍스트를 추출했습니다."
        
        return {
            "content_type": content_type,
            "description": description,
            "summary": summary,
            "extracted_text": text
        }
