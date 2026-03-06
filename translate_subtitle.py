import os
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from dotenv import load_dotenv

from subtitle import Subtitle

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o")
COST_PER_1K_INPUT = float(os.getenv("DEFAULT_MODEL_COST_PER_1K_TOKENS_INPUT", "0"))
COST_PER_1K_OUTPUT = float(os.getenv("DEFAULT_MODEL_COST_PER_1K_TOKENS_OUTPUT", "0"))
MAX_REQUEST_COST = float(os.getenv("MAX_REQUEST_COST", "1"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "2"))

DEFAULT_SYS_PROMPT = (
    "You are a professional translator. Respond only with the content translated. "
    "Do not add explanations, comments, or any extra text."
)

DEFAULT_USER_PROMPT = (
    "Please respect the original meaning, maintain the original format, "
    "and rewrite the following content in {target_language}.\n\n{context}"
)

CONTEXT_TEMPLATE = (
    "This is a subtitle file. Each line is formatted as INDEX|TEXT, "
    "where INDEX is the subtitle line number and TEXT is the dialogue. "
    "And \"<br>\" is a line break within a subtitle. "
    "Translate ONLY the TEXT portion of each line. Keep the INDEX and | separator and <br> line breaks unchanged. "
    "The INDEX numbers may not start at 1 — preserve the exact index numbers from the input in your response.\n\n"
    "CRITICAL REQUIREMENTS:\n"
    "1. You MUST translate every single line without changing the meaning\n"
    "2. Keep the exact format: INDEX|translated text\n"
    "3. If a line contains only sounds/exclamations, still translate them appropriately"
)


def _translate_batch(
    client: OpenAI,
    batch: list[str],
    user_message: str,
) -> tuple[list[str], dict | None]:
    content = "\n".join(batch)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": DEFAULT_SYS_PROMPT},
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "Sure, I will translate the content exactly as requested."},
        {"role": "user", "content": content},
    ]

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
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


def translate_subtitle(subtitle: Subtitle, target_language: str) -> Subtitle:
    global API_KEY, DEFAULT_MODEL
    if not API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in the environment variables.")
    if not DEFAULT_MODEL:
        raise ValueError("DEFAULT_MODEL is not set in the environment variables.")

    encoded_lines = subtitle.encode()
    total = len(encoded_lines)

    user_message = DEFAULT_USER_PROMPT.format(
        target_language=target_language,
        context=CONTEXT_TEMPLATE,
    )

    client = OpenAI(api_key=API_KEY)
    # Estimate tokens/cost for the whole job (one-time, not per-batch)
    content = "\n".join(encoded_lines)
    messages_for_count = [
        {"role": "system", "content": DEFAULT_SYS_PROMPT},
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "Sure, I will translate the content exactly as requested."},
        {"role": "user", "content": content},
    ]

    token_count = client.responses.input_tokens.count(
        model=DEFAULT_MODEL,
        instructions=DEFAULT_SYS_PROMPT,
        input=[  # type: ignore[arg-type]
            {"role": str(m["role"]), "content": str(m.get("content", ""))}
            for m in messages_for_count if m["role"] != "system"
        ],
    )
    content_token_count = client.responses.input_tokens.count(
        model=DEFAULT_MODEL,
        input=content,
    )

    input_tokens = token_count.input_tokens
    estimated_output_tokens = content_token_count.input_tokens
    estimated_total = input_tokens + estimated_output_tokens
    print(f"Estimated tokens: {input_tokens} (input) + ~{estimated_output_tokens} (output) = ~{estimated_total} total")

    estimated_input_cost = (input_tokens / 1000) * COST_PER_1K_INPUT
    estimated_output_cost = (estimated_output_tokens / 1000) * COST_PER_1K_OUTPUT
    estimated_cost = estimated_input_cost + estimated_output_cost
    print(f"Estimated cost:   ${estimated_input_cost:.4f} (input) + ~${estimated_output_cost:.4f} (output) = ~${estimated_cost:.4f}")

    if MAX_REQUEST_COST and estimated_cost > MAX_REQUEST_COST:
        raise ValueError(f"Estimated cost ${estimated_cost:.4f} exceeds MAX_REQUEST_COST ${MAX_REQUEST_COST:.4f}. Aborting.")

    batches = [encoded_lines[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    num_batches = len(batches)
    print(f"Translating {total} subtitle lines to {target_language} in {num_batches} batch(es) of up to {BATCH_SIZE}...")

    all_response_lines: list[str] = []
    total_actual_input = 0
    total_actual_output = 0

    for batch_num, batch in enumerate(batches, start=1):
        print(f"Batch {batch_num}/{num_batches} ({len(batch)} lines):")
        last_error: Exception | None = None
        for attempt in range(1, RETRY_COUNT + 2):  # 1 initial + RETRY_COUNT retries
            try:
                response_lines, usage_info = _translate_batch(client, batch, user_message)
                all_response_lines.extend(response_lines)
                if usage_info:
                    total_actual_input += usage_info.get("prompt_tokens", 0)
                    total_actual_output += usage_info.get("completion_tokens", 0)
                print(f"  Batch {batch_num}/{num_batches} completed.")
                break
            except Exception as e:
                last_error = e
                if attempt <= RETRY_COUNT:
                    print(f"  Attempt {attempt} failed: {e}. Retrying ({attempt}/{RETRY_COUNT})...")
                else:
                    raise ValueError(
                        f"Batch {batch_num}/{num_batches} failed after {RETRY_COUNT + 1} attempt(s): {last_error}"
                    ) from last_error

    if total_actual_input or total_actual_output:
        actual_total = total_actual_input + total_actual_output
        print(f"Actual tokens:    {total_actual_input} (input) + {total_actual_output} (output) = {actual_total} total")
        actual_input_cost = (total_actual_input / 1000) * COST_PER_1K_INPUT
        actual_output_cost = (total_actual_output / 1000) * COST_PER_1K_OUTPUT
        actual_cost = actual_input_cost + actual_output_cost
        print(f"Actual cost:      ${actual_input_cost:.4f} (input) + ${actual_output_cost:.4f} (output) = ${actual_cost:.4f}")

    print("Translation complete.")
    return subtitle.decode(all_response_lines)