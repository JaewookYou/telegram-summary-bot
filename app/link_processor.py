from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from playwright.async_api import async_playwright
import base64

logger = logging.getLogger("app.link")


class LinkProcessor:
    def __init__(self, *, request_timeout_sec: int = 12, render_wait_ms: int = 2000, max_content_len: int = 1000, enable_screenshot: bool = False):
        self.request_timeout_sec = request_timeout_sec
        self.render_wait_ms = render_wait_ms
        self.max_content_len = max_content_len
        self.enable_screenshot = enable_screenshot
    
    def extract_links_from_text(self, text: str) -> list[str]:
        """텍스트에서 링크 추출"""
        # URL 패턴 매칭
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        urls = re.findall(url_pattern, text)
        
        # www로 시작하는 URL을 https://로 변환
        processed_urls = []
        for url in urls:
            if url.startswith('www.'):
                url = 'https://' + url
            processed_urls.append(url)
        
        return processed_urls
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=3, max=10))
    async def fetch_webpage_content(self, url: str) -> Optional[Dict[str, Any]]:
        """Playwright로 렌더링하여 웹페이지 메타/본문 추출"""
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    )
                )
                page = await context.new_page()
                await page.goto(url, timeout=self.request_timeout_sec * 1000)
                # 네트워크/DOM 안정화 대기
                await page.wait_for_timeout(self.render_wait_ms)

                html = await page.content()
                screenshot_b64: Optional[str] = None
                if self.enable_screenshot:
                    try:
                        img_bytes = await page.screenshot(full_page=True, type='png')
                        screenshot_b64 = base64.b64encode(img_bytes).decode('ascii')
                    except Exception:
                        screenshot_b64 = None
                soup = BeautifulSoup(html, 'html.parser')

                # 메타 태그 추출
                title_el = soup.find('title')
                title_text = title_el.get_text().strip() if title_el else ""
                og_title = soup.find('meta', property='og:title')
                og_description = soup.find('meta', property='og:description')
                og_image = soup.find('meta', property='og:image')
                meta_description = soup.find('meta', attrs={'name': 'description'})

                # 본문 텍스트 추출 (불필요 태그 제거)
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    tag.decompose()

                main_content = ""
                for selector in ['main', 'article', '.content', '.post', '.entry']:
                    content = soup.select_one(selector)
                    if content:
                        main_content = content.get_text(separator=' ', strip=True)
                        break
                if not main_content:
                    body = soup.find('body')
                    if body:
                        main_content = body.get_text(separator=' ', strip=True)

                main_content = re.sub(r'\s+', ' ', main_content).strip()

                await context.close()
                await browser.close()

                result = {
                    "url": url,
                    "title": og_title.get('content', '') if og_title else title_text,
                    "description": og_description.get('content', '') if og_description else (meta_description.get('content', '') if meta_description else ""),
                    "image": og_image.get('content', '') if og_image else "",
                    "content": main_content[: self.max_content_len],
                    "domain": urlparse(url).netloc,
                }
                if screenshot_b64:
                    result["screenshot_b64"] = screenshot_b64
                return result
        except Exception as e:
            logger.error(f"웹페이지 가져오기 실패 ({url}): {e}")
            return None
    
    def analyze_link_content(self, webpage_data: Dict[str, Any]) -> Dict[str, Any]:
        """웹페이지 내용 분석"""
        if not webpage_data:
            return {
                "content_type": "link",
                "description": "링크 (내용 가져오기 실패)",
                "summary": "웹페이지 링크"
            }
        
        title = webpage_data.get("title", "")
        description = webpage_data.get("description", "")
        content = webpage_data.get("content", "")
        domain = webpage_data.get("domain", "")
        
        # 도메인 기반 카테고리 분류
        domain_keywords = {
            "뉴스": ["news", "media", "press", "coindesk", "cointelegraph"],
            "거래소": ["binance", "upbit", "bithumb", "coinbase", "exchange"],
            "블로그": ["blog", "medium", "substack", "mirror"],
            "소셜": ["twitter", "x.com", "telegram", "discord"],
            "기술": ["github", "docs", "technical", "whitepaper"]
        }
        
        found_categories = []
        for category, keywords in domain_keywords.items():
            for keyword in keywords:
                if keyword.lower() in domain.lower():
                    found_categories.append(category)
                    break
        
        # 내용 기반 키워드 분석
        content_keywords = {
            "가격": ["가격", "price", "cost", "원", "$", "₩", "market cap"],
            "차트": ["차트", "chart", "그래프", "graph", "candle", "technical"],
            "뉴스": ["뉴스", "news", "발표", "announcement", "update"],
            "이벤트": ["이벤트", "event", "프로모션", "promotion", "airdrop"],
            "코인": ["코인", "coin", "토큰", "token", "btc", "eth", "crypto"],
            "거래": ["거래", "trade", "매수", "매도", "buy", "sell", "trading"]
        }
        
        all_text = f"{title} {description} {content}".lower()
        found_keywords = []
        for category, words in content_keywords.items():
            for word in words:
                if word.lower() in all_text:
                    found_keywords.append(category)
                    break
        
        # 요약 생성
        if title:
            summary = f"제목: {title}"
            if description:
                summary += f"\n설명: {description[:100]}{'...' if len(description) > 100 else ''}"
        else:
            summary = f"웹페이지 링크 ({domain})"
        
        return {
            "content_type": "link_with_content",
            "description": f"링크 ({', '.join(found_categories + found_keywords) if found_categories or found_keywords else '웹페이지'})",
            "summary": summary,
            "title": title,
            "domain": domain,
            "categories": found_categories,
            "keywords": found_keywords
        }
