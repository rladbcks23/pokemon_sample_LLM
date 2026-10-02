"""Claude API provider (1단계). 한 번의 모델 호출을 스트리밍한다.

turn()은 ('text', 조각)을 내보내다가 마지막에 ('final', 메시지)를 낸다.
메시지 content는 Claude 형식 블록 그대로 (에이전트 루프가 다음 호출에 다시 넣음).
"""
import anthropic

import config


class ClaudeProvider:
    def __init__(self, model: str = config.LLM_MODEL, effort: str = config.LLM_EFFORT):
        self.client = anthropic.AsyncAnthropic()      # ANTHROPIC_API_KEY (llm/.env)
        self.model, self.effort = model, effort

    async def turn(self, system: str, messages: list, tools: list):
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=config.LLM_MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
            output_config={'effort': self.effort},
            cache_control={'type': 'ephemeral'},       # 도구·시스템 프롬프트·앞 대화를 캐시
            # 안전 분류기가 거절하면 서버에서 다른 모델로 다시 시도
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
        ) as stream:
            async for event in stream:
                if event.type == 'text':
                    yield 'text', event.text
            yield 'final', await stream.get_final_message()
