import asyncio
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from subtitle_translator.subtitle import Subtitle
from subtitle_translator import config


async def _translate_batch(
    client: AsyncOpenAI,
    batch: list[str],
    user_message: str,
) -> tuple[list[str], dict | None]:
    content = "\n".join(batch)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": config.DEFAULT_SYS_PROMPT},
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "Sure, I will translate the content exactly as requested."},
        {"role": "user", "content": content},
    ]

    response = await client.chat.completions.create(
        model=config.DEFAULT_MODEL,
        messages=messages,
        temperature=1,
    )

    response_text = response.choices[0].message.content
    if not response_text or response_text.strip() == "":
        raise ValueError("Received empty response from the translation API.")

    response_lines = [l for l in response_text.splitlines() if "|" in l]
    if len(response_lines) != len(batch):
        raise ValueError(f"Expected {len(batch)} translated lines, got {len(response_lines)}.")

    for i, line in enumerate(response_lines):
        if "|" not in line:
            raise ValueError(f"Line {i+1} in the response does not contain '|': {line}")
        index_part, text_part = line.split("|", 1)
        if not index_part.isdigit():
            raise ValueError(f"Line {i+1} has non-numeric index: {index_part}")
        if text_part.strip() == "":
            raise ValueError(f"Line {i+1} has empty translation text.")
        
        correct_index = batch[i].split("|", 1)[0].strip()
        if index_part.strip() != correct_index:
            raise ValueError(f"Line {i+1} index mismatch: expected '{correct_index}', got '{index_part.strip()}'")

    usage_info = None
    usage = getattr(response, "usage", None)
    if usage is not None:
        usage_info = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }

    return response_lines, usage_info


async def translate_subtitle(subtitle: Subtitle, target_language: str, on_progress=None) -> Subtitle:
    if not config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in the environment variables.")
    if not config.DEFAULT_MODEL:
        raise ValueError("DEFAULT_MODEL is not set in the environment variables.")

    encoded_lines = subtitle.encode()
    total = len(encoded_lines)

    user_message = config.DEFAULT_USER_PROMPT.format(
        target_language=target_language,
        context=config.CONTEXT_TEMPLATE,
    )

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    batches = [encoded_lines[i:i + config.BATCH_SIZE] for i in range(0, total, config.BATCH_SIZE)]
    num_batches = len(batches)

    print(f"Translating {total} subtitle lines to {target_language} in {num_batches} batch(es) of up to {config.BATCH_SIZE}...")

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
    batch_results = {}
    completed_lines = 0

    async def _translate_batch_with_retry(batch_num: int, batch: list[str]) -> tuple[int, list[str]]:
        async with semaphore:
            print(f"Batch {batch_num}/{num_batches} ({len(batch)} lines): Starting")
            last_error: Exception | None = None
            for attempt in range(1, config.RETRY_COUNT + 2):
                try:
                    response_lines, _ = await _translate_batch(client, batch, user_message)
                    print(f"Batch {batch_num}/{num_batches}: Completed")
                    return batch_num, response_lines
                except Exception as e:
                    last_error = e
                    if attempt <= config.RETRY_COUNT:
                        print(f"Batch {batch_num}/{num_batches}: Attempt {attempt} failed: {e}. Retrying ({attempt}/{config.RETRY_COUNT})...")
                    else:
                        raise ValueError(
                            f"Batch {batch_num}/{num_batches} failed after {config.RETRY_COUNT + 1} attempt(s): {last_error}"
                        ) from last_error
            raise RuntimeError("Unreachable")

    tasks = [asyncio.create_task(_translate_batch_with_retry(i + 1, batch)) for i, batch in enumerate(batches)]
    
    for coro in asyncio.as_completed(tasks):
        batch_num, response_lines = await coro
        batch_results[batch_num] = response_lines
        completed_lines += len(batches[batch_num - 1])
        if on_progress:
            on_progress(completed_lines, total)

    all_response_lines = [line for batch_num in sorted(batch_results.keys()) for line in batch_results[batch_num]]

    print("Translation complete.")
    return subtitle.decode(all_response_lines)
