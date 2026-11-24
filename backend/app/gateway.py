import logging
from dataclasses import dataclass

import litellm
from litellm.caching import Cache

from .config import Settings


logger = logging.getLogger(__name__)
SIMULATED_STATUSES = {"429", "500", "502", "503"}


class ProvidersUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Completion:
    reply: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int = 0


class Gateway:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.model
        self.simulation_enabled = settings.enable_failure_simulation
        self.key_ids = tuple(f"key_{index}" for index in range(1, len(settings.api_keys) + 1))
        self.cache = Cache(type="local", ttl=settings.cache_ttl_seconds)
        self.router = litellm.Router(
            model_list=[
                {
                    "model_name": key_id,
                    "model_info": {"id": key_id},
                    "litellm_params": {
                        "model": self.model,
                        "api_key": api_key,
                        **({"api_base": settings.api_base} if settings.api_base else {}),
                    },
                }
                for key_id, api_key in zip(self.key_ids, settings.api_keys, strict=True)
            ],
            num_retries=0,
            max_fallbacks=len(self.key_ids) - 1,
            timeout=settings.timeout_seconds,
            disable_cooldowns=True,
            cache_responses=False,
        )

    def simulated_failures(self, header: str | None) -> set[str]:
        if not self.simulation_enabled or header is None:
            return set()

        failed_keys = set()
        for pair in header.split(","):
            key, separator, status = (part.strip() for part in pair.partition("="))
            if not separator or status not in SIMULATED_STATUSES or (key != "*" and key not in self.key_ids):
                raise ValueError("invalid X-Simulate-Failure header")
            failed_keys.update(self.key_ids if key == "*" else (key,))
        return failed_keys

    async def complete(self, messages: list[dict[str, str]], failed_keys: set[str]) -> Completion:
        # Use model + the entire prompt as the cache identity, independent of routing aliases.
        cache_fields = {"model": self.model, "messages": messages}
        if not failed_keys:
            cached = self.cache.get_cache(**cache_fields)
            if cached is not None:
                return Completion(**cached, key_id=None)

        # Every simulated status is failover-eligible. Keep those keys out of this call's route.
        # A simulated call bypasses both cache reads and writes so it always exercises routing.
        eligible = [key_id for key_id in self.key_ids if key_id not in failed_keys]
        if not eligible:
            raise ProvidersUnavailable

        first, *fallbacks = eligible
        try:
            response = await self.router.acompletion(
                model=first,
                messages=messages,
                fallbacks=[{first: fallbacks}] if fallbacks else [],
                caching=False,
            )
        except Exception as exc:
            # Provider exception text can contain credentials, request data, or upstream URLs.
            logger.warning("Provider routes exhausted (%s)", type(exc).__name__)
            raise ProvidersUnavailable from None

        reply = response.choices[0].message.content if response.choices else None
        usage = response.usage
        key_id = response._hidden_params.get("model_id")
        if not isinstance(reply, str) or not reply.strip() or usage is None or key_id not in self.key_ids:
            logger.warning("Provider returned an incomplete chat response")
            raise ProvidersUnavailable

        counts = {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}
        if any(not isinstance(value, int) or value < 0 for value in counts.values()):
            logger.warning("Provider returned invalid token usage")
            raise ProvidersUnavailable

        if not failed_keys:
            self.cache.add_cache({"reply": reply, **counts}, **cache_fields)

        return Completion(reply, **counts, key_id=key_id, fallback_attempts=self.key_ids.index(key_id))
