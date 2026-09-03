from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# 从项目 .env 读取 LLM 供应商配置（与 src/app/config.py Settings 对齐）
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

import os

api_key = os.environ.get("LLM_API_KEYS", "").split(";")[0]
base_url = os.environ.get("LLM_BASE_URL", "")
model = os.environ.get("LLM_DEFAULT_MODEL", "")

missing = [k for k, v in [
    ("LLM_API_KEYS", api_key),
    ("LLM_BASE_URL", base_url),
    ("LLM_DEFAULT_MODEL", model),
] if not v]
if missing:
    raise SystemExit(
        f"缺少 LLM 配置，请先在 backend/.env 中填写: {', '.join(missing)}"
    )

client = OpenAI(api_key=api_key, base_url=base_url)

response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "user", "content": "你好，请用一句话介绍自己"}
    ],
)

import sys

sys.stdout.reconfigure(encoding="utf-8")
print(response.choices[0].message.content)