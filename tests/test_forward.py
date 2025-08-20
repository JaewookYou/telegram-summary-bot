#!/usr/bin/env python3
"""
Forward 메시지 감지 테스트 스크립트
"""

import asyncio
from telethon import TelegramClient
from app.config import load_settings
from app.run import extract_forward_info

async def test_forward_detection():
    """Forward 메시지 감지 기능 테스트"""
    settings = load_settings()
    
    client = TelegramClient(settings.telegram_session, settings.telegram_api_id, settings.telegram_api_hash)
    
    try:
        await client.start()
        print("Telegram 클라이언트 시작됨")
        
        # 최근 메시지들을 가져와서 forward 여부 확인
        for channel in settings.source_channels[:3]:  # 처음 3개 채널만 테스트
            print(f"\n채널 {channel}에서 최근 메시지 확인 중...")
            
            try:
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=10)
                
                for msg in messages:
                    if msg.message:  # 텍스트 메시지만
                        is_forward, original_chat_id, original_message_id, original_text = extract_forward_info(msg)
                        
                        if is_forward:
                            print(f"  [FORWARD] msg_id={msg.id}")
                            print(f"    원본: chat_id={original_chat_id}, msg_id={original_message_id}")
                            print(f"    텍스트: {msg.message[:100]}...")
                        else:
                            print(f"  [NORMAL] msg_id={msg.id}")
                            print(f"    텍스트: {msg.message[:100]}...")
                        
                        print()
                        
            except Exception as e:
                print(f"  채널 {channel} 처리 중 오류: {e}")
                
    except Exception as e:
        print(f"테스트 중 오류: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(test_forward_detection())
