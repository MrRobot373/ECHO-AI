# Training a Custom Car-Domain LLM (Unsloth + Tool Calling)

This guide explains how to fine-tune a small LLM with [Unsloth](https://github.com/unslothai/unsloth) so Echo AI becomes **genuinely intelligent about the car** *and* **calls its 20 tools more accurately**, then serve it through Ollama.

The result: a model (`echo-car:v1`) that you drop in by changing one environment variable.

---

## 1. Why fine-tune?

Today Echo AI uses stock models (see [`backend/config.py`](../backend/config.py)):

- `ollama_model = "qwen2.5:0.5b"` — conversational fallback
- `ollama_tool_model = "qwen2.5:1.5b"` — tool/intent decisions

These are general-purpose. A fine-tune fixes two weaknesses at once:

1. **Tool-calling accuracy** — the stock model sometimes picks the wrong tool, hallucinates arguments, or calls a tool when it should just answer. Training on examples of *your exact 20 tools* makes selection reliable.
2. **Car intelligence** — out of the box the model knows nothing about *this* car. Training on car knowledge (basics, maintenance, troubleshooting, FAQs) makes it a real automotive assistant instead of a generic chatbot.

---

## 2. Choose a base model

| Base model | Params | Why |
|---|---|---|
| **Qwen2.5-1.5B-Instruct** (recommended) | 1.5B | Already tool-aware, matches current `ollama_tool_model`, runs on CPU/Pi as Q4 GGUF |
| Qwen2.5-3B-Instruct | 3B | More headroom for reasoning; slower on Pi |
| Llama-3.2-3B-Instruct | 3B | Strong tool calling; larger |

This guide uses **Qwen2.5-1.5B-Instruct** so the fine-tuned model is a drop-in replacement for the current tool model.

Unsloth 4-bit base: `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit`

---

## 3. Understand the exact formats to match

Your training data must teach the model to produce output in the **same shapes the runtime expects**, or accuracy won't transfer.

### 3.1 Tool schema (from [`backend/commands/tools.py`](../backend/commands/tools.py))

Each of the 20 tools is defined with this structure:

```json
{
  "type": "function",
  "function": {
    "name": "navigate_maps",
    "description": "Open navigation / directions to a place in Google Maps.",
    "parameters": {
      "type": "object",
      "properties": {
        "destination": { "type": "string", "description": "Destination, e.g. 'Pune airport'" }
      },
      "required": ["destination"]
    }
  }
}
```

The full 20 tools:
`open_app`, `play_youtube`, `play_spotify`, `play_music`, `navigate_maps`, `web_search`, `get_weather`, `set_volume`, `set_brightness`, `send_whatsapp`, `send_text`, `make_call`, `control_setting`, `play_radio`, `get_car_info`, `get_vehicle_data`, `get_diagnostics`, `set_climate`, `control_vehicle`.

### 3.2 Request + response shape (from [`backend/pipeline/llm.py`](../backend/pipeline/llm.py))

Echo AI calls Ollama `/api/chat` with `messages` + `tools`. A tool decision response looks like:

```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      { "function": { "name": "navigate_maps", "arguments": { "destination": "Pune airport" } } }
    ]
  }
}
```

For a general question (no tool), the model should return plain `content` and **no** `tool_calls`.

### 3.3 Routing rule (from [`backend/commands/router.py`](../backend/commands/router.py))

The router injects this guidance — your training data should reflect it:

> Call a tool ONLY when the user wants an action (open, play, navigate, call, message, set volume/brightness, toggle a setting) or live data (weather/vehicle). For general questions, knowledge, or chit-chat, DO NOT call a tool — answer directly in one or two short, spoken sentences. Only use `web_search` when the user explicitly asks to search the web.

### 3.4 System prompt (from [`backend/config.py`](../backend/config.py))

```
You are Echo, a local automotive voice assistant. Keep replies concise,
conversational, and useful while driving. Ask one short follow-up only when needed.
```
Include this as the system message in every training example so the model learns the persona.

---

## 4. Build the dataset (three buckets)

Aim for **800–3,000** examples total. Format each as a chat conversation (ShareGPT/ChatML) with a `tools` field.

### Bucket A — Tool-calling examples (~50%)
Cover **every** tool, with varied phrasings, plus **negatives**.

```json
{
  "tools": [ /* the 20 tool specs from tools.py */ ],
  "messages": [
    {"role": "system", "content": "You are Echo, a local automotive voice assistant..."},
    {"role": "user", "content": "take me to the nearest charging station"},
    {"role": "assistant", "content": "",
     "tool_calls": [{"function": {"name": "navigate_maps", "arguments": {"destination": "nearest charging station"}}}]}
  ]
}
```

Include hard cases:
- `"set the AC to 21 degrees"` → `set_climate {"temperature": 21}`
- `"how much battery is left?"` → `get_vehicle_data {}`
- `"open the sunroof"` → `control_vehicle {"feature": "sunroof", "action": "open"}`
- `"call mom"` → `make_call {"contact": "mom"}`
- **Negative:** `"what's the capital of France?"` → assistant answers `"Paris."` with **no** tool call.
- **Negative:** `"thanks, you're great"` → friendly reply, no tool.

### Bucket B — Car knowledge Q&A (~35%)
Seed from [`car_info.md`](../car_info.md), then expand.

- **Primary:** range, charging time, tyre pressure, driving modes, boot space, warranty.
- **Secondary / troubleshooting:** "what does the orange turtle light mean?", "car won't start, what do I check?", "how does regenerative braking work?", "why is my range lower in winter?", "how do I connect the app?".

```json
{
  "messages": [
    {"role": "system", "content": "You are Echo, a local automotive voice assistant..."},
    {"role": "user", "content": "what does the turtle light mean?"},
    {"role": "assistant", "content": "The orange turtle light means the car is in reduced-power mode, usually from a low or overheating battery. Power returns once it recovers."}
  ]
}
```

### Bucket C — Persona / conversational (~15%)
Short, spoken, in-character replies ("Tell me a joke", "Good morning", "How are you?") so the model stays warm but concise.

> **Generating data fast:** use a strong model (e.g. GPT-4-class or a large local model) to draft examples from the tool list + `car_info.md`, then hand-review. Keep arguments realistic and always valid against the schema.

Save as `echo_car_dataset.jsonl` (one JSON object per line). Hold out ~10% for evaluation.

---

## 5. Fine-tune with Unsloth (Colab T4)

```python
# pip install unsloth
from unsloth import FastLanguageModel
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit",
    max_seq_length = 2048,
    load_in_4bit = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj","k_proj","v_proj","o_proj",
                      "gate_proj","up_proj","down_proj"],
    lora_alpha = 16,
    use_gradient_checkpointing = "unsloth",
)
```

Format the dataset with the Qwen chat template (Unsloth has `get_chat_template`), then train:

```python
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,          # your formatted echo_car_dataset
    dataset_text_field = "text",
    max_seq_length = 2048,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        num_train_epochs = 2,         # 1–3 epochs is plenty for a small set
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 10,
        optim = "adamw_8bit",
        output_dir = "outputs",
    ),
)
trainer.train()
```

Free Colab T4 trains a 1.5B LoRA on a few thousand examples in well under an hour.

---

## 6. Export to GGUF + import into Ollama

```python
# Export a quantized GGUF for CPU/Pi inference
model.save_pretrained_gguf("echo-car", tokenizer, quantization_method = "q4_k_m")
# produces echo-car/echo-car.Q4_K_M.gguf (or similar)
```

Create an Ollama **Modelfile** next to the GGUF:

```dockerfile
FROM ./echo-car.Q4_K_M.gguf

# Echo persona baked in
SYSTEM """You are Echo, a local automotive voice assistant. Keep replies concise, conversational, and useful while driving. Ask one short follow-up only when needed."""

PARAMETER temperature 0.2
PARAMETER num_ctx 2048
```

Import it:

```bash
ollama create echo-car:v1 -f Modelfile
ollama run echo-car:v1 "set the AC to 22 degrees"   # quick smoke test
```

---

## 7. Point Echo AI at the new model

Set the tool model (and optionally the chat model) to your fine-tune, then restart:

```bash
# Windows PowerShell
$env:OLLAMA_TOOL_MODEL = "echo-car:v1"
# optional: also use it for conversation
$env:OLLAMA_MODEL = "echo-car:v1"
```
```bash
# Linux / Pi
export OLLAMA_TOOL_MODEL=echo-car:v1
export OLLAMA_MODEL=echo-car:v1
```

Restart the server. No code changes — `config.py` reads these env vars.

---

## 8. Evaluate + iterate

Run your held-out set and measure:

| Metric | How |
|---|---|
| **Tool-selection accuracy** | % where the right tool name is chosen |
| **Argument correctness** | % where arguments match the schema + expected value |
| **No-tool precision** | general questions answered directly (no spurious tool) |
| **Car-answer quality** | manual review of knowledge/troubleshooting answers |

If a category is weak, add more examples of that case and retrain. Tool-calling accuracy improves fastest with more **negative** examples and more phrasing variety per tool.

---

## 9. Hardware notes

- **Training** needs a GPU — a free Colab T4 is enough for 1.5B/3B LoRA.
- **Inference** runs on the same targets as today (laptop / Pi / Android) via the Q4 GGUF. See [MINIMUM_HARDWARE_REQUIREMENTS.md](MINIMUM_HARDWARE_REQUIREMENTS.md) for per-device model sizing.

---

## Summary checklist

- [ ] Pick base: `unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit`
- [ ] Build `echo_car_dataset.jsonl` (tool calls + negatives, car Q&A, persona) matching the real tool schema + system prompt
- [ ] Fine-tune with Unsloth + SFTTrainer (1–3 epochs, LoRA r=16)
- [ ] Export Q4_K_M GGUF
- [ ] Write Modelfile (with Echo SYSTEM prompt) → `ollama create echo-car:v1`
- [ ] Set `OLLAMA_TOOL_MODEL=echo-car:v1` (and optionally `OLLAMA_MODEL`)
- [ ] Restart, evaluate on hold-out set, iterate
