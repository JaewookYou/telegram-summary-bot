#!/usr/bin/env python3
"""
봇 API를 사용한 개인 DM 알림 시스템
Telegram Bot API를 통해 개인 chat_id로 알림을 보내는 기능
"""

import aiohttp
import logging
import sys
import os
from typing import Optional, Dict, Any

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings

logger = logging.getLogger("app.bot_notifier")


class BotNotifier:
    def __init__(self, settings: Settings):
        self.bot_token = settings.bot_token
        self.personal_chat_id = settings.personal_chat_id
        self.important_bot_token = settings.important_bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.important_base_url = f"https://api.telegram.org/bot{self.important_bot_token}" if self.important_bot_token else None
        
        if not self.personal_chat_id:
            logger.warning("PERSONAL_CHAT_ID가 설정되지 않았습니다. 개인 알림 기능이 비활성화됩니다.")
        
        if not self.important_bot_token:
            logger.warning("IMPORTANT_BOT_TOKEN이 설정되지 않았습니다. 중요 봇 알림 기능이 비활성화됩니다.")
    
    def send_personal_notification(self, message: str, disable_notification: bool = False) -> bool:
        """개인 DM으로 알림 메시지 전송"""
        if not self.personal_chat_id:
            logger.warning("개인 chat_id가 설정되지 않아 알림을 보낼 수 없습니다.")
            return False
        
        try:
            payload = {
                "chat_id": self.personal_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_notification": disable_notification
            }
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info(f"✅ 개인 알림 전송 성공: {self.personal_chat_id}")
                    return True
                else:
                    logger.error(f"❌ 봇 API 오류: {result.get('description', 'Unknown error')}")
                    return False
            else:
                logger.error(f"❌ HTTP 오류: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 개인 알림 전송 실패: {e}")
            return False
    
    async def send_personal_html(self, html_content: str, disable_notification: bool = False) -> bool:
        """HTML 형식의 개인 DM 전송"""
        if not self.personal_chat_id:
            logger.warning("개인 chat_id가 설정되지 않아 알림을 보낼 수 없습니다.")
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.personal_chat_id,
                    "text": html_content,
                    "parse_mode": "HTML",
                    "disable_notification": disable_notification
                }
                
                async with session.post(f"{self.base_url}/sendMessage", json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("ok"):
                            logger.info(f"✅ 개인 HTML 알림 전송 성공: {self.personal_chat_id}")
                            return True
                        else:
                            logger.error(f"❌ 봇 API 오류: {result.get('description', 'Unknown error')}")
                            return False
                    else:
                        logger.error(f"❌ HTTP 오류: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ 개인 HTML 알림 전송 실패: {e}")
            return False
    
    async def send_important_html(self, html_content: str, disable_notification: bool = False) -> bool:
        """HTML 형식의 중요 봇 전송"""
        if not self.important_bot_token or not self.important_base_url:
            logger.warning("중요 봇 토큰이 설정되지 않아 중요 알림을 보낼 수 없습니다.")
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.personal_chat_id,  # 같은 개인 chat_id로 전송
                    "text": html_content,
                    "parse_mode": "HTML",
                    "disable_notification": disable_notification
                }
                
                async with session.post(f"{self.important_base_url}/sendMessage", json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("ok"):
                            logger.info(f"✅ 중요 봇 HTML 알림 전송 성공: {self.personal_chat_id}")
                            return True
                        else:
                            logger.error(f"❌ 중요 봇 API 오류: {result.get('description', 'Unknown error')}")
                            return False
                    else:
                        logger.error(f"❌ 중요 봇 HTTP 오류: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ 중요 봇 HTML 알림 전송 실패: {e}")
            return False
    
    async def get_updates(self) -> Optional[Dict[str, Any]]:
        """봇 업데이트 확인 (chat_id 확보용)"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/getUpdates") as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("ok"):
                            return result
                        else:
                            logger.error(f"❌ 봇 API 오류: {result.get('description', 'Unknown error')}")
                            return None
                    else:
                        logger.error(f"❌ HTTP 오류: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ 봇 업데이트 확인 실패: {e}")
            return None
    
    def extract_personal_chat_id(self, updates: Dict[str, Any]) -> Optional[str]:
        """업데이트에서 개인 chat_id 추출"""
        try:
            results = updates.get("result", [])
            for update in results:
                message = update.get("message", {})
                chat = message.get("chat", {})
                chat_type = chat.get("type", "")
                
                # 개인 채팅인 경우
                if chat_type == "private":
                    chat_id = chat.get("id")
                    if chat_id:
                        logger.info(f"개인 chat_id 발견: {chat_id}")
                        return str(chat_id)
            
            logger.warning("개인 chat_id를 찾을 수 없습니다. 봇에게 /start를 보내주세요.")
            return None
            
        except Exception as e:
            logger.error(f"chat_id 추출 실패: {e}")
            return None


async def setup_personal_chat_id(settings: Settings) -> Optional[str]:
    """개인 chat_id 설정 (봇과 /start 후 자동 확보)"""
    notifier = BotNotifier(settings)
    
    logger.info("개인 chat_id 설정을 위해 봇 업데이트를 확인합니다...")
    logger.info("봇에게 /start를 보내고 Enter를 눌러주세요.")
    #input("Enter를 눌러 계속...")
    
    updates = await notifier.get_updates()
    if updates:
        chat_id = notifier.extract_personal_chat_id(updates)
        if chat_id:
            logger.info(f"✅ 개인 chat_id 설정 완료: {chat_id}")
            logger.info(f"환경변수에 추가하세요: PERSONAL_CHAT_ID={chat_id}")
            return chat_id
        else:
            logger.error("❌ 개인 chat_id를 찾을 수 없습니다.")
            return None
    else:
        logger.error("❌ 봇 업데이트를 가져올 수 없습니다.")
        return None


if __name__ == "__main__":
    import asyncio
    from app.config import load_settings
    
    async def main():
        settings = load_settings()
        await setup_personal_chat_id(settings)
    
    asyncio.run(main())
